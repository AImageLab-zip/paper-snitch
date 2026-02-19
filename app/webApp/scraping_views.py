"""
Views for managing conference scraping operations.
"""
import os
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from django.http import JsonResponse, StreamingHttpResponse, HttpResponseForbidden
from django.views import View
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import UserPassesTestMixin
from django.utils import timezone
from webApp.models import Conference


class StartScrapingView(UserPassesTestMixin, View):
    """Start scraping process for a conference (admin only)."""
    
    def test_func(self):
        """Only allow staff/superuser to start scraping."""
        return self.request.user.is_staff or self.request.user.is_superuser
    
    def post(self, request, conference_id):
        """Start the scraping process."""
        import json
        
        conference = get_object_or_404(Conference, id=conference_id)
        
        # Parse request data
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            data = {}
        
        limit = data.get('limit', None)
        
        # Check if already scraping
        if conference.is_scraping:
            return JsonResponse({
                'success': False,
                'message': 'Scraping is already in progress for this conference.',
                'is_scraping': True
            }, status=400)
        
        # Validate conference has necessary fields
        if not conference.papers_url:
            return JsonResponse({
                'success': False,
                'message': 'Conference does not have a papers URL configured.'
            }, status=400)
        
        # Save schema to file if it exists in database
        # If no schema exists, the scraper will try file or auto-generate with LLM
        if conference.scraping_schema:
            schema_dir = '/app/webApp/fixtures/scraper_schemas'
            os.makedirs(schema_dir, exist_ok=True)
            schema_filename = f"{conference.name.lower().replace(' ', '_')}_schema.json"
            schema_path = os.path.join(schema_dir, schema_filename)
            try:
                with open(schema_path, 'w') as f:
                    json.dump(conference.scraping_schema, f, indent=2)
            except Exception as e:
                # Log but don't fail - scraper will try to use existing file or auto-generate
                print(f"Warning: Could not save schema to file: {e}")
        
        # Mark as scraping
        conference.is_scraping = True
        conference.last_scrape_start = timezone.now()
        conference.last_scrape_status = 'running'
        
        # Generate log file path (inside container, mounted to host)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        safe_name = conference.name.replace(' ', '_').replace('/', '_')
        log_filename = f"{safe_name}_scrape_{timestamp}.log"
        # Use container path that's mounted to host via docker-compose
        log_path = f"/app/scraping_logs/{log_filename}"
        conference.scraping_log_file = log_path
        conference.save()
        
        # Ensure directory exists
        os.makedirs('/app/scraping_logs', exist_ok=True)
        
        # Start scraping in background thread
        def run_scraping():
            """Run the scraping command in a subprocess."""
            try:
                # Construct the scraping command
                cmd = [
                    'docker', 'exec', 'django-web-dev-bolelli',
                    'python', 'manage.py', 'scrape_conference',
                    conference.name,
                    conference.papers_url,
                    '--sync',
                    '--conference-id', str(conference.id)
                ]
                
                # Add limit if specified
                if limit and limit > 0:
                    cmd.extend(['--limit', str(limit)])
                
                # Run command and redirect output to log file
                with open(log_path, 'w') as log_file:
                    log_file.write(f"=== Scraping started at {datetime.now()} ===\n")
                    log_file.write(f"Conference: {conference.name}\n")
                    log_file.write(f"Papers URL: {conference.papers_url}\n")
                    if limit:
                        log_file.write(f"Limit: {limit} papers\n")
                    else:
                        log_file.write("Limit: All papers\n")
                    log_file.write(f"Command: {' '.join(cmd)}\n")
                    log_file.write("=" * 80 + "\n\n")
                    log_file.flush()
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )
                    
                    # Wait for completion
                    return_code = process.wait()
                    
                    log_file.write(f"\n{'=' * 80}\n")
                    log_file.write(f"=== Scraping ended at {datetime.now()} ===\n")
                    log_file.write(f"Exit code: {return_code}\n")
                
                # Update conference status
                conference.refresh_from_db()
                conference.is_scraping = False
                conference.last_scrape_end = timezone.now()
                conference.last_scrape_status = 'success' if return_code == 0 else 'failed'
                conference.save()
                
            except Exception as e:
                # Log error and update status
                with open(log_path, 'a') as log_file:
                    log_file.write(f"\n\nERROR: {str(e)}\n")
                
                conference.refresh_from_db()
                conference.is_scraping = False
                conference.last_scrape_end = timezone.now()
                conference.last_scrape_status = 'failed'
                conference.save()
        
        # Start thread
        thread = threading.Thread(target=run_scraping, daemon=True)
        thread.start()
        
        return JsonResponse({
            'success': True,
            'message': f'Scraping started for {conference.name}',
            'is_scraping': True,
            'log_file': log_filename
        })


class ScrapingStatusView(View):
    """Get the current scraping status for a conference."""
    
    def get(self, request, conference_id):
        """Return scraping status as JSON."""
        conference = get_object_or_404(Conference, id=conference_id)
        
        data = {
            'is_scraping': conference.is_scraping,
            'last_scrape_status': conference.last_scrape_status,
            'last_scrape_start': conference.last_scrape_start.isoformat() if conference.last_scrape_start else None,
            'last_scrape_end': conference.last_scrape_end.isoformat() if conference.last_scrape_end else None,
            'log_file': os.path.basename(conference.scraping_log_file) if conference.scraping_log_file else None,
            'paper_count': conference.papers.count(),
        }
        
        return JsonResponse(data)


class ScrapingLogView(View):
    """Stream or get scraping log content."""
    
    def get(self, request, conference_id):
        """Get log content."""
        conference = get_object_or_404(Conference, id=conference_id)
        
        if not conference.scraping_log_file:
            return JsonResponse({
                'success': True,
                'content': 'No scraping has been started yet for this conference.',
                'is_scraping': False
            })
        
        if not os.path.exists(conference.scraping_log_file):
            # File doesn't exist yet (scraping just started)
            return JsonResponse({
                'success': True,
                'content': 'Scraping is starting... Log file will be available shortly.',
                'is_scraping': conference.is_scraping
            })
        
        # Check if streaming is requested
        stream = request.GET.get('stream', 'false').lower() == 'true'
        
        if stream and conference.is_scraping:
            # Stream log content for ongoing scraping
            def log_stream():
                """Generator to stream log file content."""
                try:
                    with open(conference.scraping_log_file, 'r') as f:
                        # Send existing content
                        f.seek(0)
                        yield f.read()
                        
                        # Keep reading new content while scraping
                        while conference.is_scraping:
                            line = f.readline()
                            if line:
                                yield line
                            else:
                                # Wait a bit before checking again
                                import time
                                time.sleep(0.5)
                                conference.refresh_from_db()
                except Exception as e:
                    yield f"\n\nError reading log: {str(e)}\n"
            
            response = StreamingHttpResponse(log_stream(), content_type='text/plain')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            # Return full log content
            try:
                with open(conference.scraping_log_file, 'r') as f:
                    content = f.read()
                return JsonResponse({
                    'success': True,
                    'content': content,
                    'is_scraping': conference.is_scraping
                })
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'message': f'Error reading log file: {str(e)}'
                }, status=500)


class StopScrapingView(UserPassesTestMixin, View):
    """Stop an ongoing scraping process (admin only)."""
    
    def test_func(self):
        """Only allow staff/superuser to stop scraping."""
        return self.request.user.is_staff or self.request.user.is_superuser
    
    def post(self, request, conference_id):
        """Stop the scraping process."""
        conference = get_object_or_404(Conference, id=conference_id)
        
        if not conference.is_scraping:
            return JsonResponse({
                'success': False,
                'message': 'No scraping is currently in progress.'
            }, status=400)
        
        # Note: This is a simple implementation that just marks as stopped.
        # The actual subprocess will complete, but we update the status.
        # For a real kill, we'd need to track the process ID.
        conference.is_scraping = False
        conference.last_scrape_end = timezone.now()
        conference.last_scrape_status = 'cancelled'
        
        if conference.scraping_log_file:
            try:
                with open(conference.scraping_log_file, 'a') as f:
                    f.write(f"\n\n=== Scraping cancelled by user at {datetime.now()} ===\n")
            except:
                pass
        
        conference.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Scraping has been stopped.'
        })


class CreateAndScrapeConferenceView(UserPassesTestMixin, View):
    """Create a new conference and immediately start scraping (admin only)."""
    
    def test_func(self):
        """Only allow staff/superuser to create and scrape conferences."""
        return self.request.user.is_staff or self.request.user.is_superuser
    
    def post(self, request):
        """Create conference and start scraping."""
        import json
        
        # Check if this is a multipart form (with file upload) or JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle multipart form data (with file upload)
            name = request.POST.get('name', '').strip()
            acronym = request.POST.get('acronym', '').strip()
            year = request.POST.get('year', None)
            website_url = request.POST.get('website_url', '').strip()
            papers_url = request.POST.get('papers_url', '').strip()
            scraping_schema_str = request.POST.get('scraping_schema', '').strip()
            limit = request.POST.get('limit', None)
            logo_file = request.FILES.get('logo', None)
            
            # Parse scraping_schema if provided
            scraping_schema = None
            if scraping_schema_str:
                try:
                    scraping_schema = json.loads(scraping_schema_str)
                except json.JSONDecodeError:
                    return JsonResponse({
                        'success': False,
                        'message': 'Scraping schema must be valid JSON.'
                    }, status=400)
        else:
            # Handle JSON data (backward compatibility)
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid JSON data.'
                }, status=400)
            
            name = data.get('name', '').strip()
            acronym = data.get('acronym', '').strip()
            year = data.get('year', None)
            website_url = data.get('website_url', '').strip()
            papers_url = data.get('papers_url', '').strip()
            scraping_schema = data.get('scraping_schema', None)
            limit = data.get('limit', None)
            logo_file = None
        
        # Validate required fields
        if not name:
            return JsonResponse({
                'success': False,
                'message': 'Conference name is required.'
            }, status=400)
        
        if not papers_url:
            return JsonResponse({
                'success': False,
                'message': 'Papers URL is required.'
            }, status=400)
        
        # Validate year if provided
        if year:
            try:
                year = int(year)
                if year < 1900 or year > 2100:
                    return JsonResponse({
                        'success': False,
                        'message': 'Year must be between 1900 and 2100.'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Year must be a valid number.'
                }, status=400)
        
        # Check for duplicates (unique_together: acronym + year)
        if acronym and year:
            if Conference.objects.filter(acronym=acronym, year=year).exists():
                return JsonResponse({
                    'success': False,
                    'message': f'A conference with acronym "{acronym}" and year {year} already exists.'
                }, status=400)
        
        # Create conference
        try:
            conference = Conference.objects.create(
                name=name,
                acronym=acronym if acronym else None,
                year=year if year else None,
                website_url=website_url if website_url else None,
                papers_url=papers_url,
                scraping_schema=scraping_schema,
                logo=logo_file if logo_file else None
            )
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error creating conference: {str(e)}'
            }, status=500)
        
        # Save schema to file so scraper can find it
        if scraping_schema:
            schema_dir = '/app/webApp/fixtures/scraper_schemas'
            os.makedirs(schema_dir, exist_ok=True)
            schema_filename = f"{conference.name.lower().replace(' ', '_')}_schema.json"
            schema_path = os.path.join(schema_dir, schema_filename)
            try:
                with open(schema_path, 'w') as f:
                    json.dump(scraping_schema, f, indent=2)
            except Exception as e:
                # Log but don't fail - scraper will try to auto-generate
                print(f"Warning: Could not save schema to file: {e}")
        
        # Mark as scraping
        conference.is_scraping = True
        conference.last_scrape_start = timezone.now()
        conference.last_scrape_status = 'running'
        
        # Generate log file path
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        safe_name = conference.name.replace(' ', '_').replace('/', '_')
        log_filename = f"{safe_name}_scrape_{timestamp}.log"
        log_path = f"/app/scraping_logs/{log_filename}"
        conference.scraping_log_file = log_path
        conference.save()
        
        # Ensure directory exists
        os.makedirs('/app/scraping_logs', exist_ok=True)
        
        # Start scraping in background thread (reuse logic from StartScrapingView)
        def run_scraping():
            """Run the scraping command in a subprocess."""
            try:
                # Construct the scraping command
                cmd = [
                    'docker', 'exec', 'django-web-dev-bolelli',
                    'python', 'manage.py', 'scrape_conference',
                    conference.name,
                    conference.papers_url,
                    '--sync',
                    '--conference-id', str(conference.id)
                ]
                
                # Add limit if specified
                if limit and limit > 0:
                    cmd.extend(['--limit', str(limit)])
                
                # Run command and redirect output to log file
                with open(log_path, 'w') as log_file:
                    log_file.write(f"=== Scraping started at {datetime.now()} ===\n")
                    log_file.write(f"Conference: {conference.name}\n")
                    log_file.write(f"Papers URL: {conference.papers_url}\n")
                    if limit:
                        log_file.write(f"Limit: {limit} papers\n")
                    else:
                        log_file.write("Limit: All papers\n")
                    log_file.write(f"Command: {' '.join(cmd)}\n")
                    log_file.write("=" * 80 + "\n\n")
                    log_file.flush()
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )
                    
                    # Wait for completion
                    return_code = process.wait()
                    
                    log_file.write(f"\n{'=' * 80}\n")
                    log_file.write(f"=== Scraping ended at {datetime.now()} ===\n")
                    log_file.write(f"Exit code: {return_code}\n")
                
                # Update conference status
                conference.refresh_from_db()
                conference.is_scraping = False
                conference.last_scrape_end = timezone.now()
                conference.last_scrape_status = 'success' if return_code == 0 else 'failed'
                conference.save()
                
            except Exception as e:
                # Log error and update status
                with open(log_path, 'a') as log_file:
                    log_file.write(f"\n\nERROR: {str(e)}\n")
                
                conference.refresh_from_db()
                conference.is_scraping = False
                conference.last_scrape_end = timezone.now()
                conference.last_scrape_status = 'failed'
                conference.save()
        
        # Start thread
        thread = threading.Thread(target=run_scraping, daemon=True)
        thread.start()
        
        return JsonResponse({
            'success': True,
            'message': f'Conference "{name}" created and scraping started.',
            'conference_id': conference.id,
            'is_scraping': True,
            'log_file': log_filename
        })

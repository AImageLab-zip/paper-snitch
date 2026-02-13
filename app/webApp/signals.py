"""
Django signals for automatic database schema diagram generation.
"""
import subprocess
import os
from pathlib import Path
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.core.files import File
from django.conf import settings


@receiver(post_migrate)
def generate_schema_diagram(sender, **kwargs):
    """Generate database schema diagram after migrations."""
    
    # Only run for webApp migrations to avoid duplicates
    if sender.name != 'webApp':
        return
    
    try:
        from webApp.models_schema import DatabaseSchema
        
        # Get migration name if available
        migration_name = kwargs.get('plan', [])
        migration_str = str(migration_name) if migration_name else "auto-generated"
        
        # Generate schema using Django's graph_models command
        dot_file = Path(settings.BASE_DIR) / 'temp_schema.dot'
        png_file = Path(settings.BASE_DIR) / 'temp_schema.png'
        
        # Generate DOT file using django-extensions with app grouping
        result = subprocess.run(
            [
                'python', 'manage.py', 'graph_models', '-a', 
                '--group-models',  # Group models by app in visual frames
                '-o', str(dot_file)
            ],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"⚠️  Failed to generate schema DOT: {result.stderr}")
            return
        
        # Read DOT content
        with open(dot_file, 'r') as f:
            dot_content = f.read()
        
        # Generate PNG from DOT using graphviz
        result = subprocess.run(
            ['dot', '-Tpng', str(dot_file), '-o', str(png_file)],
            capture_output=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"⚠️  Failed to generate schema PNG")
            dot_file.unlink(missing_ok=True)
            return
        
        # Create DatabaseSchema record
        schema = DatabaseSchema.objects.create(
            migration_name=migration_str[:500],
            schema_dot=dot_content
        )
        
        # Attach the PNG file
        with open(png_file, 'rb') as f:
            schema.schema_diagram.save(
                f'schema_{schema.created_at.strftime("%Y%m%d_%H%M%S")}.png',
                File(f),
                save=True
            )
        
        # Cleanup temp files
        dot_file.unlink(missing_ok=True)
        png_file.unlink(missing_ok=True)
        
        print(f"✅ Database schema diagram generated: {schema.schema_diagram.name}")
        
    except Exception as e:
        print(f"⚠️  Error generating schema diagram: {e}")

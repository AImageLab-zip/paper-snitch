"""
Django management command to initialize reproducibility checklist criteria embeddings.

Usage:
    python manage.py initialize_criteria_embeddings
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from openai import OpenAI
import os

from webApp.models import ReproducibilityChecklistCriterion
from webApp.services.nodes.reproducibility_criteria import get_all_criteria

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Initialize reproducibility checklist criteria with embeddings"

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-creation of all embeddings even if they exist'
        )
        parser.add_argument(
            '--model',
            type=str,
            default='text-embedding-3-small',
            help='OpenAI embedding model to use (default: text-embedding-3-small)'
        )

    def handle(self, *args, **options):
        force = options['force']
        embedding_model = options['model']
        
        self.stdout.write(f"Initializing reproducibility checklist criteria embeddings")
        self.stdout.write(f"Embedding model: {embedding_model}")
        self.stdout.write(f"Force refresh: {force}")
        
        # Get OpenAI client
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY not found in environment"))
            return
        
        client = OpenAI(api_key=api_key)
        
        # Get all criteria definitions
        criteria = get_all_criteria()
        self.stdout.write(f"\nFound {len(criteria)} criteria to process")
        
        created_count = 0
        updated_count = 0
        skipped_count = 0
        
        for criterion in criteria:
            try:
                # Check if already exists
                exists = ReproducibilityChecklistCriterion.objects.filter(
                    criterion_id=criterion.criterion_id,
                    embedding_model=embedding_model
                ).exists()
                
                if exists and not force:
                    self.stdout.write(
                        f"  [{criterion.criterion_number:2d}] {criterion.criterion_name[:40]:40s} - SKIPPED (already exists)"
                    )
                    skipped_count += 1
                    continue
                
                # Generate embedding context
                context_text = criterion.get_embedding_context()
                
                # Generate embedding
                response = client.embeddings.create(
                    model=embedding_model,
                    input=context_text
                )
                
                embedding_vector = response.data[0].embedding
                dimension = len(embedding_vector)
                
                # Create or update in database
                with transaction.atomic():
                    if exists:
                        # Update existing
                        obj = ReproducibilityChecklistCriterion.objects.get(
                            criterion_id=criterion.criterion_id,
                            embedding_model=embedding_model
                        )
                        obj.criterion_number = criterion.criterion_number
                        obj.criterion_name = criterion.criterion_name
                        obj.category = criterion.category
                        obj.description = criterion.description
                        obj.criterion_context = context_text
                        obj.embedding = embedding_vector
                        obj.embedding_dimension = dimension
                        obj.save()
                        
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [{criterion.criterion_number:2d}] {criterion.criterion_name[:40]:40s} - UPDATED"
                            )
                        )
                        updated_count += 1
                    else:
                        # Create new
                        ReproducibilityChecklistCriterion.objects.create(
                            criterion_id=criterion.criterion_id,
                            criterion_number=criterion.criterion_number,
                            criterion_name=criterion.criterion_name,
                            category=criterion.category,
                            description=criterion.description,
                            criterion_context=context_text,
                            embedding=embedding_vector,
                            embedding_model=embedding_model,
                            embedding_dimension=dimension
                        )
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [{criterion.criterion_number:2d}] {criterion.criterion_name[:40]:40s} - CREATED"
                            )
                        )
                        created_count += 1
            
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [{criterion.criterion_number:2d}] {criterion.criterion_name[:40]:40s} - ERROR: {str(e)}"
                    )
                )
        
        # Summary
        self.stdout.write("\n" + "="*80)
        self.stdout.write(self.style.SUCCESS(f"✓ Created: {created_count}"))
        if updated_count > 0:
            self.stdout.write(self.style.WARNING(f"↻ Updated: {updated_count}"))
        if skipped_count > 0:
            self.stdout.write(f"⊘ Skipped: {skipped_count}")
        self.stdout.write(f"Total criteria: {len(criteria)}")
        
        # Verify database state
        total_in_db = ReproducibilityChecklistCriterion.objects.filter(
            embedding_model=embedding_model
        ).count()
        self.stdout.write(f"\nTotal criteria in database (model={embedding_model}): {total_in_db}")
        
        # Show category breakdown
        self.stdout.write("\nCriteria by category:")
        for category in ['models', 'datasets', 'experiments']:
            count = ReproducibilityChecklistCriterion.objects.filter(
                embedding_model=embedding_model,
                category=category
            ).count()
            self.stdout.write(f"  - {category}: {count}")

"""
Enhanced management command to view detailed workflow analysis results.

Usage:
    python manage.py view_analysis <paper_id>
    python manage.py view_analysis <paper_id> --run-id <run_id>
    python manage.py view_analysis <paper_id> --json
"""

from django.core.management.base import BaseCommand, CommandError
from workflow_engine.models import WorkflowRun, WorkflowNode, NodeArtifact, NodeLog
from webApp.models import Paper
import json


class Command(BaseCommand):
    help = 'View detailed analysis results for a paper'

    def add_arguments(self, parser):
        parser.add_argument('paper_id', type=int, help='Paper ID to view analysis for')
        parser.add_argument('--run-id', type=str, help='Specific run ID to view')
        parser.add_argument('--json', action='store_true', help='Output as JSON')

    def handle(self, *args, **options):
        paper_id = options['paper_id']
        run_id = options.get('run_id')
        as_json = options.get('json')

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f'Paper {paper_id} not found')

        # Get workflow run
        if run_id:
            try:
                run = WorkflowRun.objects.get(id=run_id, paper=paper)
            except WorkflowRun.DoesNotExist:
                raise CommandError(f'Run {run_id} not found for paper {paper_id}')
        else:
            run = WorkflowRun.objects.filter(paper=paper).order_by('-created_at').first()
            if not run:
                raise CommandError(f'No workflow runs found for paper {paper_id}')

        if as_json:
            self._output_json(run, paper)
        else:
            self._output_formatted(run, paper)

    def _output_json(self, run, paper):
        """Output complete analysis as JSON."""
        data = {
            'paper_id': paper.id,
            'paper_title': paper.title,
            'run_id': str(run.id),
            'run_number': run.run_number,
            'status': run.status,
            'created_at': run.created_at.isoformat(),
            'completed_at': run.completed_at.isoformat() if run.completed_at else None,
            'nodes': {}
        }

        for node in run.nodes.all():
            node_data = {
                'status': node.status,
                'artifacts': {},
                'logs': []
            }

            # Get artifacts
            for artifact in NodeArtifact.objects.filter(node=node):
                node_data['artifacts'][artifact.name] = artifact.inline_data

            # Get logs
            for log in NodeLog.objects.filter(node=node).order_by('timestamp'):
                node_data['logs'].append({
                    'level': log.level,
                    'timestamp': log.timestamp.isoformat(),
                    'message': log.message,
                    'context': log.context
                })

            data['nodes'][node.node_id] = node_data

        self.stdout.write(json.dumps(data, indent=2))

    def _output_formatted(self, run, paper):
        """Output formatted analysis for human reading."""
        self.stdout.write(self.style.SUCCESS(f'\n{"="*80}'))
        self.stdout.write(self.style.SUCCESS(f'Analysis Results for Paper {paper.id}'))
        self.stdout.write(self.style.SUCCESS(f'{"="*80}\n'))
        
        self.stdout.write(f'Title: {paper.title}')
        self.stdout.write(f'Run ID: {run.id}')
        self.stdout.write(f'Run Number: #{run.run_number}')
        self.stdout.write(f'Status: {run.status.upper()}')
        self.stdout.write(f'Created: {run.created_at}')
        if run.completed_at:
            duration = (run.completed_at - run.started_at).total_seconds() if run.started_at else None
            self.stdout.write(f'Duration: {duration:.1f}s' if duration else 'N/A')

        # Node A: Paper Type Classification
        self._display_classification_node(run)

        # Node B: Code Reproducibility
        self._display_reproducibility_node(run)

    def _display_classification_node(self, run):
        """Display paper type classification results."""
        try:
            node = run.nodes.get(node_id='paper_type_classification')
            artifact = NodeArtifact.objects.get(node=node, name='result')
            data = artifact.inline_data

            self.stdout.write(f'\n{"-"*80}')
            self.stdout.write(self.style.SUCCESS('NODE A: PAPER TYPE CLASSIFICATION'))
            self.stdout.write(f'{"-"*80}')
            
            self.stdout.write(f'Type: {data.get("paper_type", "unknown")}')
            self.stdout.write(f'Confidence: {data.get("confidence", 0):.2f}')
            self.stdout.write(f'\nReasoning:')
            self.stdout.write(f'{data.get("reasoning", "N/A")}')
            
            if data.get('key_evidence'):
                self.stdout.write(f'\nKey Evidence:')
                for evidence in data['key_evidence']:
                    self.stdout.write(f'  • {evidence}')

            # Token usage
            token_artifact = NodeArtifact.objects.filter(node=node, name='token_usage').first()
            if token_artifact:
                tokens = token_artifact.inline_data
                self.stdout.write(f'\n Tokens: {tokens.get("input_tokens")} in + {tokens.get("output_tokens")} out')

        except WorkflowNode.DoesNotExist:
            self.stdout.write(self.style.WARNING('\nNode A: Not found'))
        except NodeArtifact.DoesNotExist:
            self.stdout.write(self.style.WARNING('\nNode A: No results'))

    def _display_reproducibility_node(self, run):
        """Display code reproducibility analysis results."""
        try:
            node = run.nodes.get(node_id='code_reproducibility_analysis')
            artifact = NodeArtifact.objects.get(node=node, name='result')
            data = artifact.inline_data

            self.stdout.write(f'\n{"-"*80}')
            self.stdout.write(self.style.SUCCESS('NODE B: CODE REPRODUCIBILITY ANALYSIS'))
            self.stdout.write(f'{"-"*80}')

            # Code availability
            code_avail = data.get('code_availability', {})
            self.stdout.write(f'\n📦 Code Availability:')
            self.stdout.write(f'  Available: {code_avail.get("code_available", False)}')
            if code_avail.get('code_url'):
                self.stdout.write(f'  URL: {code_avail["code_url"]}')
            self.stdout.write(f'  Notes: {code_avail.get("availability_notes", "N/A")}')

            # Research methodology
            if data.get('research_methodology'):
                method = data['research_methodology']
                self.stdout.write(f'\n🔬 Research Methodology:')
                self.stdout.write(f'  Type: {method.get("methodology_type", "unknown").replace("_", " ").title()}')
                self.stdout.write(f'  Requires Training: {method.get("requires_training", "N/A")}')
                self.stdout.write(f'  Requires Datasets: {method.get("requires_datasets", "N/A")}')
                self.stdout.write(f'  Requires Splits: {method.get("requires_splits", "N/A")}')
                if method.get('methodology_notes'):
                    self.stdout.write(f'  Notes: {method["methodology_notes"]}')
            else:
                self.stdout.write(f'\n🔬 Research Methodology: Not classified')

            # Repository structure
            if data.get('repository_structure'):
                struct = data['repository_structure']
                self.stdout.write(f'\n🏗️  Repository Structure:')
                self.stdout.write(f'  Standalone: {struct.get("is_standalone")}')
                if struct.get('base_repository'):
                    self.stdout.write(f'  Based on: {struct["base_repository"]}')
                self.stdout.write(f'  Has Requirements: {struct.get("has_requirements")}')
            else:
                self.stdout.write(f'\n🏗️  Repository Structure: Not analyzed')

            # Code components
            if data.get('code_components'):
                comp = data['code_components']
                self.stdout.write(f'\n💻 Code Components:')
                self.stdout.write(f'  Training Code: {comp.get("has_training_code")}')
                self.stdout.write(f'  Evaluation Code: {comp.get("has_evaluation_code")}')
                self.stdout.write(f'  Documented Commands: {comp.get("has_documented_commands")}')
            else:
                self.stdout.write(f'\n💻 Code Components: Not analyzed')

            # Artifacts
            if data.get('artifacts'):
                art = data['artifacts']
                self.stdout.write(f'\n📊 Artifacts:')
                self.stdout.write(f'  Checkpoints: {art.get("has_checkpoints")}')
                self.stdout.write(f'  Dataset Links: {art.get("has_dataset_links")}')
                self.stdout.write(f'  Coverage: {art.get("dataset_coverage", "unknown")}')
            else:
                self.stdout.write(f'\n📊 Artifacts: Not analyzed')

            # Dataset Splits
            if data.get('dataset_splits'):
                splits = data['dataset_splits']
                self.stdout.write(f'\n🔢 Dataset Splits:')
                self.stdout.write(f'  Splits Specified: {splits.get("splits_specified")}')
                self.stdout.write(f'  Splits Provided: {splits.get("splits_provided")}')
                self.stdout.write(f'  Seeds Documented: {splits.get("random_seeds_documented")}')
                if splits.get('splits_notes'):
                    self.stdout.write(f'  Notes: {splits["splits_notes"]}')
            else:
                self.stdout.write(f'\n🔢 Dataset Splits: Not analyzed')

            # Documentation
            if data.get('documentation'):
                doc = data['documentation']
                self.stdout.write(f'\n📚 Documentation:')
                self.stdout.write(f'  README: {doc.get("has_readme")}')
                self.stdout.write(f'  Results Table: {doc.get("has_results_table")}')
                self.stdout.write(f'  Reproduction Commands: {doc.get("has_reproduction_commands")}')
            else:
                self.stdout.write(f'\n📚 Documentation: Not analyzed')

            # Reproducibility Score (computed programmatically)
            score = data.get('reproducibility_score', 0)
            self.stdout.write(f'\n⭐ REPRODUCIBILITY SCORE: {score}/10')
            
            # Score breakdown
            if data.get('score_breakdown'):
                breakdown = data['score_breakdown']
                self.stdout.write(f'\n📊 Score Breakdown:')
                self.stdout.write(f'  Code Completeness: {breakdown.get("code_completeness", 0):.2f}/3.0')
                self.stdout.write(f'  Dependencies: {breakdown.get("dependencies", 0):.2f}/1.0')
                self.stdout.write(f'  Artifacts: {breakdown.get("artifacts", 0):.2f}/2.5')
                self.stdout.write(f'  Dataset Splits: {breakdown.get("dataset_splits", 0):.2f}/2.0')
                self.stdout.write(f'  Documentation: {breakdown.get("documentation", 0):.2f}/2.0')

            # Overall assessment
            self.stdout.write(f'\n📝 Overall Assessment:')
            self.stdout.write(f'{data.get("overall_assessment", "N/A")}')

            # Recommendations (programmatically generated)
            if data.get('recommendations'):
                self.stdout.write(f'\n💡 Recommendations (Programmatic):')
                for i, rec in enumerate(data['recommendations'], 1):
                    self.stdout.write(f'  {i}. {rec}')

            # Token usage
            token_artifact = NodeArtifact.objects.filter(node=node, name='token_usage').first()
            if token_artifact:
                tokens = token_artifact.inline_data
                self.stdout.write(f'\n🎯 Tokens: {tokens.get("input_tokens")} in + {tokens.get("output_tokens")} out = {tokens.get("total_tokens")} total')

        except WorkflowNode.DoesNotExist:
            self.stdout.write(self.style.WARNING('\nNode B: Not found'))
        except NodeArtifact.DoesNotExist:
            self.stdout.write(self.style.WARNING('\nNode B: No results'))

        self.stdout.write(f'\n{"="*80}\n')

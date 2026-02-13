"""
Tests for workflow engine.

Run with:
    python manage.py test workflow_engine
"""
from django.test import TestCase
from django.contrib.auth.models import User
from webApp.models import Paper
from workflow_engine.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode
)
from workflow_engine.services.orchestrator import WorkflowOrchestrator


class WorkflowDefinitionTestCase(TestCase):
    """Test WorkflowDefinition model."""
    
    def setUp(self):
        self.dag_structure = {
            'nodes': [
                {'id': 'node1', 'type': 'celery', 'handler': 'test.handler1'},
                {'id': 'node2', 'type': 'celery', 'handler': 'test.handler2'},
                {'id': 'node3', 'type': 'celery', 'handler': 'test.handler3'}
            ],
            'edges': [
                {'from': 'node1', 'to': 'node2'},
                {'from': 'node2', 'to': 'node3'}
            ]
        }
    
    def test_create_workflow_definition(self):
        """Test creating a workflow definition."""
        workflow = WorkflowDefinition.objects.create(
            name='test_workflow',
            version=1,
            dag_structure=self.dag_structure,
            is_active=True
        )
        
        self.assertEqual(workflow.name, 'test_workflow')
        self.assertEqual(len(workflow.dag_structure['nodes']), 3)
        self.assertTrue(workflow.is_active)
    
    def test_dag_acyclic_validation(self):
        """Test that cycles are detected."""
        # Create a cycle: node1 -> node2 -> node3 -> node1
        cyclic_dag = {
            'nodes': [
                {'id': 'node1', 'type': 'celery', 'handler': 'test.handler1'},
                {'id': 'node2', 'type': 'celery', 'handler': 'test.handler2'},
                {'id': 'node3', 'type': 'celery', 'handler': 'test.handler3'}
            ],
            'edges': [
                {'from': 'node1', 'to': 'node2'},
                {'from': 'node2', 'to': 'node3'},
                {'from': 'node3', 'to': 'node1'}  # Creates cycle
            ]
        }
        
        workflow = WorkflowDefinition(
            name='cyclic_workflow',
            version=1,
            dag_structure=cyclic_dag
        )
        
        # Should raise ValidationError
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            workflow.full_clean()
    
    def test_get_dependencies(self):
        """Test getting node dependencies."""
        workflow = WorkflowDefinition.objects.create(
            name='test_workflow',
            version=1,
            dag_structure=self.dag_structure
        )
        
        # node2 depends on node1
        deps = workflow.get_dependencies('node2')
        self.assertEqual(deps, ['node1'])
        
        # node1 has no dependencies
        deps = workflow.get_dependencies('node1')
        self.assertEqual(deps, [])


class WorkflowOrchestratorTestCase(TestCase):
    """Test WorkflowOrchestrator."""
    
    def setUp(self):
        # Create test paper
        self.paper = Paper.objects.create(
            title='Test Paper',
            doi='10.1234/test'
        )
        
        # Create workflow definition
        self.workflow_def = WorkflowDefinition.objects.create(
            name='test_pipeline',
            version=1,
            dag_structure={
                'nodes': [
                    {'id': 'step1', 'type': 'celery', 'handler': 'test.handler1', 'max_retries': 3},
                    {'id': 'step2', 'type': 'celery', 'handler': 'test.handler2', 'max_retries': 3},
                    {'id': 'step3', 'type': 'celery', 'handler': 'test.handler3', 'max_retries': 3}
                ],
                'edges': [
                    {'from': 'step1', 'to': 'step2'},
                    {'from': 'step1', 'to': 'step3'}
                ]
            },
            is_active=True
        )
        
        self.orchestrator = WorkflowOrchestrator()
    
    def test_create_workflow_run(self):
        """Test creating a workflow run."""
        run = self.orchestrator.create_workflow_run(
            workflow_name='test_pipeline',
            paper=self.paper
        )
        
        self.assertIsNotNone(run)
        self.assertEqual(run.paper, self.paper)
        self.assertEqual(run.status, 'pending')
        self.assertEqual(run.nodes.count(), 3)
    
    def test_initial_ready_nodes(self):
        """Test that nodes with no dependencies are marked ready."""
        run = self.orchestrator.create_workflow_run(
            workflow_name='test_pipeline',
            paper=self.paper
        )
        
        # step1 has no dependencies, should be ready
        ready_nodes = run.nodes.filter(status='ready')
        self.assertEqual(ready_nodes.count(), 1)
        self.assertEqual(ready_nodes.first().node_id, 'step1')
        
        # step2 and step3 depend on step1, should be pending
        pending_nodes = run.nodes.filter(status='pending')
        self.assertEqual(pending_nodes.count(), 2)
    
    def test_dependency_resolution(self):
        """Test that completing a node marks dependents as ready."""
        run = self.orchestrator.create_workflow_run(
            workflow_name='test_pipeline',
            paper=self.paper
        )
        
        # Complete step1
        step1 = run.nodes.get(node_id='step1')
        self.orchestrator.mark_node_completed(step1, output_data={'result': 'done'})
        
        # step2 and step3 should now be ready
        run.refresh_from_db()
        ready_count = run.nodes.filter(status='ready').count()
        self.assertEqual(ready_count, 2)
    
    def test_workflow_completion(self):
        """Test workflow completion detection."""
        run = self.orchestrator.create_workflow_run(
            workflow_name='test_pipeline',
            paper=self.paper
        )
        
        # Complete all nodes
        for node in run.nodes.all():
            node.status = 'ready'
            node.save()
            self.orchestrator.mark_node_completed(node, output_data={})
        
        # Workflow should be completed
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        self.assertIsNotNone(run.completed_at)
    
    def test_node_failure_propagation(self):
        """Test that failing a node skips dependents."""
        run = self.orchestrator.create_workflow_run(
            workflow_name='test_pipeline',
            paper=self.paper
        )
        
        # Fail step1
        step1 = run.nodes.get(node_id='step1')
        step1.attempt_count = step1.max_retries  # Exhaust retries
        step1.save()
        
        self.orchestrator.mark_node_failed(
            step1,
            error_message='Test failure',
            retry=True
        )
        
        run.refresh_from_db()
        
        # Dependent nodes should be skipped
        skipped = run.nodes.filter(status='skipped')
        self.assertTrue(skipped.exists())


class WorkflowUtilsTestCase(TestCase):
    """Test utility functions."""
    
    def setUp(self):
        self.paper = Paper.objects.create(
            title='Test Paper',
            doi='10.1234/test'
        )
        
        WorkflowDefinition.objects.create(
            name='test_workflow',
            version=1,
            dag_structure={
                'nodes': [
                    {'id': 'node1', 'type': 'celery', 'handler': 'test.handler1'}
                ],
                'edges': []
            },
            is_active=True
        )
    
    def test_get_workflow_statistics(self):
        """Test getting workflow statistics."""
        from workflow_engine.utils import get_workflow_statistics
        
        stats = get_workflow_statistics()
        
        self.assertIn('total_runs', stats)
        self.assertIn('active_runs', stats)
        self.assertIn('total_nodes', stats)
        self.assertIsInstance(stats['total_runs'], int)

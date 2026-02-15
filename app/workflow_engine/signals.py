"""
Signal handlers for workflow engine.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='workflow_engine.WorkflowDefinition')
def generate_workflow_diagram(sender, instance, created, **kwargs):
    """
    Automatically generate DAG diagram when a WorkflowDefinition is saved.
    
    This ensures that diagrams are always up-to-date, whether the workflow
    is created via management command, admin interface, or API.
    """
    # Skip if this is an update of just the dag_diagram field to avoid recursion
    if 'update_fields' in kwargs and kwargs['update_fields'] == {'dag_diagram'}:
        return
    
    from workflow_engine.utils import generate_dag_diagram
    
    # Generate diagram if it doesn't exist or if the workflow was just created
    if not instance.dag_diagram or created:
        logger.info(f"Generating DAG diagram for workflow: {instance.name}")
        
        # Store whether diagram existed before
        had_diagram = bool(instance.dag_diagram)
        
        success = generate_dag_diagram(instance)
        
        if success:
            # The diagram field is now set on the instance, but not saved to DB
            # We need to save it (this won't cause recursion due to the update_fields check above)
            instance.save(update_fields=['dag_diagram'])
            logger.info(f"DAG diagram {'updated' if had_diagram else 'generated'} for workflow: {instance.name}")
        else:
            logger.warning(f"Failed to generate DAG diagram for workflow: {instance.name}")


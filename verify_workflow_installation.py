#!/usr/bin/env python3
"""
Verification script for workflow engine installation.

Run with:
    python3 verify_installation.py
"""

import sys
import os

# Add app to path
sys.path.insert(0, '/home/administrator/papersnitch/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings.development')

import django
django.setup()

def check_installation():
    """Verify workflow engine installation."""
    
    print("🔍 Verifying Workflow Engine Installation...\n")
    
    checks_passed = 0
    checks_total = 0
    
    # Check 1: App in INSTALLED_APPS
    checks_total += 1
    try:
        from django.conf import settings
        if 'workflow_engine.apps.WorkflowEngineConfig' in settings.INSTALLED_APPS:
            print("✅ workflow_engine app is in INSTALLED_APPS")
            checks_passed += 1
        else:
            print("❌ workflow_engine app NOT in INSTALLED_APPS")
    except Exception as e:
        print(f"❌ Error checking INSTALLED_APPS: {e}")
    
    # Check 2: Models importable
    checks_total += 1
    try:
        from workflow_engine.models import (
            WorkflowDefinition, WorkflowRun, WorkflowNode,
            NodeArtifact, NodeLog, LangGraphCheckpoint
        )
        print("✅ All models import successfully")
        checks_passed += 1
    except Exception as e:
        print(f"❌ Error importing models: {e}")
    
    # Check 3: Orchestrator importable
    checks_total += 1
    try:
        from workflow_engine.services.orchestrator import WorkflowOrchestrator
        print("✅ WorkflowOrchestrator imports successfully")
        checks_passed += 1
    except Exception as e:
        print(f"❌ Error importing orchestrator: {e}")
    
    # Check 4: Tasks importable
    checks_total += 1
    try:
        from workflow_engine.tasks import (
            workflow_scheduler_task,
            execute_node_task,
            start_workflow_task
        )
        print("✅ Celery tasks import successfully")
        checks_passed += 1
    except Exception as e:
        print(f"❌ Error importing tasks: {e}")
    
    # Check 5: Management commands
    checks_total += 1
    try:
        import os
        cmd_path = '/home/administrator/papersnitch/app/workflow_engine/management/commands'
        if os.path.exists(os.path.join(cmd_path, 'create_workflow.py')):
            print("✅ Management commands exist")
            checks_passed += 1
        else:
            print("❌ Management commands not found")
    except Exception as e:
        print(f"❌ Error checking management commands: {e}")
    
    # Check 6: Database tables (if migrated)
    checks_total += 1
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name LIKE 'workflow_engine_%'"
            )
            table_count = cursor.fetchone()[0]
            
            if table_count >= 6:
                print(f"✅ Database tables exist ({table_count} tables)")
                checks_passed += 1
            elif table_count > 0:
                print(f"⚠️  Partial migration ({table_count} tables found, expected 6)")
                print("   Run: python3 manage.py migrate workflow_engine")
            else:
                print("⚠️  Database tables not created yet")
                print("   Run: python3 manage.py makemigrations workflow_engine")
                print("   Then: python3 manage.py migrate workflow_engine")
    except Exception as e:
        print(f"⚠️  Could not check database: {e}")
    
    # Check 7: Workflow definition exists (if migrated)
    checks_total += 1
    try:
        from workflow_engine.models import WorkflowDefinition
        count = WorkflowDefinition.objects.count()
        if count > 0:
            print(f"✅ Workflow definitions exist ({count} found)")
            checks_passed += 1
        else:
            print("⚠️  No workflow definitions yet")
            print("   Run: python3 manage.py create_workflow")
    except Exception as e:
        print(f"⚠️  Could not check workflows: {e}")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Summary: {checks_passed}/{checks_total} checks passed")
    print(f"{'='*60}\n")
    
    if checks_passed == checks_total:
        print("🎉 Workflow engine is fully installed and ready!")
        print("\nNext steps:")
        print("1. Start Celery worker: celery -A web worker -l info")
        print("2. Start Celery beat: celery -A web beat -l info")
        print("3. Test: python3 manage.py start_workflow pdf_analysis_pipeline 1")
    elif checks_passed >= 5:
        print("✅ Workflow engine is installed!")
        print("\nTo complete setup:")
        if 'table_count' in locals() and table_count == 0:
            print("1. Run: python3 manage.py makemigrations workflow_engine")
            print("2. Run: python3 manage.py migrate workflow_engine")
        print("3. Run: python3 manage.py create_workflow")
        print("4. Start Celery worker and beat")
    else:
        print("❌ Installation incomplete. Please check errors above.")
    
    return checks_passed, checks_total


if __name__ == '__main__':
    try:
        passed, total = check_installation()
        sys.exit(0 if passed == total else 1)
    except Exception as e:
        print(f"\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

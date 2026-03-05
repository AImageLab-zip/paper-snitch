from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove LangGraphCheckpoint from Django's model state.

    The underlying table never existed in production so we use
    SeparateDatabaseAndState to update the migration state only,
    without issuing a DROP TABLE that would fail on all environments
    where the table was never created.
    """

    dependencies = [
        ('workflow_engine', '0010_nodeartifact_file'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],   # do nothing in the DB (table doesn't exist)
            state_operations=[
                migrations.DeleteModel(
                    name='LangGraphCheckpoint',
                ),
            ],
        ),
    ]

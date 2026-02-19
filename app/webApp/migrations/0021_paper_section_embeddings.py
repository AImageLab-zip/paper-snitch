# Generated migration file - rename to appropriate number
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('webApp', '0020_alter_paper_conference'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaperSectionEmbedding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section_type', models.CharField(max_length=50, help_text='Section type: abstract, introduction, methods, results, conclusion, etc.')),
                ('section_text', models.TextField(help_text='Text content of the section')),
                ('embedding', models.JSONField(help_text='Vector embedding as JSON array')),
                ('embedding_model', models.CharField(default='text-embedding-3-small', max_length=50)),
                ('embedding_dimension', models.IntegerField(default=1536)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_embeddings', to='webApp.paper')),
            ],
            options={
                'db_table': 'paper_section_embeddings',
                'indexes': [
                    models.Index(fields=['paper', 'section_type'], name='idx_paper_section'),
                    models.Index(fields=['section_type'], name='idx_section_type'),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name='papersectionembedding',
            constraint=models.UniqueConstraint(fields=('paper', 'section_type', 'embedding_model'), name='unique_paper_section_embedding'),
        ),
    ]

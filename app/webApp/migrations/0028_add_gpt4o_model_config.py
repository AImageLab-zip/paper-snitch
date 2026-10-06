from django.db import migrations


def add_gpt4o(apps, schema_editor):
    LLMModelConfig = apps.get_model("webApp", "LLMModelConfig")
    LLMModelConfig.objects.get_or_create(
        model_key="gpt4o",
        defaults=dict(
            visual_name="GPT-4o",
            model="gpt-4o",
            api_key_env_var="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            token_var="TOTAL_TOKEN_OPENAI_4O",
            temperature=1.0,
            reasoning_effort=None,
            is_active=True,
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("webApp", "0027_paper_file_sha256_paper_is_public_paper_owner_and_more"),
    ]

    operations = [migrations.RunPython(add_gpt4o, migrations.RunPython.noop)]

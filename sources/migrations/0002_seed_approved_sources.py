from django.db import migrations


def seed_approved_sources(apps, schema_editor):
    Source = apps.get_model("sources", "Source")
    Source.objects.create(
        name="personal_records",
        base_url="",
        terms_notes="N/A — first-party data, no external terms govern this source",
        rate_limit=None,
    )
    Source.objects.create(
        name="manual_capture",
        base_url="",
        terms_notes="N/A — no automation involved, no external terms apply to this source",
        rate_limit=None,
    )


def unseed_approved_sources(apps, schema_editor):
    Source = apps.get_model("sources", "Source")
    Source.objects.filter(name__in=["personal_records", "manual_capture"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_approved_sources, unseed_approved_sources),
    ]

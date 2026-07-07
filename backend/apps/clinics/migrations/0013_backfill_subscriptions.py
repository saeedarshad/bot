"""Give every existing clinic an ACTIVE subscription so nothing is cut off when
suspension enforcement goes live. New clinics get one via seed_demo / admin."""
from django.db import migrations


def backfill(apps, schema_editor):
    Clinic = apps.get_model("clinics", "Clinic")
    Subscription = apps.get_model("clinics", "Subscription")
    for clinic in Clinic.objects.all():
        Subscription.objects.get_or_create(
            clinic=clinic, defaults={"plan": "demo", "status": "active"}
        )


def unbackfill(apps, schema_editor):
    apps.get_model("clinics", "Subscription").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("clinics", "0012_subscription")]
    operations = [migrations.RunPython(backfill, unbackfill)]

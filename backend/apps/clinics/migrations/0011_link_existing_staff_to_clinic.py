"""Phase 4 tenant identity: bind existing (pre-multi-tenant) staff users to a
clinic so they keep working after current_clinic() started resolving per-user.

Any non-superuser without a profile is attached to the single active clinic if
there's exactly one (the demo/single-tenant reality this migration runs against).
Superusers are intentionally left profile-less — they're the platform operator."""
from django.db import migrations


def link_staff(apps, schema_editor):
    Clinic = apps.get_model("clinics", "Clinic")
    UserProfile = apps.get_model("clinics", "UserProfile")
    User = apps.get_model("auth", "User")

    active = list(Clinic.objects.filter(is_active=True).order_by("id"))
    if len(active) != 1:
        # Zero or many clinics: no unambiguous binding. Fresh installs (0 clinics)
        # get profiles via seed_demo; a genuinely multi-clinic DB must be linked
        # by hand in admin.
        return
    clinic = active[0]
    for user in User.objects.filter(is_superuser=False):
        if not UserProfile.objects.filter(user=user).exists():
            UserProfile.objects.create(user=user, clinic=clinic)


def unlink(apps, schema_editor):
    UserProfile = apps.get_model("clinics", "UserProfile")
    UserProfile.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("clinics", "0010_userprofile")]
    operations = [migrations.RunPython(link_staff, unlink)]

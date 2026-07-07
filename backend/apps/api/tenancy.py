"""Request → clinic resolution. The single place that decides which tenant a
dashboard request belongs to. Phase 4: a staff user is bound to exactly one
clinic via UserProfile; a superuser (platform operator) is not clinic-scoped and
falls back to the first active clinic for the rare case they open the dashboard.

Suspension enforcement layers on top of this in Slice 2."""
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.clinics.models import Clinic


def clinic_for_request(request) -> Clinic:
    """The clinic the authenticated user may act on, or raise NotFound.

    Never returns another tenant's clinic: a staff user only ever resolves to the
    clinic on their profile."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise NotFound("No active clinic configured.")

    profile = getattr(user, "profile", None)
    clinic = profile.clinic if profile is not None else None

    if clinic is None and user.is_superuser:
        # Operator convenience only — superusers primarily work in Django admin.
        clinic = Clinic.objects.filter(is_active=True).order_by("id").first()

    if clinic is None or not clinic.is_active:
        raise NotFound("No active clinic configured.")
    if clinic.service_suspended:
        # Unpaid/cancelled: dashboard is cut off until the operator reactivates.
        raise PermissionDenied(
            "This clinic's subscription is inactive. Contact the operator."
        )
    return clinic

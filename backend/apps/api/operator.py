"""Superuser operator console API (Phase 4). Lets the platform operator run the
multi-tenant system from the app's own UI instead of Django admin: add/delete
clinics, create a clinic's first staff login, and set each clinic's pay status.

Every endpoint is gated by IsSuperUser — ordinary clinic staff can never reach
it. Billing stays off-platform; the operator flips `status` by hand."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.clinics.models import Clinic, Subscription, SubscriptionStatus, UserProfile

User = get_user_model()


class IsSuperUser(BasePermission):
    """Platform operator only. Note DRF's IsAdminUser checks is_staff; the
    operator boundary is is_superuser (clinic staff are is_staff too)."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_superuser)


class OperatorSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ["plan", "status", "paid_through", "notes", "updated_at"]


class OperatorClinicSerializer(serializers.ModelSerializer):
    subscription = OperatorSubscriptionSerializer(read_only=True)
    staff_count = serializers.SerializerMethodField()
    patient_count = serializers.SerializerMethodField()

    class Meta:
        model = Clinic
        fields = [
            "id", "name", "slug", "timezone", "currency", "is_active",
            "whatsapp_phone_number_id", "created_at",
            "subscription", "staff_count", "patient_count",
        ]

    def get_staff_count(self, obj) -> int:
        return obj.staff_profiles.count()

    def get_patient_count(self, obj) -> int:
        return obj.patients.count()


def _unique_slug(name: str) -> str:
    base = slugify(name) or "clinic"
    slug = base
    i = 2
    while Clinic.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


class OperatorClinicViewSet(viewsets.ModelViewSet):
    """Clinics as the operator sees them, with subscription + staff summaries."""

    permission_classes = [IsSuperUser]
    serializer_class = OperatorClinicSerializer
    queryset = (
        Clinic.objects.all().select_related("subscription").order_by("name")
    )

    def create(self, request, *args, **kwargs):
        """Create a clinic + an ACTIVE subscription (and optionally its first
        staff login) in one call."""
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "name is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        staff_username = (request.data.get("staff_username") or "").strip()
        staff_password = request.data.get("staff_password") or ""
        if staff_username and len(staff_password) < 8:
            return Response(
                {"detail": "staff_password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if staff_username and User.objects.filter(username=staff_username).exists():
            return Response(
                {"detail": "That staff username is already taken."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            clinic = Clinic.objects.create(
                name=name,
                slug=_unique_slug(request.data.get("slug") or name),
                timezone=request.data.get("timezone") or "America/New_York",
                currency=request.data.get("currency") or "USD",
                whatsapp_phone_number_id=request.data.get("whatsapp_phone_number_id") or "",
            )
            Subscription.objects.create(
                clinic=clinic,
                plan=request.data.get("plan") or "demo",
                status=SubscriptionStatus.ACTIVE,
            )
            if staff_username:
                user = User.objects.create_user(
                    username=staff_username, password=staff_password, is_staff=True
                )
                UserProfile.objects.create(user=user, clinic=clinic)

        clinic.refresh_from_db()
        return Response(
            self.get_serializer(clinic).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["patch"])
    def subscription(self, request, pk=None):
        """Set the clinic's pay status (the off-platform billing flip)."""
        clinic = self.get_object()
        sub, _ = Subscription.objects.get_or_create(clinic=clinic)

        new_status = request.data.get("status")
        if new_status is not None:
            if new_status not in SubscriptionStatus.values:
                return Response(
                    {"detail": f"Invalid status '{new_status}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            sub.status = new_status
        if "plan" in request.data:
            sub.plan = request.data.get("plan") or sub.plan
        if "paid_through" in request.data:
            sub.paid_through = request.data.get("paid_through") or None
        if "notes" in request.data:
            sub.notes = request.data.get("notes") or ""
        sub.save()
        clinic.refresh_from_db()
        return Response(self.get_serializer(clinic).data)

    @action(detail=True, methods=["get", "post"])
    def staff(self, request, pk=None):
        """List or add staff logins bound to this clinic."""
        clinic = self.get_object()
        if request.method == "GET":
            return Response(self._staff_list(clinic))

        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or len(password) < 8:
            return Response(
                {"detail": "username and an 8+ char password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username, password=password, is_staff=True
                )
                UserProfile.objects.create(user=user, clinic=clinic)
        except IntegrityError:
            return Response(
                {"detail": "That username is already taken."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self._staff_list(clinic), status=status.HTTP_201_CREATED)

    @staticmethod
    def _staff_list(clinic):
        return [
            {
                "id": p.user_id,
                "username": p.user.username,
                "is_active": p.user.is_active,
            }
            for p in clinic.staff_profiles.select_related("user").order_by(
                "user__username"
            )
        ]

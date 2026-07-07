from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import EscalationTicket, FAQEntry
from apps.messaging.models import (
    Message,
    RecallCampaign,
    RecallRule,
    ScheduledMessageKind,
    ScheduledMessageStatus,
)
from apps.scheduling.models import (
    ACTIVE_STATUSES,
    Appointment,
    Practitioner,
    ScheduleException,
    ScheduleRule,
    Service,
)


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id", "name", "duration_min", "price_min", "price_max",
            "price_display", "requires_practitioner", "practitioners",
            "buffer_after_min", "is_active",
        ]
        # Empty `practitioners` = any active doctor can perform it.
        extra_kwargs = {"practitioners": {"required": False}}


class PractitionerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Practitioner
        fields = ["id", "name", "title", "specialty", "is_active"]


class PatientSerializer(serializers.ModelSerializer):
    preferred_practitioner_name = serializers.CharField(
        source="preferred_practitioner.name", read_only=True, default=None
    )

    class Meta:
        model = Patient
        fields = [
            "id", "name", "phone_e164", "preferred_channel", "language_pref",
            "no_show_count", "opted_out_at", "notes", "last_seen_at", "created_at",
            "preferred_practitioner", "preferred_practitioner_name",
        ]


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone_e164", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    practitioner_name = serializers.CharField(
        source="practitioner.name", read_only=True, default=None
    )
    at_risk = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "patient_name", "patient_phone", "service", "service_name",
            "practitioner", "practitioner_name", "starts_at", "ends_at",
            "status", "source", "notes", "created_at",
            "patient_confirmed_at", "at_risk",
        ]
        read_only_fields = ["ends_at", "created_at", "patient_confirmed_at"]

    def get_at_risk(self, obj) -> bool:
        """An upcoming appointment whose 24h reminder went out but the patient
        never confirmed — the staff should nudge it. Reads prefetched reminders
        (see AppointmentViewSet) so this stays O(1) per row."""
        if (
            obj.status not in ACTIVE_STATUSES
            or obj.patient_confirmed_at is not None
            or obj.starts_at < timezone.now()
        ):
            return False
        return any(
            m.kind == ScheduledMessageKind.REMINDER_24H
            and m.status == ScheduledMessageStatus.SENT
            for m in obj.scheduled_messages.all()
        )

    def create(self, validated_data):
        # Staff override: compute ends_at from service duration; no conflict block.
        service = validated_data["service"]
        validated_data["ends_at"] = validated_data["starts_at"] + timedelta(
            minutes=service.duration_min
        )
        validated_data.setdefault("source", "dashboard")
        return super().create(validated_data)


class ScheduleRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleRule
        fields = ["id", "practitioner", "weekday", "start_time", "end_time"]


class ScheduleExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleException
        fields = ["id", "practitioner", "date", "is_closed", "start_time", "end_time", "reason"]


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQEntry
        fields = ["id", "question_patterns", "answer_en", "category"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "direction", "body", "message_type", "interactive", "created_at"]


class EscalationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="conversation.patient.name", read_only=True
    )
    patient_phone = serializers.CharField(
        source="conversation.patient.phone_e164", read_only=True
    )

    class Meta:
        model = EscalationTicket
        fields = [
            "id", "conversation", "patient_name", "patient_phone",
            "reason", "status", "created_at", "resolved_at",
        ]


class RecallRuleSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = RecallRule
        fields = [
            "id", "name", "service", "service_name", "interval_days", "window_days",
            "template_name", "message_override", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_service(self, service):
        # Scope the service to the current clinic (a rule can't target another
        # clinic's service). The view sets clinic on save.
        request = self.context.get("request")
        if request is not None and service.clinic_id != _current_clinic_id():
            raise serializers.ValidationError("Service does not belong to this clinic.")
        return service


def _current_clinic_id():
    from apps.clinics.models import Clinic

    c = Clinic.objects.filter(is_active=True).order_by("id").first()
    return c.id if c else None


class RecallCampaignSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.__str__", read_only=True)
    service_name = serializers.CharField(source="rule.service.name", read_only=True)

    class Meta:
        model = RecallCampaign
        fields = [
            "id", "rule", "rule_name", "service_name", "status",
            "eligible", "sent", "skipped", "failed",
            "projected_cost", "actual_cost", "created_at", "completed_at",
        ]


class ClinicSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = [
            "id", "name", "timezone", "currency", "phone_display", "emergency_phone",
            "address", "maps_link", "languages", "booking_horizon_days",
            "min_notice_minutes", "slot_granularity_minutes", "cancellation_policy",
            "new_patient_form_url", "accepted_insurance",
            "reminders_enabled", "owner_phone_e164", "owner_digest_hour",
            "no_show_recovery_enabled", "recalls_enabled", "marketing_min_interval_days",
            "prompt_variant",
        ]
        read_only_fields = ["id"]

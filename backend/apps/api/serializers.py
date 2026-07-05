from datetime import timedelta

from rest_framework import serializers

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import EscalationTicket, FAQEntry
from apps.messaging.models import Message
from apps.scheduling.models import (
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
            "price_display", "requires_practitioner", "buffer_after_min", "is_active",
        ]


class PractitionerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Practitioner
        fields = ["id", "name", "title", "specialty", "is_active"]


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id", "name", "phone_e164", "preferred_channel", "language_pref",
            "no_show_count", "opted_out_at", "notes", "last_seen_at", "created_at",
        ]


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone_e164", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    practitioner_name = serializers.CharField(
        source="practitioner.name", read_only=True, default=None
    )

    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "patient_name", "patient_phone", "service", "service_name",
            "practitioner", "practitioner_name", "starts_at", "ends_at",
            "status", "source", "notes", "created_at",
        ]
        read_only_fields = ["ends_at", "created_at"]

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
        fields = ["id", "direction", "body", "message_type", "created_at"]


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


class ClinicSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = [
            "id", "name", "timezone", "currency", "phone_display", "emergency_phone",
            "address", "maps_link", "languages", "booking_horizon_days",
            "min_notice_minutes", "slot_granularity_minutes", "cancellation_policy",
            "new_patient_form_url", "accepted_insurance",
        ]
        read_only_fields = ["id"]

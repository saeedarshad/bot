"""Minimal staff dashboard API. Single-tenant for Phase 1: everything is scoped
to the one active clinic. Multi-tenant scoping arrives in Phase 4."""
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clinics.models import Channel, Clinic, Patient
from apps.conversations.inbound import get_conversation, handle_inbound, upsert_patient
from apps.conversations.models import Conversation, EscalationStatus, EscalationTicket, FAQEntry
from apps.messaging.models import Direction, Message
from apps.scheduling.models import (
    Appointment,
    Practitioner,
    ScheduleException,
    ScheduleRule,
    Service,
)

from .serializers import (
    AppointmentSerializer,
    ClinicSettingsSerializer,
    EscalationSerializer,
    FAQSerializer,
    MessageSerializer,
    PatientSerializer,
    PractitionerSerializer,
    ScheduleExceptionSerializer,
    ScheduleRuleSerializer,
    ServiceSerializer,
)


def current_clinic() -> Clinic:
    clinic = Clinic.objects.filter(is_active=True).order_by("id").first()
    if clinic is None:
        raise NotFound("No active clinic configured.")
    return clinic


class ClinicScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(clinic=current_clinic())

    def perform_create(self, serializer):
        serializer.save(clinic=current_clinic())


# --- Auth -------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    return Response({"csrfToken": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(
        request,
        username=request.data.get("username"),
        password=request.data.get("password"),
    )
    if user is None:
        return Response({"detail": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    return Response({"username": user.username})


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    if not request.user.is_authenticated:
        return Response({"detail": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)
    clinic = current_clinic()
    return Response(
        {"username": request.user.username, "clinic": ClinicSettingsSerializer(clinic).data}
    )


# --- Resources --------------------------------------------------------------

class AppointmentViewSet(ClinicScopedViewSet):
    serializer_class = AppointmentSerializer
    queryset = Appointment.objects.select_related(
        "patient", "service", "practitioner"
    ).prefetch_related("scheduled_messages")

    def get_queryset(self):
        qs = super().get_queryset()
        start = self.request.query_params.get("from")
        end = self.request.query_params.get("to")
        if start:
            qs = qs.filter(starts_at__gte=start)
        if end:
            qs = qs.filter(starts_at__lte=end)
        return qs

    def _lifecycle(self, fn, pk):
        result = fn(current_clinic(), int(pk))
        if not result.ok:
            raise NotFound("Appointment not found or not in an active state.")
        appt = Appointment.objects.select_related(
            "patient", "service", "practitioner"
        ).get(pk=result.appointment.pk)
        return Response(AppointmentSerializer(appt).data)

    @action(detail=True, methods=["post"])
    def no_show(self, request, pk=None):
        from apps.scheduling.engine import mark_no_show

        return self._lifecycle(mark_no_show, pk)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        from apps.scheduling.engine import mark_completed

        return self._lifecycle(mark_completed, pk)


class PatientViewSet(ClinicScopedViewSet):
    serializer_class = PatientSerializer
    queryset = Patient.objects.all()
    http_method_names = ["get", "patch", "head", "options"]


class ServiceViewSet(ClinicScopedViewSet):
    serializer_class = ServiceSerializer
    queryset = Service.objects.all()


class PractitionerViewSet(ClinicScopedViewSet):
    serializer_class = PractitionerSerializer
    queryset = Practitioner.objects.all()


class ScheduleRuleViewSet(ClinicScopedViewSet):
    serializer_class = ScheduleRuleSerializer
    queryset = ScheduleRule.objects.all()


class ScheduleExceptionViewSet(ClinicScopedViewSet):
    serializer_class = ScheduleExceptionSerializer
    queryset = ScheduleException.objects.all()


class FAQViewSet(ClinicScopedViewSet):
    serializer_class = FAQSerializer
    queryset = FAQEntry.objects.all()


class EscalationViewSet(ClinicScopedViewSet):
    serializer_class = EscalationSerializer
    queryset = EscalationTicket.objects.select_related("conversation__patient")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.query_params.get("status")
        if state:
            qs = qs.filter(status=state)
        return qs


class ResolveEscalationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        clinic = current_clinic()
        try:
            ticket = EscalationTicket.objects.get(pk=pk, clinic=clinic)
        except EscalationTicket.DoesNotExist:
            raise NotFound("Ticket not found.")
        ticket.status = EscalationStatus.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at"])
        # Resume the bot on that conversation.
        conv = ticket.conversation
        conv.bot_paused = False
        conv.save(update_fields=["bot_paused"])
        return Response(EscalationSerializer(ticket).data)


class ConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        clinic = current_clinic()
        try:
            conv = Conversation.objects.get(pk=pk, clinic=clinic)
        except Conversation.DoesNotExist:
            raise NotFound("Conversation not found.")
        msgs = conv.messages.order_by("created_at")
        return Response(MessageSerializer(msgs, many=True).data)


class PatientMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        clinic = current_clinic()
        try:
            patient = Patient.objects.get(pk=pk, clinic=clinic)
        except Patient.DoesNotExist:
            raise NotFound("Patient not found.")
        from apps.messaging.models import Message

        msgs = Message.objects.filter(conversation__patient=patient).order_by("created_at")
        return Response(MessageSerializer(msgs, many=True).data)


class SettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ClinicSettingsSerializer(current_clinic()).data)

    def patch(self, request):
        clinic = current_clinic()
        serializer = ClinicSettingsSerializer(clinic, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CostSummaryView(APIView):
    """Estimated outbound-messaging spend for the clinic over a date range
    (default: current month). Sums the per-message cost snapshotted on each
    outbound Message, broken down by WhatsApp conversation category."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from decimal import Decimal

        from django.db.models import Count, Sum

        from apps.messaging.models import Direction as MsgDirection
        from apps.messaging.models import Message as Msg

        clinic = current_clinic()
        now = timezone.now()
        start = request.query_params.get("from")
        end = request.query_params.get("to")

        qs = Msg.objects.filter(clinic=clinic, direction=MsgDirection.OUT)
        if start:
            qs = qs.filter(created_at__gte=start)
        else:
            qs = qs.filter(created_at__gte=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        if end:
            qs = qs.filter(created_at__lte=end)

        rows = (
            qs.values("category")
            .annotate(count=Count("id"), amount=Sum("cost_amount"))
            .order_by("category")
        )
        by_category = [
            {
                "category": r["category"],
                "count": r["count"],
                "amount": str(r["amount"] or Decimal("0")),
            }
            for r in rows
        ]
        total = sum((r["amount"] or Decimal("0")) for r in rows)
        failed_count = qs.filter(delivery_status="failed").count()
        return Response(
            {
                "currency": clinic.currency,
                "message_count": sum(r["count"] for r in rows),
                "total": str(total),
                "by_category": by_category,
                "failed_deliveries": failed_count,
            }
        )


class AnalyticsView(APIView):
    """Clinic analytics over a date range (default: current clinic-local month).
    Bookings by source, no-show rate + trend, recovered revenue, waitlist fills,
    bot containment, and median first-response time — all clinic-scoped."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import analytics

        clinic = current_clinic()
        rng = analytics.resolve_range(
            clinic,
            request.query_params.get("from"),
            request.query_params.get("to"),
        )
        return Response(analytics.compute_analytics(clinic, rng))


class MonthlyReportListView(APIView):
    """The clinic's stored monthly reports (newest first), for the "view report"
    action. Each row is a frozen analytics snapshot for one month."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.clinics.models import MonthlyReport

        clinic = current_clinic()
        reports = MonthlyReport.objects.filter(clinic=clinic)[:24]
        return Response(
            [
                {
                    "year": r.year,
                    "month": r.month,
                    "generated_at": r.generated_at,
                    "data": r.data,
                }
                for r in reports
            ]
        )


class DevChatView(APIView):
    """DEV-ONLY message simulator for testing the conversation flow before the
    WhatsApp number is live. Reuses the real inbound pipeline (patient upsert,
    consent/STOP handling, LLM tool loop) but skips the outbound channel send.
    Gated on DEBUG so it can never run in production.

    Each POST makes a live Anthropic call — the frontend must only call this on
    an explicit user action (never poll or loop) to avoid runaway charges."""

    permission_classes = [IsAuthenticated]
    DEMO_PHONE = "+15550000000"

    def _guard(self):
        if not settings.DEBUG:
            raise NotFound()

    def _conversation(self, clinic):
        patient = Patient.objects.filter(clinic=clinic, phone_e164=self.DEMO_PHONE).first()
        if patient is None:
            return None, None
        conv = (
            Conversation.objects.filter(clinic=clinic, patient=patient)
            .order_by("-last_message_at")
            .first()
        )
        return patient, conv

    def get(self, request):
        self._guard()
        clinic = current_clinic()
        _, conv = self._conversation(clinic)
        msgs = conv.messages.order_by("created_at") if conv else []
        return Response(MessageSerializer(msgs, many=True).data)

    def post(self, request):
        self._guard()
        text = (request.data.get("message") or "").strip()
        if not text:
            return Response({"detail": "message required"}, status=status.HTTP_400_BAD_REQUEST)

        clinic = current_clinic()
        channel = Channel.WHATSAPP
        patient = upsert_patient(clinic, self.DEMO_PHONE, channel)
        conversation = get_conversation(clinic, patient, channel)

        Message.objects.create(
            clinic=clinic,
            conversation=conversation,
            channel=channel,
            direction=Direction.IN,
            from_number=self.DEMO_PHONE,
            to_number=clinic.whatsapp_phone_number_id or "dev",
            body=text,
        )
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=["last_message_at"])

        reply = handle_inbound(clinic, patient, conversation, text)
        if reply is not None:
            Message.objects.create(
                clinic=clinic,
                conversation=conversation,
                channel=channel,
                direction=Direction.OUT,
                from_number=clinic.whatsapp_phone_number_id or "dev",
                to_number=self.DEMO_PHONE,
                body=reply.text,
                message_type="interactive" if reply.interactive else "text",
                interactive=reply.interactive,
            )
            conversation.last_message_at = timezone.now()
            conversation.save(update_fields=["last_message_at"])

        return Response(
            {
                "reply": reply.text if reply else None,
                "interactive": reply.interactive if reply else None,
                "silent": reply is None,
            }
        )

    def delete(self, request):
        """Reset the sandbox: remove the demo patient and all their data
        (conversation, messages, appointments) for a clean-slate demo."""
        self._guard()
        clinic = current_clinic()
        Patient.objects.filter(clinic=clinic, phone_e164=self.DEMO_PHONE).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

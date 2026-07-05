"""Minimal staff dashboard API. Single-tenant for Phase 1: everything is scoped
to the one active clinic. Multi-tenant scoping arrives in Phase 4."""
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation, EscalationStatus, EscalationTicket, FAQEntry
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
    queryset = Appointment.objects.select_related("patient", "service", "practitioner")

    def get_queryset(self):
        qs = super().get_queryset()
        start = self.request.query_params.get("from")
        end = self.request.query_params.get("to")
        if start:
            qs = qs.filter(starts_at__gte=start)
        if end:
            qs = qs.filter(starts_at__lte=end)
        return qs


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

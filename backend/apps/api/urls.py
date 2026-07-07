from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("appointments", views.AppointmentViewSet, basename="appointment")
router.register("patients", views.PatientViewSet, basename="patient")
router.register("services", views.ServiceViewSet, basename="service")
router.register("practitioners", views.PractitionerViewSet, basename="practitioner")
router.register("schedule-rules", views.ScheduleRuleViewSet, basename="schedulerule")
router.register("schedule-exceptions", views.ScheduleExceptionViewSet, basename="scheduleexception")
router.register("faqs", views.FAQViewSet, basename="faq")
router.register("escalations", views.EscalationViewSet, basename="escalation")
router.register("recall-rules", views.RecallRuleViewSet, basename="recallrule")

urlpatterns = [
    path("auth/csrf", views.csrf),
    path("auth/login", views.login_view),
    path("auth/logout", views.logout_view),
    path("me", views.me),
    path("settings", views.SettingsView.as_view()),
    path("escalations/<int:pk>/resolve", views.ResolveEscalationView.as_view()),
    path("conversations/<int:pk>/messages", views.ConversationMessagesView.as_view()),
    path("patients/<int:pk>/messages", views.PatientMessagesView.as_view()),
    path("dev/chat", views.DevChatView.as_view()),
    path("costs", views.CostSummaryView.as_view()),
    path("analytics", views.AnalyticsView.as_view()),
    path("reports/monthly", views.MonthlyReportListView.as_view()),
    path("recall-campaigns", views.RecallCampaignListView.as_view()),
    path("quality/export", views.QualityExportView.as_view()),
    path("", include(router.urls)),
]

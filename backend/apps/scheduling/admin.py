from django.contrib import admin

from .models import (
    Appointment,
    Practitioner,
    ScheduleException,
    ScheduleRule,
    Service,
)


@admin.register(Practitioner)
class PractitionerAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "clinic", "is_active")
    list_filter = ("clinic", "is_active")
    search_fields = ("name",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "clinic", "duration_min", "price_display", "is_active")
    list_filter = ("clinic", "is_active")
    search_fields = ("name",)


@admin.register(ScheduleRule)
class ScheduleRuleAdmin(admin.ModelAdmin):
    list_display = ("clinic", "practitioner", "weekday", "start_time", "end_time")
    list_filter = ("clinic", "weekday")


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(admin.ModelAdmin):
    list_display = ("clinic", "practitioner", "date", "is_closed", "reason")
    list_filter = ("clinic", "is_closed")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "starts_at",
        "clinic",
        "patient",
        "service",
        "practitioner",
        "status",
        "source",
    )
    list_filter = ("clinic", "status", "source")
    search_fields = ("patient__name", "patient__phone_e164")
    date_hierarchy = "starts_at"

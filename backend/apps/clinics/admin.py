from django.contrib import admin

from .models import Clinic, Patient


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "timezone", "whatsapp_phone_number_id", "is_active")
    search_fields = ("name", "slug", "whatsapp_phone_number_id")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_e164", "clinic", "no_show_count", "last_seen_at")
    list_filter = ("clinic", "preferred_channel")
    search_fields = ("name", "phone_e164")

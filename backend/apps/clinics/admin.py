from django.contrib import admin

from .models import Clinic


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "timezone", "whatsapp_phone_number_id", "is_active")
    search_fields = ("name", "slug", "whatsapp_phone_number_id")
    prepopulated_fields = {"slug": ("name",)}

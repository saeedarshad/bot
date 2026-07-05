from django.db import models


class Clinic(models.Model):
    """A single tenant. `clinic_id` lives on every domain table from day 1
    so multi-tenancy (later) is a config change, not a rewrite."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    timezone = models.CharField(max_length=64, default="America/New_York")
    currency = models.CharField(max_length=8, default="USD")
    phone_display = models.CharField(max_length=40, blank=True)
    emergency_phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    maps_link = models.URLField(blank=True)
    languages = models.JSONField(default=list)  # e.g. ["en"]

    # WhatsApp Cloud API routing: inbound webhooks are matched by phone_number_id.
    whatsapp_phone_number_id = models.CharField(
        max_length=64, blank=True, db_index=True
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "direction", "from_number", "to_number", "body")
    list_filter = ("channel", "direction")
    search_fields = ("from_number", "to_number", "body", "provider_message_id")
    readonly_fields = [f.name for f in Message._meta.fields]

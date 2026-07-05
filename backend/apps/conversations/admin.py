from django.contrib import admin

from .models import Conversation, EscalationTicket, FAQEntry


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "clinic", "patient", "channel", "status", "bot_paused", "last_message_at")
    list_filter = ("clinic", "status", "bot_paused")


@admin.register(FAQEntry)
class FAQEntryAdmin(admin.ModelAdmin):
    list_display = ("category", "clinic", "answer_en")
    list_filter = ("clinic", "category")
    search_fields = ("question_patterns", "answer_en")


@admin.register(EscalationTicket)
class EscalationTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "clinic", "conversation", "reason", "status", "created_at")
    list_filter = ("clinic", "status")

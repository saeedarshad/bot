from decimal import Decimal

from django.db import migrations

# Representative WhatsApp Cloud API US pricing (per-message estimate). Service
# (in-session) replies are free; business-initiated categories carry a cost.
_DEFAULTS = [
    ("whatsapp", "service", Decimal("0.0000")),
    ("whatsapp", "utility", Decimal("0.0400")),
    ("whatsapp", "marketing", Decimal("0.0625")),
    ("whatsapp", "authentication", Decimal("0.0135")),
]


def seed(apps, schema_editor):
    MessageRate = apps.get_model("messaging", "MessageRate")
    for channel, category, cost in _DEFAULTS:
        MessageRate.objects.get_or_create(
            channel=channel,
            category=category,
            defaults={"unit_cost": cost, "currency": "USD"},
        )


def unseed(apps, schema_editor):
    MessageRate = apps.get_model("messaging", "MessageRate")
    MessageRate.objects.filter(channel="whatsapp").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0007_message_category_message_cost_amount_messagerate"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

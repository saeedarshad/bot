from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"

    def ready(self):
        from django.db.models.signals import post_save

        from apps.scheduling.models import Appointment

        from .reminders import reconcile_appointment_reminders

        def _on_appointment_saved(sender, instance, **kwargs):
            reconcile_appointment_reminders(instance)

        post_save.connect(
            _on_appointment_saved,
            sender=Appointment,
            dispatch_uid="messaging.reconcile_reminders",
        )

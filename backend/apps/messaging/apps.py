from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"

    def ready(self):
        from django.db.models.signals import post_save

        from apps.scheduling.models import Appointment

        from .reminders import attribute_recovered_booking, reconcile_appointment_reminders

        def _on_appointment_saved(sender, instance, created=False, **kwargs):
            reconcile_appointment_reminders(instance)
            # A brand-new booking may be the payoff of a recovery offer — link it
            # to the no-show it recovers (deterministic, at most once).
            if created:
                attribute_recovered_booking(instance)

        post_save.connect(
            _on_appointment_saved,
            sender=Appointment,
            dispatch_uid="messaging.reconcile_reminders",
        )

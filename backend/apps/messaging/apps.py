from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"

    def ready(self):
        from django.db import transaction
        from django.db.models.signals import post_save, pre_save
        from django.utils import timezone

        from apps.scheduling.models import Appointment, AppointmentStatus

        from .reminders import attribute_recovered_booking, reconcile_appointment_reminders

        # Statuses whose *transition into* frees the appointment's slot.
        _FREEING = (AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED)

        def _on_appointment_presave(sender, instance, **kwargs):
            # Stash the persisted status so post_save can detect transitions
            # (post_save alone can't tell a re-save from a real change).
            if instance.pk:
                instance._old_status = (
                    sender.objects.filter(pk=instance.pk)
                    .values_list("status", flat=True)
                    .first()
                )
            else:
                instance._old_status = None

        def _on_appointment_saved(sender, instance, created=False, **kwargs):
            reconcile_appointment_reminders(instance)
            # A brand-new booking may be the payoff of a recovery offer — link it
            # to the no-show it recovers (deterministic, at most once).
            if created:
                attribute_recovered_booking(instance)
            # A slot just freed for the future → offer it to the waitlist. After
            # commit so the worker sees the cancellation (else the live re-check
            # would still count the old booking and match nobody).
            old = getattr(instance, "_old_status", None)
            if (
                instance.status in _FREEING
                and old is not None
                and old not in _FREEING
                and instance.starts_at > timezone.now()
            ):
                from .tasks import offer_waitlist_slot

                transaction.on_commit(
                    lambda appt_id=instance.id: offer_waitlist_slot.delay(appt_id)
                )

        pre_save.connect(
            _on_appointment_presave,
            sender=Appointment,
            dispatch_uid="messaging.stash_old_status",
        )
        post_save.connect(
            _on_appointment_saved,
            sender=Appointment,
            dispatch_uid="messaging.reconcile_reminders",
        )

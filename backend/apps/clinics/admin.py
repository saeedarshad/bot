from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Clinic, Patient, Subscription, UserProfile


class SubscriptionInline(admin.StackedInline):
    """Pay status lives on the clinic page so the operator sets it inline when
    creating a clinic. Billing is off-platform — flip `status` by hand."""

    model = Subscription
    extra = 0
    can_delete = False
    fields = ("plan", "status", "paid_through", "notes")


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "timezone", "whatsapp_phone_number_id",
        "is_active", "subscription_status",
    )
    list_filter = ("is_active", "subscription__status")
    search_fields = ("name", "slug", "whatsapp_phone_number_id")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SubscriptionInline]

    @admin.display(description="Subscription", ordering="subscription__status")
    def subscription_status(self, obj):
        sub = getattr(obj, "subscription", None)
        return sub.status if sub else "—"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """A flat list of every clinic's pay status — flip status inline here."""

    list_display = ("clinic", "plan", "status", "paid_through", "updated_at")
    list_filter = ("status", "plan")
    list_editable = ("status", "paid_through")
    search_fields = ("clinic__name", "clinic__slug")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_e164", "clinic", "no_show_count", "last_seen_at")
    list_filter = ("clinic", "preferred_channel")
    search_fields = ("name", "phone_e164")


# --- Bind staff users to a clinic from the User admin ----------------------

class UserProfileInline(admin.StackedInline):
    """A staff user's clinic (tenant boundary). Set it when creating the clinic's
    first staff login. Leave empty only for the platform operator (superuser)."""

    model = UserProfile
    extra = 0
    fk_name = "user"
    verbose_name = "Clinic membership"
    verbose_name_plural = "Clinic membership"


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = BaseUserAdmin.list_display + ("clinic",)

    @admin.display(description="Clinic")
    def clinic(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.clinic if profile else "—"


User = get_user_model()
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

"""Phase 4 superuser admin surface: the platform operator manages clinics + pay
status through Django admin; ordinary staff cannot reach it."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.clinics.models import Clinic, Subscription, SubscriptionStatus, UserProfile


class AdminSurfaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="operator", password="operator12345"
        )
        self.clinic = Clinic.objects.create(name="Bright Smiles", slug="bright-smiles")
        Subscription.objects.create(
            clinic=self.clinic, status=SubscriptionStatus.ACTIVE
        )
        self.staff = User.objects.create_user(
            username="demo", password="demo12345", is_staff=True
        )
        UserProfile.objects.create(user=self.staff, clinic=self.clinic)
        self.client = Client()

    def _login_operator(self):
        self.assertTrue(self.client.login(username="operator", password="operator12345"))

    def test_operator_can_load_admin_pages(self):
        self._login_operator()
        for url in (
            f"/admin/clinics/clinic/{self.clinic.id}/change/",
            "/admin/clinics/clinic/add/",
            "/admin/clinics/subscription/",
            f"/admin/auth/user/{self.staff.id}/change/",
            "/admin/auth/user/add/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_clinic_change_page_has_subscription_inline(self):
        self._login_operator()
        html = self.client.get(
            f"/admin/clinics/clinic/{self.clinic.id}/change/"
        ).content.decode()
        self.assertIn("Paid through", html)
        self.assertIn("subscription-0-status", html)

    def test_user_change_page_has_clinic_membership_inline(self):
        self._login_operator()
        html = self.client.get(
            f"/admin/auth/user/{self.staff.id}/change/"
        ).content.decode()
        self.assertIn("profile-0-clinic", html)

    def test_operator_can_suspend_clinic_via_subscription_admin(self):
        self._login_operator()
        sub = self.clinic.subscription
        resp = self.client.post(
            f"/admin/clinics/subscription/{sub.id}/change/",
            {
                "clinic": self.clinic.id,
                "plan": sub.plan,
                "status": SubscriptionStatus.SUSPENDED,
                "paid_through": "",
                "notes": "",
            },
        )
        # Redirect back to the changelist on success.
        self.assertIn(resp.status_code, (302, 200))
        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.SUSPENDED)

    def test_ordinary_staff_denied_admin(self):
        self.client.login(username="demo", password="demo12345")
        # A non-superuser with no admin permissions can't view operator models.
        self.assertIn(
            self.client.get("/admin/clinics/subscription/").status_code, (302, 403)
        )

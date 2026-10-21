"""Running without demonstration data, and the platform administrator account."""
import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core import demo
from core.models import HND, Department, Institution, ModelVersion, PastProject, Student, Supervisor, User


def setup(**kw):
    out = StringIO()
    call_command("setup_site", stdout=out, **kw)
    return out.getvalue()


class DemoOff(TestCase):
    def test_fresh_site_without_demo(self):
        with override_settings(DEMO_MODE=False):
            out = setup()
            self.assertIn("No administrator account exists", out)
            self.assertEqual(Institution.objects.count(), 1)
            self.assertEqual(Student.objects.count() + Supervisor.objects.count() + User.objects.count(), 0)
            self.assertTrue(ModelVersion.active())
            r = self.client.get(reverse("landing"))
            self.assertContains(r, "Waiting for records")
            self.assertNotContains(r, "fictional")
            self.assertNotContains(self.client.get(reverse("login")), "demo12345")
            cs = Department.objects.get(name="Computer Science", institution__short_name="YABATECH")
            r = self.client.post(reverse("register"), {
                "role": "student", "department": cs.pk, "full_name": "Real Person",
                "matric_no": "F/HD/24/3210001", "level": HND, "email": "real@example.com",
                "password": "a-long-pass-1"},
                follow=True)
            self.assertRedirects(r, reverse("student_home"))
            setup()  # a restart must not touch real records
            self.assertTrue(Student.objects.filter(pk="F/HD/24/3210001", user__email="real@example.com").exists())

    def test_removing_demo_keeps_real_records(self):
        setup(demo="on")
        cs = Department.objects.get(name="Computer Science", institution__short_name="YABATECH")
        n_students, n_sups = Student.objects.count(), Supervisor.objects.count()
        # a real student claims an imported matric number; a real supervisor and coordinator join
        claimed = Student.objects.filter(department=cs, user__isnull=True, level=HND).first()
        self.client.post(reverse("register"), {
            "role": "student", "department": cs.pk, "full_name": claimed.full_name, "level": HND,
            "matric_no": claimed.pk, "email": "claimed@example.com", "password": "a-long-pass-1"})
        self.client.logout()
        self.client.post(reverse("register"), {
            "role": "supervisor", "department": cs.pk, "full_name": "Dr. Real Lecturer",
            "email": "lecturer@example.com", "password": "a-long-pass-1"})
        self.client.logout()
        User.objects.create_user(username="coord@example.com", email="coord@example.com",
                                 password="a-long-pass-1", role=User.COORDINATOR, department=cs)
        self.client.login(username="coordinator@yabatech.demo", password=demo.PASSWORD)
        self.client.get(reverse("c_overview") + "?level=HND")
        self.client.post(reverse("c_run"), {"threshold": "0.30"})
        self.client.post(reverse("c_report"), {"publish": 1})
        self.client.logout()

        out = setup(demo="off")
        self.assertIn(f"{n_students - 1} students, {n_sups} supervisors", out)
        self.assertEqual(list(Student.objects.values_list("pk", flat=True)), [claimed.pk])
        self.assertEqual(list(Supervisor.objects.values_list("full_name", flat=True)), ["Dr. Real Lecturer"])
        self.assertFalse(PastProject.objects.exists())
        self.assertFalse(User.objects.filter(email__endswith=".demo").exists())
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Institution.objects.count(), 1)
        self.assertGreater(Department.objects.count(), 10)
        self.assertIsNone(ModelVersion.active().top1)
        self.assertFalse(demo.present())
        # the claimed student lost a demo supervisor: flagged, and the department is unpublished
        claimed.refresh_from_db()
        self.assertIsNone(claimed.allocation.supervisor)
        self.assertTrue(claimed.allocation.flagged)
        self.client.login(username="coord@example.com", password="a-long-pass-1")
        for name in ["c_overview", "c_students", "c_supervisors", "c_projects", "c_models", "c_run",
                     "c_flagged", "c_report"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(setup(demo="off").count("Removed"), 0)  # nothing left to remove
        setup(demo="on")  # and the demonstration can be switched back on
        self.assertEqual(Supervisor.objects.count(), n_sups + 1)
        self.assertEqual(Student.objects.count(), n_students)
        self.assertIsNotNone(ModelVersion.active().top1)


class Administrator(TestCase):
    def test_admin_from_environment(self):
        setup(demo="on", no_eval=True)
        self.assertTrue(User.objects.filter(email=demo.DEMO_ADMIN).exists())
        env = {"ADMIN_EMAIL": "Boss@Example.com", "ADMIN_PASSWORD": "first-secret-9"}
        with mock.patch.dict(os.environ, env):
            setup(demo="off", no_eval=True)
        self.assertFalse(User.objects.filter(email=demo.DEMO_ADMIN).exists())
        with mock.patch.dict(os.environ, {**env, "ADMIN_PASSWORD": "second-secret-9"}):
            setup(demo="off", no_eval=True)  # changing the variable changes the password
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        r = self.client.post(reverse("login"), {"username": "boss@example.com", "password": "second-secret-9"},
                             follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/admin/")
        self.assertContains(r, "Institutions, departments and coordinator accounts")
        self.assertNotContains(r, "PairWise")

        # the administrator creates a coordinator with an email address, no username
        cs = Department.objects.get(name="Computer Science", institution__short_name="YABATECH")
        self.assertEqual(self.client.get("/admin/core/user/add/").status_code, 200)
        form = {"email": "New.Coord@Example.com", "first_name": "New", "last_name": "Coord",
                "role": "coordinator", "department": "", "password1": "coord-secret-77",
                "password2": "coord-secret-77", "usable_password": "true"}
        r = self.client.post("/admin/core/user/add/", form)
        self.assertContains(r, "Choose the department this coordinator will run")
        r = self.client.post("/admin/core/user/add/", {**form, "department": cs.pk})
        self.assertEqual(r.status_code, 302, r.content[:600])
        for path in ["/admin/core/user/", "/admin/core/department/", "/admin/core/pastproject/",
                     "/admin/core/institution/add/", "/admin/core/department/add/"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "new.coord@example.com",
                                                "password": "coord-secret-77"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("c_overview"))
        self.assertEqual(self.client.get("/admin/", follow=True).redirect_chain[-1][0].split("?")[0],
                         "/admin/login/")

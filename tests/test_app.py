"""End-to-end test of the portals, database, SBERT scoring module and allocation module.
Run everything with: python manage.py test tests"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import HND, ND, Allocation, Department, FitScore, ModelVersion, PastProject, Student, Supervisor, User

PW = "demo12345"


class FullCycle(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.cs = Department.objects.get(name="Computer Science", institution__short_name="YABATECH")

    def login(self, email):
        self.client.logout()
        self.assertTrue(self.client.login(username=email, password=PW))

    def test_model_baseline_is_recorded(self):
        v = ModelVersion.active()
        self.assertEqual(v.training_round, 0)
        self.assertGreater(v.top3, 0.8)
        self.assertEqual(v.n_eval, PastProject.objects.filter(held_out=True).count())

    def test_semantic_match_without_shared_keywords(self):
        r = self.client.post(reverse("api_match"), json.dumps({"text": "online store for selling shoes"}),
                             content_type="application/json")
        top = r.json()["results"][0]
        self.assertIn("e-commerce", top["specialisation"])
        r = self.client.post(reverse("api_match"), json.dumps({"text": "hi"}), content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_database_integrity_rules(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(matric_no="F/HD/24/9999999", department=self.cs, full_name="X", cgpa=5.5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Supervisor.objects.create(department=self.cs, full_name="X", capacity=0, capacity_nd=0)
        Supervisor.objects.create(department=self.cs, full_name="ND only", capacity=0, capacity_nd=2).delete()
        s = Student.objects.filter(department=self.cs).first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(matric_no=s.matric_no, department=self.cs, full_name="Dup", cgpa=3)

    def test_registration_and_validation(self):
        base = {"role": "student", "department": self.cs.pk, "full_name": "Ada Test",
                "email": "ada@example.com", "password": "a-long-pass-1"}
        r = self.client.post(reverse("register"), {**base, "matric_no": "12345"})
        self.assertContains(r, "does not look like a YABATECH matric number")
        r = self.client.get(reverse("register"))
        self.assertNotContains(r, "Ahmadu Bello")  # only YabaTech departments are offered
        self.assertContains(r, "Computer Science")
        r = self.client.post(reverse("register"), {**base, "matric_no": "f/hd/24/3219999", "level": "ND"})
        self.assertContains(r, "This matric number is an HND number")
        r = self.client.post(reverse("register"), {**base, "matric_no": "f/hd/24/3219999"}, follow=True)
        self.assertRedirects(r, reverse("student_home"))
        st = Student.objects.get(pk="F/HD/24/3219999")
        self.assertEqual(st.level, HND)
        r = self.client.post(reverse("student_home"), {"full_name": "Ada Test", "cgpa": "4.50",
                                                       "interest_text": "a web app for booking halls online"})
        self.assertContains(r, "between 0.00 and 4.00")
        r = self.client.post(reverse("student_home"), {"full_name": "Ada Test", "cgpa": "3.40", "interest_text": "web"})
        self.assertContains(r, "at least a few words")
        self.client.post(reverse("student_home"), {"full_name": "Ada Test", "cgpa": "3.40",
                                                   "interest_text": "a web app for booking halls online"})
        st.refresh_from_db()
        self.assertTrue(st.ready)
        self.assertEqual(self.client.get(reverse("c_overview")).status_code, 302)  # role isolation

    def test_full_allocation_cycle(self):
        self.login("coordinator@yabatech.demo")
        for name in ["c_overview", "c_students", "c_supervisors", "c_projects", "c_models", "c_run",
                     "c_flagged", "c_report", "c_student_add", "c_supervisor_add"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        r = self.client.post(reverse("c_report"), {"publish": 1}, follow=True)
        self.assertContains(r, "Run the allocation before publishing")

        self.client.get(reverse("c_overview") + "?level=HND")
        self.client.post(reverse("c_run"), {"threshold": "0.30"})
        hnd = self.cs.students.filter(level=HND)
        n = hnd.count()
        self.assertEqual(Allocation.objects.filter(student__department=self.cs).count(), n)
        self.assertEqual(FitScore.objects.filter(student__department=self.cs).count(),
                         n * self.cs.supervisors.count())
        for s in self.cs.supervisors.all():
            self.assertLessEqual(s.allocations.count(), s.capacity)
        # nothing leaked into the other department or the ND students
        self.assertFalse(Allocation.objects.exclude(student__department=self.cs).exists())
        self.assertFalse(Allocation.objects.filter(student__level=ND).exists())
        first = Allocation.objects.filter(student__department=self.cs).order_by("priority_position").first()
        self.assertEqual(first.student.cgpa, max(s.cgpa for s in hnd))
        self.assertEqual(first.choice_rank, 1)
        self.assertEqual(self.client.get(reverse("c_student_detail", args=[first.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("c_run")).status_code, 200)
        self.assertEqual(self.client.get(reverse("c_flagged")).status_code, 200)

        open_flags = Allocation.objects.filter(student__department=self.cs, flagged=True, resolved=False)
        self.assertTrue(open_flags.exists())
        r = self.client.post(reverse("c_report"), {"publish": 1}, follow=True)
        self.assertContains(r, "flagged cases before publishing")
        unplaced = open_flags.filter(supervisor__isnull=True).first()
        self.assertIsNotNone(unplaced)  # 48 HND students, 47 HND places
        target = self.cs.supervisors.first()
        r = self.client.post(reverse("c_flagged"), {"matric": unplaced.pk, "supervisor": target.pk, "assign": 1},
                             follow=True)
        self.assertContains(r, "is full")
        self.client.post(reverse("c_supervisor_edit", args=[target.pk]), {
            "full_name": target.full_name, "specialisation_text": target.specialisation_text,
            "capacity": target.capacity + 1, "capacity_nd": target.capacity_nd})
        self.client.post(reverse("c_flagged"), {"matric": unplaced.pk, "supervisor": target.pk, "assign": 1})
        unplaced.refresh_from_db()
        self.assertEqual(unplaced.supervisor_id, target.pk)
        self.assertTrue(unplaced.manual and unplaced.resolved)
        for a in list(open_flags.all()):
            self.client.post(reverse("c_flagged"), {"matric": a.pk, "accept": 1})
        self.assertFalse(open_flags.all().exists())
        # capacity cannot be cut below current load
        r = self.client.post(reverse("c_supervisor_edit", args=[target.pk]), {
            "full_name": target.full_name, "specialisation_text": target.specialisation_text, "capacity": 1,
            "capacity_nd": 3})
        self.assertContains(r, "already allocated")

        r = self.client.post(reverse("c_report"), {"publish": 1}, follow=True)
        self.assertContains(r, "HND allocation published")
        self.assertContains(self.client.get(reverse("c_report")), "No supervisor exceeds capacity")
        csv_text = self.client.get(reverse("c_report_csv")).content.decode()
        self.assertEqual(len(csv_text.strip().splitlines()), n + 1)
        r = self.client.post(reverse("c_run"), {"threshold": "0.30"}, follow=True)
        self.assertContains(r, "Unpublish it before changing records")

        # the ND allocation is a separate cycle: it can still be run and published on its own
        self.client.get(reverse("c_overview") + "?level=ND")
        r = self.client.post(reverse("c_run"), {"threshold": "0.30"}, follow=True)
        self.assertContains(r, "ND allocation complete")
        nd = self.cs.students.filter(level=ND)
        self.assertEqual(Allocation.objects.filter(student__level=ND).count(), nd.count())
        self.assertEqual(Allocation.objects.filter(student__level=HND).count(), n)  # HND result untouched
        for s in self.cs.supervisors.all():
            self.assertLessEqual(s.load(ND), s.capacity_nd)
        nd_flags = Allocation.objects.filter(student__level=ND, flagged=True, resolved=False)
        for a in list(nd_flags.all()):
            self.client.post(reverse("c_flagged"), {"matric": a.pk, "accept": 1})
        r = self.client.post(reverse("c_report"), {"publish": 1}, follow=True)
        self.assertContains(r, "ND allocation published")
        self.assertContains(self.client.get(reverse("c_students")), "ND students")
        csv_nd = self.client.get(reverse("c_report_csv")).content.decode()
        self.assertEqual(len(csv_nd.strip().splitlines()), nd.count() + 1)
        self.assertIn(",ND,", csv_nd)
        self.assertNotIn(",HND,", csv_nd)

        self.login("student@yabatech.demo")
        me = Student.objects.get(user__email="student@yabatech.demo")
        r = self.client.get(reverse("student_home"))
        self.assertContains(r, me.allocation.supervisor.full_name)
        self.assertContains(r, "Why this supervisor")
        self.login("student.nd@yabatech.demo")
        nd_me = Student.objects.get(user__email="student.nd@yabatech.demo")
        self.assertContains(self.client.get(reverse("student_home")), nd_me.allocation.supervisor.full_name)
        self.login("supervisor@yabatech.demo")
        r = self.client.get(reverse("supervisor_home"))
        self.assertContains(r, "HND students allocated to you")
        self.assertContains(r, "ND students allocated to you")
        # another department's coordinator cannot open this department's records
        self.login("coordinator.ee@yabatech.demo")
        self.assertEqual(self.client.get(reverse("c_student_detail", args=[me.pk])).status_code, 404)

    def test_csv_imports(self):
        self.login("coordinator@yabatech.demo")
        data = ("matric_no,full_name,cgpa,interest_text\n"
                "F/HD/24/3217001,New Person,3.10,an app that reminds people to take their drugs\n"
                "F/ND/24/3217003,New ND Person,2.80,a website for a small shop to show its products\n"
                "BADMATRIC,Wrong Format,3.00,something about websites for schools\n"
                "F/HD/24/3217002,Too High,4.70,something about websites for schools\n")
        r = self.client.post(reverse("c_students_import"),
                             {"file": SimpleUploadedFile("s.csv", data.encode(), "text/csv")}, follow=True)
        self.assertContains(r, "Imported 2 student records")
        self.assertContains(r, "2 rows were skipped")
        self.assertEqual(Student.objects.get(pk="F/ND/24/3217003").level, ND)  # level read from the matric
        self.assertEqual(Student.objects.get(pk="F/HD/24/3217001").level, HND)
        sup = self.cs.supervisors.first()
        before = sup.past_projects.count()
        data = ("supervisor_name,title,keywords,abstract,session\n"
                f"{sup.full_name},A brand new online grocery delivery portal,\"web, delivery\",,2024/2025\n"
                "Nobody Here,Some project title that is long enough,,,\n")
        r = self.client.post(reverse("c_projects"),
                             {"file": SimpleUploadedFile("p.csv", data.encode(), "text/csv")}, follow=True)
        self.assertContains(r, "Loaded 1 past project records")
        self.assertEqual(sup.past_projects.count(), before + 1)

    def test_supervisor_self_registration_needs_confirmation(self):
        r = self.client.get(reverse("register") + "?role=supervisor")
        self.assertContains(r, 'id="student-only" hidden')  # no matric number asked of supervisors
        r = self.client.post(reverse("register"), {"role": "supervisor", "department": self.cs.pk,
                                                   "full_name": "Dr. New Staff", "email": "new@example.com",
                                                   "password": "a-long-pass-1"}, follow=True)
        self.assertRedirects(r, reverse("supervisor_home"))
        sup = Supervisor.objects.get(user__email="new@example.com")
        self.assertFalse(sup.ready)
        r = self.client.post(reverse("supervisor_home"), {"p-full_name": "Dr. New Staff", "save_profile": 1,
                                                          "p-specialisation_text": "Game development and graphics",
                                                          "p-capacity": 0, "p-capacity_nd": 0})
        self.assertContains(r, "At least one of the two capacities")
        self.client.post(reverse("supervisor_home"), {"p-full_name": "Dr. New Staff", "save_profile": 1,
                                                      "p-specialisation_text": "Game development and graphics",
                                                      "p-capacity": 3, "p-capacity_nd": 0})
        sup.refresh_from_db()
        self.assertTrue(sup.capacity == 3 and sup.capacity_nd == 0)
        self.login("coordinator@yabatech.demo")
        self.client.post(reverse("c_supervisor_approve", args=[sup.pk]))
        sup.refresh_from_db()
        self.assertTrue(sup.ready)

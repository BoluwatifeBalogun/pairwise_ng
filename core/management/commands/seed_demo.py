"""Load the fictional demonstration data and register the pretrained SBERT model.

    python manage.py seed_demo            # add demo data if the database is empty
    python manage.py seed_demo --reset    # wipe demo tables and reload
"""
import random

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core import services
from core.models import (Allocation, Department, FitScore, Institution, ModelVersion, PastProject, Student,
                         Supervisor, User)
from data import seed_data as sd

PASSWORD = "demo12345"
SESSIONS = ["2021/2022", "2022/2023", "2023/2024", "2024/2025"]


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--no-eval", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            for m in (Allocation, FitScore, PastProject, Student, Supervisor, Department, Institution):
                m.objects.all().delete()
            User.objects.filter(email__endswith=".demo").delete()
        if Institution.objects.exists():
            self.stdout.write("Data already present. Use --reset to reload.")
        else:
            self.load()
        v, created = ModelVersion.objects.get_or_create(
            name="Pretrained SBERT (all-MiniLM-L6-v2)",
            defaults={"training_round": 0, "file_path": settings.PRETRAINED_MODEL,
                      "notes": "No fine-tuning. Baseline for Table 4.7.",
                      "is_active": not ModelVersion.objects.filter(is_active=True).exists()})
        if not opts["no_eval"] and v.top1 is None:
            services.evaluate_version(v)
            self.stdout.write(f"Baseline on held-out records: top1={v.top1:.3f} top3={v.top3:.3f} "
                              f"mrr={v.mrr:.3f} (n={v.n_eval})")
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(username="admin@pairwise.demo", email="admin@pairwise.demo",
                                          password=PASSWORD, role=User.COORDINATOR, first_name="Platform",
                                          last_name="Admin")
        self.stdout.write(self.style.SUCCESS("Demo ready. All demo accounts use the password " + PASSWORD))

    def load(self):
        inst = {}
        for name, short, kind, state, zone, scale in sd.INSTITUTIONS:
            inst[short] = Institution.objects.create(name=name, short_name=short, kind=kind, state=state,
                                                     zone=zone, cgpa_scale=scale)
        for short, dname in sd.EMPTY_DEPARTMENTS:
            Department.objects.create(institution=inst[short], name=dname)
        names = [f"{f} {l}" for f, l in zip(sd.FIRST, sd.LAST)]
        for n, spec in enumerate((sd.CS, sd.EE)):
            rng = random.Random(2026 + n)
            dept = Department.objects.create(
                institution=inst[spec["institution"]], name=spec["name"], session=spec["session"],
                matric_pattern=spec["matric_pattern"], matric_example=spec["matric_example"])
            slug = spec["institution"].lower()
            User.objects.create_user(username=f"coordinator@{slug}.demo", email=f"coordinator@{slug}.demo",
                                     password=PASSWORD, role=User.COORDINATOR, department=dept,
                                     first_name="Project", last_name="Coordinator")
            for k, (full, cap, specialisation, projects) in enumerate(spec["supervisors"]):
                user = None
                if k == 0:
                    user = User.objects.create_user(
                        username=f"supervisor@{slug}.demo", email=f"supervisor@{slug}.demo", password=PASSWORD,
                        role=User.SUPERVISOR, first_name=full.split()[1], last_name=full.split()[-1])
                sup = Supervisor.objects.create(department=dept, user=user, full_name=full, capacity=cap,
                                                specialisation_text=specialisation)
                step = 5 if len(projects) >= 9 else 4
                for i, line in enumerate(projects):
                    title, _, kw = line.partition(" | ")
                    PastProject.objects.create(supervisor=sup, title=title, keywords=kw,
                                               session=SESSIONS[i % len(SESSIONS)], held_out=(i % step == 2))
            order = list(range(len(spec["interests"])))
            rng.shuffle(order)
            lo, hi = spec["cgpa_range"]
            pool = names if n == 0 else [f"{f} {l}" for f, l in zip(sd.FIRST[::-1], sd.LAST[7:] + sd.LAST[:7])]
            for pos, idx in enumerate(order):
                user = None
                if pos == 0:
                    f, l = pool[pos].split()
                    user = User.objects.create_user(
                        username=f"student@{slug}.demo", email=f"student@{slug}.demo", password=PASSWORD,
                        role=User.STUDENT, first_name=f, last_name=l)
                Student.objects.create(matric_no=spec["matric_fmt"].format(pos + 1), user=user, department=dept,
                                       full_name=pool[pos], cgpa=round(rng.uniform(lo, hi), 2),
                                       interest_text=spec["interests"][idx])
        self.stdout.write(f"Loaded {Institution.objects.count()} institutions, {Supervisor.objects.count()} "
                          f"supervisors, {PastProject.objects.count()} past projects, "
                          f"{Student.objects.count()} students.")

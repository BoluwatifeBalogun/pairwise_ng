"""Prepare the site on every start. Safe to run again and again.

    python manage.py setup_site

  * registers the pretrained SBERT model
  * DEMO_MODE=1: loads the fictional demonstration data if none is present
    DEMO_MODE=0: removes the demonstration people, records and accounts, and keeps the
                 institutions and departments so real users can register
  * ADMIN_EMAIL + ADMIN_PASSWORD: creates (or updates) the platform administrator
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core import demo, services
from core.models import Institution, ModelVersion, PastProject, User


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--demo", choices=["on", "off"], help="Override DEMO_MODE for this run")
        parser.add_argument("--no-eval", action="store_true")

    @transaction.atomic
    def handle(self, *args, **o):
        demo_on = settings.DEMO_MODE if o["demo"] is None else o["demo"] == "on"
        v, _ = ModelVersion.objects.get_or_create(
            name="Pretrained SBERT (all-MiniLM-L6-v2)",
            defaults={"training_round": 0, "file_path": settings.PRETRAINED_MODEL,
                      "notes": "No fine-tuning. Baseline for Table 4.7.",
                      "is_active": not ModelVersion.objects.filter(is_active=True).exists()})

        if demo_on:
            if demo.present():
                self.stdout.write("Demonstration data already present.")
            else:
                demo.load_people()
                self.stdout.write("Loaded the demonstration data.")
        else:
            if not Institution.objects.exists():
                demo.load_structure()
                self.stdout.write("Created institutions and departments (no demonstration people).")
            if demo.present():
                c = demo.remove()
                self.stdout.write(f"Removed demonstration data: {c['students']} students, "
                                  f"{c['supervisors']} supervisors, {c['past_projects']} past projects, "
                                  f"{c['accounts']} accounts.")

        # Baseline scores always describe the records that are actually in the database.
        if not PastProject.objects.filter(held_out=True).exists():
            ModelVersion.objects.exclude(top1=None).update(top1=None, top3=None, mrr=None, n_eval=None,
                                                           n_train=None)
        elif not o["no_eval"] and v.top1 is None:
            services.evaluate_version(v)
            if v.top1 is not None:
                self.stdout.write(f"Baseline on held-out records: top1={v.top1:.3f} top3={v.top3:.3f} "
                                  f"mrr={v.mrr:.3f} (n={v.n_eval})")

        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "")
        if email and password:
            admin = User.objects.filter(email=email).first() or User(email=email, first_name="Platform",
                                                                     last_name="Admin")
            admin.username, admin.is_staff, admin.is_superuser, admin.is_active = email, True, True, True
            admin.role = User.COORDINATOR
            admin.set_password(password)
            admin.save()
            if email != demo.DEMO_ADMIN:
                User.objects.filter(email=demo.DEMO_ADMIN).delete()
            self.stdout.write(f"Administrator account ready: {email}")
        elif demo_on:
            if not User.objects.filter(is_superuser=True).exists():
                User.objects.create_superuser(username=demo.DEMO_ADMIN, email=demo.DEMO_ADMIN,
                                              password=demo.PASSWORD, role=User.COORDINATOR,
                                              first_name="Platform", last_name="Admin")
        elif not User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING(
                "No administrator account exists. Set ADMIN_EMAIL and ADMIN_PASSWORD and restart."))

        if demo_on:
            self.stdout.write(self.style.SUCCESS("Demo ready. All demo accounts use the password " + demo.PASSWORD))
        else:
            self.stdout.write(self.style.SUCCESS("Site ready without demonstration data."))

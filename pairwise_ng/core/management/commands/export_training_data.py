"""Write the fine-tuning and evaluation files from the past_projects table.

    python manage.py export_training_data --out training/data

train_pairs.csv   (project text, supervisor text) positive pairs, held-out rows excluded
held_out.csv      held-out project text with its correct supervisor, for evaluation
supervisors.csv   the text of every supervisor
Student names and matric numbers never appear in these files.
"""
import csv
import os

from django.core.management.base import BaseCommand

from core.models import PastProject, Supervisor
from engine.preprocess import clean_text, project_text


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--out", default="training/data")

    def handle(self, *args, **o):
        os.makedirs(o["out"], exist_ok=True)
        sups = [s for s in Supervisor.objects.select_related("department") if s.ready]
        with open(os.path.join(o["out"], "supervisors.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["supervisor_id", "department_id", "specialisation_text"])
            for s in sups:
                w.writerow([s.pk, s.department_id, clean_text(s.specialisation_text)])
        counts = {}
        for held, fname in ((False, "train_pairs.csv"), (True, "held_out.csv")):
            rows = PastProject.objects.filter(held_out=held, supervisor__in=sups).select_related("supervisor")
            with open(os.path.join(o["out"], fname), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["project_text", "supervisor_id", "department_id", "supervisor_text", "session"])
                for p in rows:
                    w.writerow([project_text(p.title, p.keywords, p.abstract), p.supervisor_id,
                                p.supervisor.department_id, clean_text(p.supervisor.specialisation_text),
                                p.session])
            counts[fname] = rows.count()
        self.stdout.write(self.style.SUCCESS(f"Wrote {counts} to {o['out']}"))

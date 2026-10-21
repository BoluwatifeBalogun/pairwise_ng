"""Load the fictional demonstration data (local use).

    python manage.py seed_demo            # same as setup_site (follows DEMO_MODE)
    python manage.py seed_demo --reset    # wipe every record and reload the demo data

On a hosted site use `setup_site`, which follows the DEMO_MODE setting.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from core import demo
from core.models import Allocation, Department, FitScore, Institution, ModelVersion, PastProject, Student, Supervisor


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
            demo._demo_accounts().delete()
            ModelVersion.objects.update(top1=None, top3=None, mrr=None, n_eval=None, n_train=None)
        # Without --reset this follows DEMO_MODE, so a host still starting with the old
        # "seed_demo" command behaves exactly like "setup_site".
        call_command("setup_site", demo="on" if opts["reset"] else None, no_eval=opts["no_eval"],
                     stdout=self.stdout)

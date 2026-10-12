"""Register a fine-tuned SBERT version produced by training/finetune_sbert.py.

    python manage.py register_model sbert-round-1 --round 1 --activate

The folder must sit inside models/. The version is evaluated on the held-out
records with the same code as the pretrained baseline, and the scores are stored.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import services
from core.models import ModelVersion


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--round", type=int, required=True)
        parser.add_argument("--name")
        parser.add_argument("--notes", default="")
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--keep-if-worse", action="store_true",
                            help="Register even if it scores below the current active version")

    def handle(self, *args, **o):
        if not os.path.isdir(os.path.join(settings.MODELS_DIR, o["folder"])):
            raise CommandError(f"models/{o['folder']} does not exist")
        v, _ = ModelVersion.objects.update_or_create(
            name=o["name"] or f"Fine-tuned SBERT, round {o['round']}",
            defaults={"training_round": o["round"], "file_path": o["folder"], "notes": o["notes"]})
        services.evaluate_version(v)
        self.stdout.write(f"{v.name}: top1={v.top1:.3f} top3={v.top3:.3f} mrr={v.mrr:.3f} (n={v.n_eval})")
        current = ModelVersion.active()
        worse = current and current.mrr is not None and v.mrr < current.mrr
        if worse and not o["keep_if_worse"]:
            self.stdout.write(self.style.WARNING(
                "This round scores below the active version on held-out records, so it was "
                "registered but not activated (Section 3.4.2: a round is kept only if it is not worse)."))
            return
        if o["activate"]:
            ModelVersion.objects.update(is_active=False)
            v.is_active = True
            v.save()
            self.stdout.write(self.style.SUCCESS(f"{v.name} is now active."))

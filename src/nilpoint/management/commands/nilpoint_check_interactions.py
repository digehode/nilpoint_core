"""Validate Nilpoint interaction wiring.

A game's assets store the dotted path of the class that implements their
behaviour, so a rename or a move can leave an asset pointing at something that
no longer exists.  This command resolves every configured interaction and
reports the ones that fail, along with what each one offers, so the problem
shows up in development or CI rather than in play.

Usage:
    python manage.py nilpoint_check_interactions
    python manage.py nilpoint_check_interactions --game cypherpunk --actions
"""

from django.apps import apps
from django.core.management.base import BaseCommand

from nilpoint.exceptions import UnresolvableInteraction
from nilpoint.interactions import InteractiveMixin


class Command(BaseCommand):
    help = (
        "Resolves every asset's interaction class and reports any that cannot "
        "be loaded, plus the actions each one offers."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--game",
            type=str,
            help="Only check assets belonging to this game (nilpoint_slug)",
        )
        parser.add_argument(
            "--actions",
            action="store_true",
            help="Also list the actions each interaction class offers",
        )
        parser.add_argument(
            "--include-unused",
            action="store_true",
            help="Also list assets that have no interaction class",
        )

    def handle(self, *args, **options):
        slug = options.get("game")
        show_actions = options.get("actions")
        include_unused = options.get("include_unused")

        interactive_models = [
            model
            for model in apps.get_models()
            if issubclass(model, InteractiveMixin) and not model._meta.abstract
        ]

        if not interactive_models:
            self.stdout.write("No models use InteractiveMixin.")
            return

        failures = []
        checked = 0

        for model in interactive_models:
            queryset = model.objects.order_by("pk")
            if slug:
                queryset = queryset.filter(game__nilpoint_slug=slug)

            configured = queryset.exclude(interaction="")
            unused = queryset.filter(interaction="") if include_unused else None

            self.stdout.write(
                f"\n{model._meta.verbose_name_plural}: {configured.count()} configured"
            )

            # Group by stored path so one class shared by forty assets is
            # resolved once and reported as one line.
            grouped = {}
            for obj in configured:
                grouped.setdefault(obj.interaction, []).append(obj)

            for path, objects in sorted(grouped.items()):
                checked += len(objects)
                asset_ids = ", ".join(sorted(str(o.asset_id) for o in objects))
                try:
                    interaction_class = objects[0].get_interaction_class()
                except UnresolvableInteraction as e:
                    failures.append(path)
                    self.stdout.write(self.style.ERROR(f"  FAIL {path}"))
                    self.stdout.write(self.style.ERROR(f"       {e}"))
                    self.stdout.write(self.style.ERROR(f"       assets: {asset_ids}"))
                    continue

                self.stdout.write(self.style.SUCCESS(f"  ok   {path}"))
                self.stdout.write(f"       {len(objects)} asset(s): {asset_ids}")
                if show_actions:
                    described = interaction_class(objects[0]).describe()
                    for action in described:
                        self.stdout.write(
                            f"         - {action['name']}: {action['label']}"
                            f" -> {action['show'] or '(no partial)'}"
                        )

            if unused is not None:
                for obj in unused:
                    self.stdout.write(f"  --   {obj.asset_id}: no interaction")

        self.stdout.write("")
        if failures:
            self.stdout.write(
                self.style.ERROR(
                    f"{len(failures)} interaction class(es) could not be "
                    f"resolved out of {checked} configured asset(s)."
                )
            )
            self.stdout.write(
                self.style.ERROR(
                    "Renaming or moving an interaction class needs a release "
                    "step that rewrites the affected assets' interaction field."
                )
            )
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(f"All {checked} configured interaction(s) resolved.")
        )

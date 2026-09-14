from django.core.management.base import BaseCommand
from nilpoint.models import Game


class Command(BaseCommand):
    help = (
        "Lists all Nilpoint game instances and their current/latest release versions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pending-only",
            action="store_true",
            help="Filter output to only display games that need an update.",
        )

    def handle(self, *args, **options):
        pending_only = options["pending_only"]
        games = Game.objects.select_subclasses().all()

        if not games.exists():
            self.stdout.write("No Nilpoint games found in database.")
            return

        self.stdout.write(f"{'SLUG':<30} {'NAME':<30} {'RELEASE':<10}")
        self.stdout.write("-" * 72)

        for game in games:
            current_rel = game.release
            latest_rel = (
                game.latest_release()
                if callable(getattr(game, "latest_release", None))
                else current_rel
            )

            needs_update = current_rel < latest_rel

            if pending_only and not needs_update:
                continue

            release_str = f"[{current_rel}/{latest_rel}]"

            # Color code outputs: SUCCESS (green) if updated, WARNING (yellow) if pending
            if needs_update:
                styled_release = self.style.WARNING(f"{release_str} (Update Available)")
            else:
                styled_release = self.style.SUCCESS(f"{release_str}")

            slug_display = getattr(game, "nilpoint_slug", "N/A")
            name_display = getattr(game, "name", str(game))

            self.stdout.write(f"{slug_display:<30} {name_display:<30} {styled_release}")

from django.core.management.base import BaseCommand, CommandError
from nilpoint.models import Game


class Command(BaseCommand):
    help = "Updates Nilpoint game instances to their latest subclass release version."

    def add_arguments(self, parser):
        # Optional: Allow updating a specific game by slug
        parser.add_argument(
            "--slug",
            type=str,
            help="Slug of a specific Game instance to update. Updates all if omitted.",
            choices=list(Game.objects.values_list("nilpoint_slug", flat=True)),
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="If set, continue updating until the latest release is reached",
        )

    def handle(self, *args, **options):
        slug = options.get("slug")
        full = options.get("full")
        if slug:
            games = Game.objects.filter(nilpoint_slug=slug)
            if not games.exists():
                raise CommandError(f"Game with slug '{slug}' not found.")
        else:
            games = Game.objects.all()

        games = games.select_subclasses()
        for game in games:
            # Cast or access your specific game instance/subclass logic
            if game.release < game.latest_release():
                while game.release < game.latest_release():
                    rel_from = game.release
                    rel_to = rel_from + 1
                    self.stdout.write(
                        f"Updating '{game.name} ({game.nilpoint_slug})' from v{rel_from} -> v{rel_to}..."
                    )
                    game.update_release()

                    if not full:
                        break
                self.stdout.write(
                    self.style.SUCCESS(f"Successfully updated '{game.nilpoint_slug}'.")
                )
            else:
                self.stdout.write(
                    f"'{game}' is already at (or over) latest release (v{game.release})."
                )

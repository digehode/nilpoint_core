"""
Configuration management for Nilpoint

This module resolves application-level settings defined in the host Django project's
`settings.py` in a `NILPOINT_SETTINGS` dictionary. It manages model archetype
overrides (allowing individual games to replace core models like `PlayerCharacter`
with custom subclasses) and dynamic game model discovery.

Usage Example (in host settings.py):
    NILPOINT_SETTINGS = {
        # Maps game model slugs/names to their subclass model overrides
        "archetypes": {
            "cypherpunkgame": {
                "PlayerCharacter": "cypherpunk.CypherpunkPC",
            }
        },
        # Registered game model ContentType model names
        "games": ["cypherpunkgame"],
    }

Classes:
    AppSettings:
        Wrapper providing runtime resolution of archetype mapping and registered
        game classes against project defaults. Use the pre-instantiated object rather than this class.

Instances:
    nilpoint_settings:
        Pre-instantiated singleton object for importing directly into views,
        models, or management commands.
"""

from django.conf import settings
from django.contrib.contenttypes.models import ContentType


DEFAULTS = {
    "archetypes": {
        "PlayerCharacter": "nilpoint.PlayerCharacter",
    },
}


class AppSettings:
    def __init__(self):
        # Get user's overrides from the global settings.py
        self.user_settings = getattr(settings, "NILPOINT_SETTINGS", {})

    def get_archetype(self, game, model):
        """Get the preferred archetype for a model for the given game.

        Each game can subclass key Nilpoint models, such as the
        PlayerCharacter. Using this method, nilpoint can work with
        these subclasses without having to do complicated casting
        """
        if "archetypes" in self.user_settings:
            if game in self.user_settings["archetypes"]:
                if model in self.user_settings["archetypes"][game]:
                    return self.user_settings["archetypes"][game][model]
        return DEFAULTS["archetypes"][model]

    def games(self):
        """Returns a list of configured game models"""
        game_models = []
        for game_class in self.user_settings["games"]:
            content_type = ContentType.objects.get(model=game_class)
            model = content_type.model_class()
            game_models.append(model)
        return game_models


# Instantiate so it can be imported elsewhere
nilpoint_settings = AppSettings()

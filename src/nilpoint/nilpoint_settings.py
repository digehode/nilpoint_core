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

    # def __getattr__(self, attr):
    #     if attr not in DEFAULTS:
    #         raise AttributeError(f"Invalid setting: '{attr}'")

    #     try:
    #         return self.user_settings[attr]
    #     except KeyError:
    #         return DEFAULTS[attr]

    # def get(self, setting):
    #     """Uses getattr but with a nicer name"""
    #     return self.__getattr__(setting)

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

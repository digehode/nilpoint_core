from django.conf import settings


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
        if "archetypes" in self.user_settings:
            if game in self.user_settings["archetypes"]:
                if model in self.user_settings["archetypes"][game]:
                    return self.user_settings["archetypes"][game][model]
        return DEFAULTS["archetypes"][model]


# Instantiate so it can be imported elsewhere
nilpoint_settings = AppSettings()

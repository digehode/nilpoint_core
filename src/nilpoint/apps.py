from django.apps import AppConfig


class NilpointConfig(AppConfig):
    name = "nilpoint"

    def ready(self):
        # from django.conf import settings
        print("Nilpoint initialising")
        pass

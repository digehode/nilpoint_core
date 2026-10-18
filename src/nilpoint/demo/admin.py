"""Admin registration for the demo game's models.

Only the game and the player character are subclassed here, so only
these need registering - the core nilpoint admins already cover the
locations, exits and items the release steps create.  The admin is the
only way to make a playable instance: create a `DemoGame` here, then
run `manage.py nilpoint_update_game --slug <slug> --full` to build its
world (creating the instance alone doesn't run the release steps).
"""

from django.contrib import admin

from .models import DemoGame, DemoPC


@admin.register(DemoGame)
class DemoGameAdmin(admin.ModelAdmin):
    model = DemoGame
    prepopulated_fields = {"nilpoint_slug": ("instance_name",)}


@admin.register(DemoPC)
class DemoPCAdmin(admin.ModelAdmin):
    model = DemoPC
    list_display = ["handle", "player", "game", "tagline", "release"]

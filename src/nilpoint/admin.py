from django.contrib import admin

from .models import (
    Player,
    PlayerCharacter,
    Game,
    Location,
    Exit,
    Item,
    InventoryItem,
    LocationItem,
)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    model = Player


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    model = Game
    list_display = [
        "instance_name",
        "_game_type",
        "instance_description",
        "nilpoint_slug",
        "get_dispatch_url",
        "allow_multiple_characters",
    ]


@admin.register(PlayerCharacter)
class PlayerCharacterAdmin(admin.ModelAdmin):
    model = PlayerCharacter
    list_display = ["handle", "player", "game"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    model = Location
    list_display = ["name", "description", "game", "graphic", "initial"]


@admin.register(Exit)
class ExitAdmin(admin.ModelAdmin):
    model = Exit
    list_display = ["name", "exit_from", "exit_to"]


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    model = Item


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    model = InventoryItem


@admin.register(LocationItem)
class LocationItemAdmin(admin.ModelAdmin):
    model = LocationItem

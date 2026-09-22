import json
import pickle

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Player,
    PlayerCharacter,
    Game,
    Location,
    Exit,
    Item,
    InventoryItem,
    LocationItem,
    ItemState,
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
    list_display = ["name", "description", "game", "graphic", "initial", "asset_id"]


@admin.register(Exit)
class ExitAdmin(admin.ModelAdmin):
    model = Exit
    list_display = ["name", "exit_from", "exit_to", "asset_id"]


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    model = Item
    list_display = ["name", "asset_id", "graphic"]


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    model = InventoryItem
    list_display = ["item", "pc", "state_preview"]
    readonly_fields = ["state_display"]

    @admin.display(description="State")
    def state_preview(self, obj):
        """Show a preview of the state in list view."""
        data = obj.item_state._data
        if not data:
            return "—"
        preview = ", ".join(f"{k}={v}" for k, v in list(data.items())[:3])
        if len(data) > 3:
            preview += " …"
        return preview

    @admin.display(description="Item State")
    def state_display(self, obj):
        """Show full state in detail view as formatted JSON."""
        data = obj.item_state._data
        if not data:
            return "No state data"
        try:
            formatted = json.dumps(data, indent=2, default=str)
            return format_html("<pre>{}</pre>", formatted)
        except Exception:
            return format_html("<pre>{}</pre>", str(obj.item_state._data))


@admin.register(LocationItem)
class LocationItemAdmin(admin.ModelAdmin):
    model = LocationItem
    list_display = ["item", "location", "pc", "state_preview"]
    readonly_fields = ["state_display"]

    @admin.display(description="State")
    def state_preview(self, obj):
        """Show a preview of the state in list view."""
        data = obj.item_state._data
        if not data:
            return "—"
        preview = ", ".join(f"{k}={v}" for k, v in list(data.items())[:3])
        if len(data) > 3:
            preview += " …"
        return preview

    @admin.display(description="Item State")
    def state_display(self, obj):
        """Show full state in detail view as formatted JSON."""
        data = obj.item_state._data
        if not data:
            return "No state data"
        try:
            formatted = json.dumps(data, indent=2, default=str)
            return format_html("<pre>{}</pre>", formatted)
        except Exception:
            return format_html("<pre>{}</pre>", str(obj.item_state._data))


@admin.register(ItemState)
class ItemStateAdmin(admin.ModelAdmin):
    model = ItemState
    list_display = ["content_type", "object_id", "content_object_link", "state_preview"]
    readonly_fields = ["content_type", "object_id", "state_display"]
    list_filter = ["content_type"]
    search_fields = ["object_id"]

    @admin.display(description="Related Object")
    def content_object_link(self, obj):
        """Link to the related object in admin."""
        if obj.content_object:
            ct = obj.content_type
            admin_url = f"/admin/nilpoint/{ct.model}/{obj.object_id}/change/"
            return format_html('<a href="{}">{}</a>', admin_url, obj.content_object)
        return "—"

    @admin.display(description="State")
    def state_preview(self, obj):
        """Show a preview of the state in list view."""
        if not obj.data:
            return "—"
        try:
            data = pickle.loads(obj.data) if obj.data else {}
        except Exception:
            return "Error unpickling"
        if not data:
            return "—"
        preview = ", ".join(f"{k}={v}" for k, v in list(data.items())[:3])
        if len(data) > 3:
            preview += " …"
        return preview

    @admin.display(description="State Data")
    def state_display(self, obj):
        """Show full state in detail view as formatted JSON."""
        if not obj.data:
            return "No state data"
        try:
            data = pickle.loads(obj.data) if obj.data else {}
            formatted = json.dumps(data, indent=2, default=str)
            return format_html("<pre>{}</pre>", formatted)
        except Exception:
            return format_html("<pre>Error displaying state: {}</pre>", str(obj.data))

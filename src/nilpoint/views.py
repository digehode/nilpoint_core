from django.views.generic import View
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect
from .models import (
    Game,
    Player,
    PlayerCharacter,
    Exit,
    LocationItem,
    InventoryItem,
    transfer_item_state,
)
from django.http import HttpResponse
from .exceptions import NilpointMissingSlugException
from .forms import NewPlayerCharacterForm
from functools import wraps
import json
from .models import get_model
from django.template.loader import render_to_string
from .decorators import require_http_methods


# TODO: Allow Exit objects to be subclassed - use same settings as other subclassed things


class HtmxTriggerResponse(HttpResponse):
    """An HTTP Response that automatically attaches an HTMX trigger header."""

    def __init__(self, trigger_name=None, trigger_data=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.htmx_triggers = {}
        if trigger_name:
            self.htmx_triggers[trigger_name] = (
                trigger_data if trigger_data is not None else None
            )

    def add_trigger(self, trigger_name, trigger_data=None):
        """Dynamically add or update a trigger anytime before the response sends."""
        self.htmx_triggers[trigger_name] = trigger_data

    def serialize_htmx_headers(self):
        if self.htmx_triggers:
            triggers_serial = json.dumps(self.htmx_triggers)
            self["HX-Trigger"] = triggers_serial

    def from_template_response(response):

        # Force the template to render so we can extract the HTML string
        response.render()

        # Pass the rendered content and headers into your custom class
        custom_response = HtmxTriggerResponse(
            content=response.content,
            status=response.status_code,
            content_type=response["Content-Type"],
        )

        return custom_response


class NilpointAdminPanel(UserPassesTestMixin, View):
    """Admin panel for site admin"""

    def test_func(self):
        """Ensure only authenticated staff users / site admins can access."""
        return self.request.user.is_authenticated and self.request.user.is_staff

    def get(self, request, *args, **kwargs):
        """Renders the admin panel"""
        context = {}
        partial = "nilpoint/admin/admin_panel.jinja2#nilpoint_admin_panel"
        content = render_to_string(partial, request=request, context=context)
        response = HtmxTriggerResponse(content=content)
        return response


class NilpointGameBasic(View):
    """Super class for game views."""

    _handlers = {
        # TODO: Think about the naming scheme here
        "debug": "debug",
        "overview": "handle_overview",
        "landing": "handle_landing",
        "new_player_character": "handle_new_player_character",
        "select_player_character": "handle_select_player_character",
        "player_selection_panel": "handle_player_selection_panel",
        "get_location_graphic": "handle_get_location_graphic",
        "get_player_location_panel": "handle_get_player_location_panel",
        "use_exit": "handle_use_exit",
        "get_location_item_panel": "handle_get_location_item_panel",
        "get_inventory_panel": "handle_get_inventory_panel",
        "item_detail": "handle_item_detail",
        "take_item": "handle_take_item",
        "drop_item": "handle_drop_item",
        "interact": "handle_interact",
    }

    @classmethod
    def get_valid_actions(cls):
        """Return set of valid action names for this view class."""
        actions = set(cls._handlers.keys())
        if hasattr(cls, "handlers"):
            actions.update(cls.handlers.keys())
        return actions

    def __init__(self, *args, **kwargs):
        """Combine subclass handlers with the _handlers dict"""
        if hasattr(self, "handlers"):
            self._handlers.update(self.handlers)
        self.game = None
        self.player = None
        self.player_characters = []
        self.player_character = None
        super().__init__(*args, **kwargs)

    def get_player_characters(self, request, *args, **kwargs):
        if self.game is not None and request.user and not request.user.is_anonymous:
            return self.game.get_player_characters(request.user, self.game)
        return None

    def _get_game_object(self, request, *args, **kwargs):
        """Return the generic game object associated with this request.

        By default, it looks for the nilpoint_slug in the request path.

        Games/platforms that don't use this system will need to
        provide a different implementation of this method in their
        views.

        Will allow the Game.DoesNotExist exception to bubble up and
        should be caught from wherever this is called.

        Raises nilpoint.MissingSlugException if the slug doesn't identify a game instance

        """

        if "nilpoint_slug" in kwargs:
            return Game.objects.get(nilpoint_slug=kwargs["nilpoint_slug"])
        else:
            raise NilpointMissingSlugException("No nilpoint_slug was given in kwargs")

    def get_context_data(self, request, *args, **kwargs):
        context = {}

        context["game"] = self.game
        context["player_characters"] = self.player_characters
        context["player_character"] = self.player_character

        return context

    def nilpoint_render(self, request, template, context={}, *args, **kwargs):
        full_context = {}

        full_context.update(self.get_context_data(request, *args, **kwargs))
        full_context.update(context)

        content = render_to_string(template, request=request, context=full_context)
        response = HtmxTriggerResponse(content=content)
        if "trigger" in kwargs:
            response.add_trigger(kwargs["trigger"])
            # response["HX-Trigger"] = kwargs["trigger"]
        return response

    def _request_wrapper(func):

        @wraps(func)
        def _get_post_common(self, request, *args, **kwargs):
            """Do all of the things that need to be done regardless of method

            Before the handling:
            1. Set the self.game object.
            2. Set the self.player object, or None if it doesn't exist
            3. Set self.player_characters to a list of player characters for this user, for this game
            3. set self.action
            4. If an early response is required (errors, for eg), return it
            5. Check if the current player character has a location.
               Set it to the starting location for the game if not.

            After the handling:
            1. Set/clear cookies, etc.
            """

            response = None

            if (
                request.user.is_authenticated
                and Player.objects.filter(user=request.user).exists()
            ):
                # Use the reverse relationship from player to user
                self.player = request.user.player
            else:
                self.player = None

            try:
                self.game = self._get_game_object(request, *args, **kwargs)
            except Game.DoesNotExist:
                self.game = None
            except NilpointMissingSlugException:
                self.game = None

            # Now if there is both a game and a player, retrieve the
            # list of player characters for that player and game
            if self.player is not None and self.game is not None:
                self.player_characters = self.get_player_characters(
                    request, *args, **kwargs
                )

            # The pc cookie is used to track which player character is
            # active for the player.

            # Check if the pc cookie is set and if it matches the game
            # and player
            pc_id = request.COOKIES.get("pc", None)
            if pc_id is not None:
                try:
                    pc = PlayerCharacter.objects.get_subclass(id=pc_id)
                    if pc.game != self.game or pc.player != self.player:
                        self.player_character = None
                    else:
                        self.player_character = pc
                except PlayerCharacter.DoesNotExist:
                    self.player_character = None

            # Now all the player and game setup is done, we store the
            # details about the current request itself

            self.action = request.GET.get("action", None)
            if self.action is None:
                response = HtmxTriggerResponse(
                    content="Action required", content_type="text/plain"
                )
            elif self.action not in self._handlers:
                response = HtmxTriggerResponse(
                    content=f"Unknown action '{self.action}'", content_type="text/plain"
                )

            # Now to the specific GET/POST handler.  If the response
            # is already set, it's because something happened in
            # checking state that overrides general handling
            if response is None:
                response = func(self, request, *args, **kwargs)

            # Any changes post handling

            # If the player character has been unset, remove the cookie
            if self.player_character is None:
                response.delete_cookie("pc")

            ##Deal with location
            if self.player_character:
                # If there is no location set (new character), get the initial location from the game
                if self.player_character.current_location is None:
                    self.player_character.current_location = (
                        self.game.get_initial_location()
                    )
                    self.player_character.save()
                    response.add_trigger("player_location_changed")

            response.serialize_htmx_headers()
            return response

        return _get_post_common

    @require_http_methods("POST")
    def handle_select_player_character(self, request, *args, **kwargs):
        selected_pc = request.POST.get("player_character", None)
        if selected_pc == "-1":
            self.player_character = None
            response = HtmxTriggerResponse(
                content="Cleared selected player character",
                content_type="text/plain",
            )
            response.add_trigger(trigger_name="player_character_changed")
            return response

        else:
            try:
                pc = PlayerCharacter.objects.get_subclass(id=selected_pc)

            except PlayerCharacter.DoesNotExist:
                response = HtmxTriggerResponse(
                    content=f"Couldn't find selected player character '{selected_pc}'",
                    content_type="text/plain",
                )
                response.add_trigger("player_location_changed")
                return response

        if pc.player == self.player and pc.game == self.game:
            self.player_character = pc
            response = HtmxTriggerResponse(
                content=f"Successfully selected pc {pc.handle}, id {pc.id}.",
                content_type="text/plain",
            )
            response.add_trigger(trigger_name="player_character_changed")
            response.set_cookie("pc", pc.id)

            return response
        else:
            self.player_character = None
            response = HtmxTriggerResponse(
                content="Couldn't match selected pc", content_type="text/plain"
            )
            response.add_trigger("player_location_changed")
            return response

    @_request_wrapper
    def get(self, request, *args, **kwargs):
        """GET dispatcher

        Uses the content of self.handlers to redirect requests to appropriate methods.
        """
        response = getattr(self, self._handlers[self.action])(request, *args, **kwargs)
        return response

    @_request_wrapper
    def post(self, request, *args, **kwargs):
        """GET dispatcher

        Uses the content of self.handlers to redirect requests to appropriate methods.
        """
        response = getattr(self, self._handlers[self.action])(request, *args, **kwargs)
        return response

    def _value_from_subclass_or_default(self, name, default):
        """Templates used in basic methods can be overridden by
        subclasses simply by adding class variables in the subclass.

        This method checks if 'name' exists and returns it if it does,
        else returns the default. It is used by the methods that check
        for overridden templates from subclasses.

        """

        if hasattr(self, name):
            return getattr(self, name)
        else:
            return default

    @require_http_methods("GET")
    def handle_overview(self, request, *args, **kwargs):
        """Page overview

        Override the 'partial' used to render the content.
        """

        partial = self._value_from_subclass_or_default(
            "overview_partial", "nilpoint/game_overview.jinja2#game_overview"
        )

        return self.nilpoint_render(request, partial, context={}, *args, **kwargs)

    @require_http_methods("GET")
    def handle_player_selection_panel(self, request, *args, **kwargs):
        """Player character selection panel

        Override player_selection_panel_partial used to render the content.
        """

        partial = self._value_from_subclass_or_default(
            "player_selection_panel_partial",
            "nilpoint/player_selection.jinja2#player_selection",
        )

        return self.nilpoint_render(request, partial, context={}, *args, **kwargs)

    @require_http_methods("GET")
    def handle_get_location_graphic(self, request, *args, **kwargs):
        """Return the content of the graphic display area

        - Override location_graphic_partial used to render the content.

        """
        context = {}
        partial = self._value_from_subclass_or_default(
            "location_graphic_partial",
            "nilpoint/location_panel.jinja2#location_graphic",
        )
        if (
            self.player_character is None
            or self.player_character.current_location is None
        ):
            if (
                self.game.default_location_graphic is None
                or self.game.default_location_graphic.strip() == ""
            ):
                default_location_graphic = "nilpoint/locations/00_none/simple.png"
            else:
                default_location_graphic = self.game.default_location_graphic
            context = {"location_graphic_override": default_location_graphic}

        return self.nilpoint_render(request, partial, context, *args, **kwargs)

    @require_http_methods("GET")
    def handle_get_player_location_panel(self, request, *args, **kwargs):
        """Return the content of the location control panel

        - Override player_location_panel used to render the content for custom responses

        """
        context = {}
        partial = self._value_from_subclass_or_default(
            "player_location_panel",
            "nilpoint/player_location_panel.jinja2#player_location_panel",
        )

        return self.nilpoint_render(request, partial, context, *args, **kwargs)

    @require_http_methods("GET")
    def handle_get_location_item_panel(self, request, *args, **kwargs):
        """Return the list of items at the current location"""
        context = {}
        partial = self._value_from_subclass_or_default(
            "location_item_panel",
            "nilpoint/location_item_panel.jinja2#location_item_panel",
        )

        return self.nilpoint_render(request, partial, context, *args, **kwargs)

    @require_http_methods("GET")
    def handle_get_inventory_panel(self, request, *args, **kwargs):
        """Return the list of items in the player's inventory."""
        context = {}
        partial = self._value_from_subclass_or_default(
            "inventory_panel",
            "nilpoint/inventory_item_panel.jinja2#inventory_panel",
        )
        return self.nilpoint_render(request, partial, context, *args, **kwargs)

    @require_http_methods("POST")
    def handle_take_item(self, request, *args, **kwargs):
        """Take a LocationItem into the player's inventory.

        The LocationItem ID should be given as 'location_item' in the POST request.
        Checks:
        - The LocationItem belongs to the current player character
        - The LocationItem is at the player's current location
        - The Item has can_take=True
        If valid, creates an InventoryItem for the player and deletes the LocationItem.
        """
        location_item_id = request.POST.get("location_item", None)
        if location_item_id is None:
            return HtmxTriggerResponse(
                content="No location_item given in POST parameters",
                content_type="text/plain",
            )
        try:
            location_item_id = int(location_item_id)
        except (TypeError, ValueError):
            return HtmxTriggerResponse(
                content="Invalid location_item id", content_type="text/plain"
            )

        pc = self.player_character
        if pc is None:
            return HtmxTriggerResponse(
                content="No player character selected",
                content_type="text/plain",
            )

        location_item = LocationItem.objects.filter(id=location_item_id, pc=pc).first()
        if location_item is None:
            return HtmxTriggerResponse(
                content="Location item not found or not yours",
                content_type="text/plain",
            )

        # Check the location matches player's current location
        if location_item.location != pc.current_location:
            return HtmxTriggerResponse(
                content="Item is not at your current location",
                content_type="text/plain",
            )

        # Check the item belongs to the current game
        if location_item.item.game != self.game:
            return HtmxTriggerResponse(
                content="Item is not part of this game",
                content_type="text/plain",
            )

        # Check can_take on the item
        if not location_item.item.can_take:
            return HtmxTriggerResponse(
                content="This item cannot be taken",
                content_type="text/plain",
            )

        # Create inventory item and delete location item
        inventory_item = InventoryItem.objects.create(pc=pc, item=location_item.item)
        transfer_item_state(location_item, inventory_item)
        location_item.delete()

        response = HtmxTriggerResponse(
            content=f"Took {location_item.item.name}",
            content_type="text/plain",
        )
        response.add_trigger("player_location_changed")
        return response

    @require_http_methods("POST")
    def handle_drop_item(self, request, *args, **kwargs):
        """Drop an InventoryItem at the player's current location.

        The InventoryItem ID should be given as 'inventory_item' in the POST request.
        Checks:
        - The InventoryItem belongs to the current player character
        - The Item has can_drop=True
        - The player has a current location
        If valid, creates a LocationItem at the current location and deletes the InventoryItem.
        """
        inventory_item_id = request.POST.get("inventory_item", None)
        if inventory_item_id is None:
            return HtmxTriggerResponse(
                content="No inventory_item given in POST parameters",
                content_type="text/plain",
            )
        try:
            inventory_item_id = int(inventory_item_id)
        except (TypeError, ValueError):
            return HtmxTriggerResponse(
                content="Invalid inventory_item id", content_type="text/plain"
            )

        pc = self.player_character
        if pc is None:
            return HtmxTriggerResponse(
                content="No player character selected",
                content_type="text/plain",
            )

        if pc.current_location is None:
            return HtmxTriggerResponse(
                content="You are not at a location",
                content_type="text/plain",
            )

        inventory_item = InventoryItem.objects.filter(
            id=inventory_item_id, pc=pc
        ).first()
        if inventory_item is None:
            return HtmxTriggerResponse(
                content="Inventory item not found or not yours",
                content_type="text/plain",
            )

        # Check the item belongs to the current game
        if inventory_item.item.game != self.game:
            return HtmxTriggerResponse(
                content="Item is not part of this game",
                content_type="text/plain",
            )

        # Check can_drop on the item
        if not inventory_item.item.can_drop:
            return HtmxTriggerResponse(
                content="This item cannot be dropped",
                content_type="text/plain",
            )

        # Create location item and delete inventory item
        location_item = LocationItem.objects.create(
            location=pc.current_location, pc=pc, item=inventory_item.item
        )
        transfer_item_state(inventory_item, location_item)
        inventory_item.delete()

        response = HtmxTriggerResponse(
            content=f"Dropped {inventory_item.item.name}",
            content_type="text/plain",
        )
        response.add_trigger("player_location_changed")
        return response

    @require_http_methods("GET", "POST")
    def handle_interact(self, request, *args, **kwargs):
        """Handle item interactions (show/handle/can phases).

        POST with:
            - item_type: "location_item" or "inventory_item"
            - object_id: ID of the LocationItem or InventoryItem
            - action: The action name (e.g., "squeeze")
            - phase: "show", "handle", or "can"

        For "show" phase: Returns a partial template for HTMX inclusion.
        For "handle" phase: Executes the action and returns response.
        For "can" phase: Returns JSON {"allowed": true/false, "reason": "..."}.

        get_item_hooks(item) provides the hook method names.
        """
        item_type = request.POST.get("item_type", None)
        object_id = request.POST.get("object_id", None)
        action = request.POST.get("action", None)
        phase = request.POST.get("phase", None)

        if not all([item_type, object_id, action, phase]):
            return HtmxTriggerResponse(
                content="Missing required parameters: item_type, object_id, action, phase",
                content_type="text/plain",
            )

        try:
            object_id = int(object_id)
        except (TypeError, ValueError):
            return HtmxTriggerResponse(
                content="Invalid object_id", content_type="text/plain"
            )

        if phase not in ("show", "handle", "can"):
            return HtmxTriggerResponse(
                content=f"Invalid phase '{phase}'. Must be 'show', 'handle', or 'can'",
                content_type="text/plain",
            )

        pc = self.player_character
        if pc is None:
            return HtmxTriggerResponse(
                content="No player character selected",
                content_type="text/plain",
            )

        # Get the instance (LocationItem or InventoryItem)
        if item_type == "location_item":
            InstanceModel = LocationItem
        elif item_type == "inventory_item":
            InstanceModel = InventoryItem
        else:
            return HtmxTriggerResponse(
                content=f"Invalid item_type '{item_type}'. Must be 'location_item' or 'inventory_item'",
                content_type="text/plain",
            )

        instance = InstanceModel.objects.filter(id=object_id, pc=pc).first()
        if instance is None:
            return HtmxTriggerResponse(
                content="Instance not found or not yours",
                content_type="text/plain",
            )

        # Check the item belongs to the current game
        if instance.item.game != self.game:
            return HtmxTriggerResponse(
                content="Item is not part of this game",
                content_type="text/plain",
            )

        # Get hooks from game
        real_game = self.game.get_real_instance()
        hooks = real_game.get_item_hooks(instance.item)

        # Check if action exists for this phase
        phase_hooks = hooks.get(phase, {})
        hook_entry = phase_hooks.get(action)
        if not hook_entry:
            return HtmxTriggerResponse(
                content=f"No {phase} hook for action '{action}' on this item",
                content_type="text/plain",
            )

        # Extract method name: show hooks are dicts with "method", others are strings
        if phase == "show" and isinstance(hook_entry, dict):
            hook_method_name = hook_entry.get("method")
        elif isinstance(hook_entry, str):
            hook_method_name = hook_entry
        else:
            # Backward compat for any other dict format
            hook_method_name = (
                hook_entry.get("method")
                if isinstance(hook_entry, dict)
                else str(hook_entry)
            )

        # Get the hook method
        hook_method = getattr(real_game, hook_method_name, None)
        if not hook_method:
            return HtmxTriggerResponse(
                content=f"Hook method '{hook_method_name}' not found on game",
                content_type="text/plain",
            )

        # Execute based on phase
        if phase == "can":
            # Can phase: return JSON with allowed boolean
            try:
                allowed = hook_method(instance)
                if not isinstance(allowed, bool):
                    allowed = bool(allowed)
            except Exception as e:
                return HtmxTriggerResponse(
                    content=f"Error in can hook: {e}",
                    content_type="text/plain",
                )
            import json

            response = HtmxTriggerResponse(
                content=json.dumps({"allowed": allowed}),
                content_type="application/json",
            )
            return response

        elif phase == "show":
            # Show phase: return partial template
            try:
                partial = hook_method(instance)
                if not isinstance(partial, str):
                    return HtmxTriggerResponse(
                        content="Show hook must return a template path string",
                        content_type="text/plain",
                    )
            except Exception as e:
                return HtmxTriggerResponse(
                    content=f"Error in show hook: {e}",
                    content_type="text/plain",
                )

            # Render the partial with context
            context = {
                "instance": instance,
                "item": instance.item,
                "action": action,
                "phase": "handle",  # Next phase for the action buttons
                "state": instance.item_state._data,  # Pass state dict for template access
                "is_inventory_item": instance.__class__.__name__ == "InventoryItem",
            }
            return self.nilpoint_render(request, partial, context, *args, **kwargs)

        elif phase == "handle":
            # Handle phase: execute the action, then render the show partial
            # to display updated state. Fall back to push_button show hook
            # if the action doesn't have its own show hook (common pattern:
            # multiple handle hooks share one show hook).

            # First, execute the handle hook
            try:
                hook_method(instance, request)
            except Exception as e:
                return HtmxTriggerResponse(
                    content=f"Error in handle hook: {e}",
                    content_type="text/plain",
                )

            # After handling, render the show partial for the same action
            # to display updated state. Fall back to push_button show hook
            # if the action doesn't have its own show hook (common pattern:
            # multiple handle hooks share one show hook).
            show_hooks = hooks.get("show", {})
            show_entry = show_hooks.get(action)
            if not show_entry and "push_button" in show_hooks:
                show_entry = show_hooks["push_button"]

            show_method_name = None
            if isinstance(show_entry, dict):
                show_method_name = show_entry.get("method")
            elif isinstance(show_entry, str):
                # Backward compat: stored as simple string
                show_method_name = show_entry

            if show_method_name:
                show_method = getattr(real_game, show_method_name, None)
                if show_method:
                    try:
                        partial = show_method(instance)
                        if isinstance(partial, str):
                            context = {
                                "instance": instance,
                                "item": instance.item,
                                "action": action,
                                "phase": "handle",
                                "state": instance.item_state._data,
                                "is_inventory_item": instance.__class__.__name__
                                == "InventoryItem",
                            }
                            return self.nilpoint_render(
                                request, partial, context, *args, **kwargs
                            )
                    except Exception as e:
                        return HtmxTriggerResponse(
                            content=f"Error in show hook after handle: {e}",
                            content_type="text/plain",
                        )

            # Fallback: trigger refresh
            response = HtmxTriggerResponse(content="OK", content_type="text/plain")
            response.add_trigger("player_location_changed")
            return response

    @require_http_methods("GET", "POST")
    def handle_item_detail(self, request, *args, **kwargs):
        """Return the detail view of a single item instance (graphic, name, description).

        The instance ID should be given as 'location_item' or 'inventory_item' in the request.
        The instance must belong to the current player character and game instance.

        - Override item_detail_partial used to render the content.

        """
        location_item_id = request.GET.get("location_item", None) or request.POST.get(
            "location_item", None
        )
        inventory_item_id = request.GET.get("inventory_item", None) or request.POST.get(
            "inventory_item", None
        )

        if not location_item_id and not inventory_item_id:
            return HtmxTriggerResponse(
                content="No location_item or inventory_item given in request parameters",
                content_type="text/plain",
            )

        pc = self.player_character
        if pc is None:
            return HtmxTriggerResponse(
                content="No player character selected",
                content_type="text/plain",
            )

        instance = None
        instance_type = None

        if location_item_id:
            try:
                location_item_id = int(location_item_id)
            except (TypeError, ValueError):
                return HtmxTriggerResponse(
                    content="Invalid location_item id", content_type="text/plain"
                )
            instance = LocationItem.objects.filter(id=location_item_id, pc=pc).first()
            instance_type = "location_item"
        else:
            try:
                inventory_item_id = int(inventory_item_id)
            except (TypeError, ValueError):
                return HtmxTriggerResponse(
                    content="Invalid inventory_item id", content_type="text/plain"
                )
            instance = InventoryItem.objects.filter(id=inventory_item_id, pc=pc).first()
            instance_type = "inventory_item"

        if instance is None:
            return HtmxTriggerResponse(
                content="Instance not found or not yours",
                content_type="text/plain",
            )

        # Check the item belongs to the current game
        if instance.item.game != self.game:
            return HtmxTriggerResponse(
                content="Item is not part of this game",
                content_type="text/plain",
            )

        context = {
            "instance": instance,
            "item": instance.item,
            "instance_type": instance_type,
            "item_state_data": instance.item_state._data,
        }
        partial = self._value_from_subclass_or_default(
            "item_detail_partial",
            "nilpoint/item_detail_panel.jinja2#item_detail",
        )
        return self.nilpoint_render(request, partial, context, *args, **kwargs)

    @require_http_methods("POST")
    def handle_use_exit(self, request, *args, **kwargs):
        """Change the player character's location by using an exit. The ID of the exit should be given as 'exit' in the post request."""

        # Get the location ID from post
        exit_id = request.POST.get("exit", None)
        if exit_id is not None:
            exit_obj = Exit.objects.filter(id=exit_id).first()
        else:
            return HtmxTriggerResponse(
                content="No exit given in POST parameters", content_type="text/plain"
            )
        if exit_obj is None:
            return HtmxTriggerResponse(
                content="Invalid Exit - doesn't exist", content_type="text/plain"
            )
        # Get the PC
        pc = self.player_character
        # Get the PC location
        location = pc.current_location

        if not location.exits.filter(id=exit_obj.id).exists():
            return HtmxTriggerResponse(
                content="Invalid Exit - not at current location",
                content_type="text/plain",
            )
        # Change the location
        pc.current_location = exit_obj.exit_to
        pc.save()
        # Send a signal to update the front end
        response = HtmxTriggerResponse(
            content=f"Location updated to {exit_obj.exit_to}", content_type="text/plain"
        )
        response.add_trigger(trigger_name="player_location_changed")
        return response

    @require_http_methods("GET")
    def handle_landing(self, request, *args, **kwargs):
        """Landing page. This is the first page seen when accessing
        the game instance, and is the orchestrator of all others.

        Override the 'partial' used to render the content by setting
        'landing_partial' in a subclass.

        """

        partial = self._value_from_subclass_or_default(
            "landing_partial", "nilpoint/game_landing.jinja2#landing"
        )

        return self.nilpoint_render(request, partial, context={}, *args, **kwargs)

    @require_http_methods("GET", "POST")
    def handle_new_player_character(self, request, *args, **kwargs):
        """Handles new player character creation. By default, displays
        a form on a GET request and processes it on POST.

        Uses self.new_player_character_partial as a template if it
        exists, or the default Nilpoint template if not.

        Form submission is to the URL in
        self.new_player_character_submit or will use the default
        namespace rules if not.

        """

        partial = self._value_from_subclass_or_default(
            "new_player_character_partial",
            "nilpoint/new_player_character.jinja2#new_player_character",
        )
        message = None
        if not request.user.is_authenticated:
            message = (
                "You need to have an account on this site to make player characters"
            )
        elif self.player is None:
            message = "Your account is not a player account"
        elif (
            not self.game.allow_multiple_characters and len(self.player_characters) > 0
        ):
            message = "You can't have more than one player character for this game"
        if message is not None:
            response = self.nilpoint_render(
                request,
                partial,
                {"message": message},
                *args,
                **kwargs,
            )
            response.add_trigger("player_location_changed")
            return response

        url = f"{self.game.get_dispatch_url()}?action=new_player_character"
        url = self._value_from_subclass_or_default("new_player_character_submit", url)

        if request.method == "GET":
            form = NewPlayerCharacterForm()
            return self.nilpoint_render(
                request, partial, {"form": form, "submit_url": url}, *args, **kwargs
            )
        if request.method == "POST":
            form = NewPlayerCharacterForm(request.POST)

            # Add the game object to allow the form to do a narrower
            # check Without it, the form invalidates any duplicate
            # handle, regardless of which game it's used in
            form.game = self.game

            if form.is_valid():
                new_player_character = get_model(
                    self.game._game_type, "PlayerCharacter"
                ).objects.create(
                    player=self.player,
                    game=self.game,
                    handle=form.cleaned_data.get("handle"),
                )

                message = f"Your new player character '{new_player_character.handle}' has been created."

                return self.nilpoint_render(
                    request,
                    partial,
                    {"message": message},
                    trigger="player_character_changed",
                    *args,
                    **kwargs,
                )

            else:
                return self.nilpoint_render(
                    request,
                    partial,
                    {"form": form, "submit_url": url},
                    *args,
                    **kwargs,
                )
        return HtmxTriggerResponse(
            content="Method not implemented", content_type="text/plain"
        )

    @require_http_methods("GET")
    def debug(self, request, *args, **kwargs):
        """Debug view, can be used to drop in to places before the
        views are ready, ensuring everythng else is doing what is
        expected

        """
        return self.nilpoint_render(
            request,
            "nilpoint/debug.jinja2#debug",
            context={"request": request, "args": args, "kwargs": kwargs},
            *args,
            **kwargs,
        )


class NilpointRootView(View):
    def get(self, request, *args, **kwargs):
        return redirect("home")


class NilpointGameDispatchView(View):
    """Pass on requests for Nilpointgames to the game-level dispatch view.

    Combining the nilpoint_slug (identifies a unique instance of a game) and
    the game object _game_type (identifies the game uniquely) gives us
    a way to generate unique URLs that can be served by the game apps.

    The games will be expected to use the namespace of their Game
    class, all lowercase.  For example MyFirstGame is 'myfirstgame'
    and if the instance has the nilpoint_slug 'hello-world' then this
    identifies the instace of MyFirstGame.  The urls will then be
    expected to have the namespace 'myfirstgame' with the keyword arg
    'nilpoint_slug' set to 'hello-world'. A game-level dispatcher
    should pick up the following url names:

     - dispatch (for example the name could be 'myfirstgame:dispatch'
       and the request will include the nilpoint_slug as a keyword
       argument. The URL might actually be
       'games/myfirstgame/hello-world/dispatch'.

    """

    def get(self, request, *args, **kwargs):

        slug = kwargs.get("nilpoint_slug")
        try:
            game = Game.objects.get(nilpoint_slug=slug)

        except Game.DoesNotExist:
            return HtmxTriggerResponse(
                content=f"We don't seem to have a game usingthe slig '{slug}'!"
            )
        redir = redirect(game.get_dispatch_url())
        return redir

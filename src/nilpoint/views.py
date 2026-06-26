from django.views.generic import View
from django.shortcuts import redirect, render
from .models import Game, Player, PlayerCharacter
from django.http import HttpResponseNotFound, HttpResponse
from . import NilpointMissingSlugException
from .forms import NewPlayerCharacterForm
from functools import wraps
import json
from .models import get_model

# TODO: decorators for GET only handlers, POST only or both?
# TODO: create "requires player character" decorator for reuse in game views


class HtmxTriggerResponse(HttpResponse):
    """An HTTP Response that automatically attaches an HTMX trigger header."""

    def __init__(self, content=b"", trigger_name=None, trigger_data=None, **kwargs):
        super().__init__(content, **kwargs)

        if trigger_name:
            # If there's data, pass a dict; otherwise just pass the event name string
            payload = (
                json.dumps({trigger_name: trigger_data})
                if trigger_data
                else trigger_name
            )
            self["HX-Trigger"] = payload


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
    }

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

        response = render(request, template, context=full_context)
        if "trigger" in kwargs:
            response["HX-Trigger"] = kwargs["trigger"]
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
                response = HttpResponse("Action required", content_type="text/plain")
            elif self.action not in self._handlers:
                response = HttpResponse(
                    f"Unknown action '{self.action}'", content_type="text/plain"
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

            return response

        return _get_post_common

    def handle_select_player_character(self, request, *args, **kwargs):
        selected_pc = request.POST.get("player_character", None)
        if selected_pc == "-1":
            self.player_character = None
            return HtmxTriggerResponse(
                "Cleared selected player character",
                content_type="text/plain",
                trigger_name="player_character_changed",
            )

        else:
            try:
                pc = PlayerCharacter.objects.get_subclass(id=selected_pc)

            except PlayerCharacter.DoesNotExist:
                return HttpResponse(
                    f"Couldn't find selected player character '{selected_pc}'",
                    content_type="text/plain",
                )

        if pc.player == self.player and pc.game == self.game:
            self.player_character = pc
            response = HtmxTriggerResponse(
                f"Successfully selected pc {pc.handle}, id {pc.id}.",
                content_type="text/plain",
                trigger_name="player_character_changed",
            )
            response.set_cookie("pc", pc.id)

            return response
        else:
            self.player_character = None
            return HttpResponse("Couldn't match selected pc", content_type="text/plain")

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

    def handle_overview(self, request, *args, **kwargs):
        """Page overview

        Override the 'partial' used to render the content.
        """

        partial = self._value_from_subclass_or_default(
            "overview_partial", "nilpoint/game_overview.jinja2#game_overview"
        )

        return self.nilpoint_render(request, partial, context={}, *args, **kwargs)

    def handle_player_selection_panel(self, request, *args, **kwargs):
        """Player character selection panel

        Override player_selection_panel_partial used to render the content.
        """

        partial = self._value_from_subclass_or_default(
            "player_selection_panel_partial",
            "nilpoint/player_selection.jinja2#player_selection",
        )

        return self.nilpoint_render(request, partial, context={}, *args, **kwargs)

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
            return self.nilpoint_render(
                request,
                partial,
                {"message": message},
                *args,
                **kwargs,
            )

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

                return HttpResponse("Valid", content_type="text/plain")
            else:
                return self.nilpoint_render(
                    request,
                    partial,
                    {"form": form, "submit_url": url},
                    *args,
                    **kwargs,
                )
        return HttpResponse("Method not implemented", content_type="text/plain")

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
            return HttpResponseNotFound(
                f"We don't seem to have a game usingthe slig '{slug}'!"
            )
        redir = redirect(game.get_dispatch_url())
        return redir

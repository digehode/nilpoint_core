"""The demo game: a tiny world showing how a nilpoint game is put together.

The demo ships inside the nilpoint package so it can serve as the worked
example in the documentation and as a fixture for nilpoint's own test
suite.  It is registered like any other game (INSTALLED_APPS +
NILPOINT_SETTINGS in the host project); nothing in core imports it.

What it demonstrates, in the order the release steps build it:

1. `DemoGame` step 1 - locations, a two-way exit, the game's default
   graphics.
2. Step 2 - adding to a world that already exists.
3. Step 3 - items, wired to their interactions via `dotted_path()`,
   created with the check-then-create idiom that keeps an interrupted
   step safe to re-run.
4. Step 4 - an exit wired to an `ExitInteraction`: the storeroom door
   exists only for characters whose keypad code has been accepted, so
   one shared rule over per-player state.
5. `DemoPC` - a player character archetype with an extra field, and a
   character release step that seeds each new character's world.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from nilpoint.decorators import release_step
from nilpoint.models import Exit, Game, Item, Location, LocationItem, PlayerCharacter

from .interactions import HiddenStoreroom, Keypad, Lamp


class DemoGame(Game):
    name = "The Demo Game"
    description = (
        "A small four-room world that demonstrates how a nilpoint game "
        "is built: locations, exits, items, interactions and release steps."
    )

    def _item(self, **kwargs):
        """Create an Item unless one with this asset_id already exists.

        The check-then-create idiom keeps a release step safe to re-run if
        it was interrupted partway (the interrupted step's release number
        is retried, so anything it already created would collide otherwise
        - see the rerun test in nilpoint's core test suite).  `get_asset`
        raises ObjectDoesNotExist when the item isn't there yet.
        """
        try:
            self.get_asset(kwargs["asset_id"], Item)
        except ObjectDoesNotExist:
            Item.objects.create(game=self, **kwargs)

    @release_step(1)
    def initial_world(self):
        """The Lobby, the Hallway, and the exit between them."""
        self.default_location_graphic = "demo/locations/default_location.png"
        self.default_item_graphic = "demo/items/default_item.png"
        self.save()

        lobby = Location.objects.create(
            asset_id="LOBBY",
            name="The Lobby",
            description=(
                "A small lobby with a mat and a noticeboard. "
                "A corridor leads off to the north."
            ),
            game=self,
            graphic="demo/locations/lobby.png",
            initial=True,
        )
        hallway = Location.objects.create(
            asset_id="HALLWAY",
            name="The Hallway",
            description=(
                "A short hallway lined with pegs. The lobby is behind you; "
                "a workshop door stands ahead."
            ),
            game=self,
            graphic="demo/locations/hallway.png",
        )
        Exit.create_two_way_exit(
            lobby,
            "To the hallway",
            hallway,
            "Back to the lobby",
            asset_id_prefix="LOBBY_HALLWAY",
        )

    @release_step(2)
    def workshop(self):
        """The Workshop, one exit further north."""
        hallway = self.get_asset("HALLWAY", Location)
        workshop = Location.objects.create(
            asset_id="WORKSHOP",
            name="The Workshop",
            description=(
                "A cluttered workbench, tools hanging on pegboards, and a "
                "desk lamp glowing in the corner."
            ),
            game=self,
            graphic="demo/locations/workshop.png",
        )
        Exit.create_two_way_exit(
            hallway,
            "To the workshop",
            workshop,
            "Back to the hallway",
            asset_id_prefix="HALLWAY_WORKSHOP",
        )

    @release_step(3)
    def interactive_items(self):
        """The three demo items, each wired to its behaviour.

        The keypad deliberately has no graphic: `graphic_safe` falls back
        to the game's `default_item_graphic` set in step 1.
        """
        self._item(
            asset_id="WELCOME_NOTE",
            name="Welcome note",
            description=(
                "A handwritten note: 'Welcome, traveller. Take me if you "
                "want something to carry.'"
            ),
            graphic="demo/items/welcome_note.png",
        )
        self._item(
            asset_id="DESK_LAMP",
            name="Desk lamp",
            description="A battered desk lamp with a chunky toggle switch.",
            graphic="demo/items/desk_lamp.png",
            can_take=False,
            interaction=Lamp.dotted_path(),
        )
        self._item(
            asset_id="KEYPAD",
            name="Keypad",
            description=(
                "A wall keypad with a four-digit display and a stubborn "
                "lock. The code is on the maker's label: 1234."
            ),
            graphic="",
            can_take=False,
            interaction=Keypad.dotted_path(),
            interaction_options={"code": "1234"},
        )

    @release_step(4)
    def storeroom(self):
        """The Storeroom: a door the hallway keypad opens.

        Both exits are created plain - the way out needs no rules - and
        then the hallway-side door is wired to an `ExitInteraction`.
        Whether it is listed and usable is judged from the character's
        own state, which the keypad's unlock writes and its lock clears,
        so the door appears for the character who entered the code,
        disappears again if they lock the keypad, and stays invisible
        to everyone else.
        """
        hallway = self.get_asset("HALLWAY", Location)
        storeroom = Location.objects.create(
            asset_id="STOREROOM",
            name="The Storeroom",
            description=(
                "Tall shelves of jars, a stepladder, and a bare bulb on a "
                "cord that swings gently overhead."
            ),
            game=self,
            graphic="demo/locations/storeroom.png",
        )
        storeroom_door, _ = Exit.create_two_way_exit(
            hallway,
            "A plain door in the wall",
            storeroom,
            "Back to the hallway",
            asset_id_prefix="HALLWAY_STOREROOM",
        )
        storeroom_door.interaction = HiddenStoreroom.dotted_path()
        storeroom_door.save()


class DemoPC(PlayerCharacter):
    """The demo's player character archetype.

    Registered under the game type "demogame" in NILPOINT_SETTINGS as
    "nilpoint_demo.DemoPC".  Adds one extra field (`tagline`) to show how
    a game extends the base character, and one release step that seeds
    each new character's world.
    """

    tagline = models.CharField(max_length=100, blank=True, default="")

    @release_step(3)
    def seed_demo_items(self):
        """Give this character their own copies of the demo items.

        Numbered to match the game release that created the items: a
        character catches up only as far as the game's current release,
        and release numbers with no character step are skipped.  A
        character created while the game is still at release 1 or 2 gets
        its items when the game next updates and the characters follow.
        """
        for asset_id, location_id in (
            ("WELCOME_NOTE", "LOBBY"),
            ("KEYPAD", "HALLWAY"),
            ("DESK_LAMP", "WORKSHOP"),
        ):
            LocationItem.objects.create(
                pc=self,
                item=self.game.get_asset(asset_id, Item),
                location=self.game.get_asset(location_id, Location),
            )

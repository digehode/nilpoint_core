"""Acceptance tests for the demo game.

The demo ships inside the package as the worked example for game
authors, so these tests pin the behaviour the documentation describes:
release steps build the world (idempotently), new characters get their
own copies of the items, and the interactions - a plain lamp, a coded
keypad, and an exit whose door only exists for characters who opened it -
work through the real view dispatch, per character.
"""

import io
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from nilpoint.demo.interactions import HiddenStoreroom, Keypad, Lamp
from nilpoint.demo.models import DemoGame, DemoPC
from nilpoint.demo.views import DemoGameView
from nilpoint.interactions import DEFAULT_EXIT_REFUSAL, holder_type
from nilpoint.models import (
    Exit,
    InventoryItem,
    Item,
    Location,
    LocationItem,
    Player,
)
from nilpoint.nilpoint_settings import nilpoint_settings

User = get_user_model()


class DemoGameTestCase(TestCase):
    """Shared setup: a demo game instance fully updated by the command."""

    def setUp(self):
        self.factory = RequestFactory()
        self.game = DemoGame.objects.create(
            instance_name="Demo",
            instance_description="A tiny world for tests",
            nilpoint_slug=f"demo_{uuid4().hex[:6]}",
        )
        call_command(
            "nilpoint_update_game",
            "--slug",
            self.game.nilpoint_slug,
            "--full",
            stdout=io.StringIO(),
        )
        self.game.refresh_from_db()

    def make_pc(self, handle, game=None):
        user = User.objects.create_user(username=f"u_{uuid4().hex[:6]}", password="pw")
        player = Player.objects.create(user=user)
        pc = DemoPC.objects.create(handle=handle, player=player, game=game or self.game)
        pc.current_location = (game or self.game).get_initial_location()
        pc.save()
        return pc


class DemoGameWorldTests(DemoGameTestCase):
    """The game's release steps build the documented world."""

    def test_full_update_reaches_the_latest_release(self):
        self.assertEqual(self.game.release, 4)

    def test_four_locations_with_one_initial(self):
        asset_ids = set(
            Location.objects.filter(game=self.game).values_list("asset_id", flat=True)
        )
        self.assertEqual(asset_ids, {"LOBBY", "HALLWAY", "WORKSHOP", "STOREROOM"})
        initial = Location.objects.get(game=self.game, initial=True)
        self.assertEqual(initial.asset_id, "LOBBY")

    def test_exits_link_the_rooms_both_ways(self):
        pairs = set(
            Exit.objects.filter(game=self.game).values_list(
                "exit_from__asset_id", "exit_to__asset_id"
            )
        )
        self.assertEqual(
            pairs,
            {
                ("LOBBY", "HALLWAY"),
                ("HALLWAY", "LOBBY"),
                ("HALLWAY", "WORKSHOP"),
                ("WORKSHOP", "HALLWAY"),
                ("HALLWAY", "STOREROOM"),
                ("STOREROOM", "HALLWAY"),
            },
        )

    def test_the_storeroom_door_carries_the_exit_interaction(self):
        door = Exit.objects.get(
            exit_from__asset_id="HALLWAY", exit_to__asset_id="STOREROOM"
        )
        self.assertEqual(door.interaction, HiddenStoreroom.dotted_path())
        # The way back out is deliberately plain.
        way_out = Exit.objects.get(
            exit_from__asset_id="STOREROOM", exit_to__asset_id="HALLWAY"
        )
        self.assertEqual(way_out.interaction, "")

    def test_items_are_wired_to_their_interactions(self):
        note = self.game.get_asset("WELCOME_NOTE", Item)
        self.assertEqual(note.interaction, "")
        self.assertTrue(note.can_take)

        lamp = self.game.get_asset("DESK_LAMP", Item)
        self.assertEqual(lamp.interaction, Lamp.dotted_path())
        self.assertFalse(lamp.can_take)

        keypad = self.game.get_asset("KEYPAD", Item)
        self.assertEqual(keypad.interaction, Keypad.dotted_path())
        self.assertEqual(keypad.interaction_options, {"code": "1234"})
        self.assertFalse(keypad.can_take)

    def test_keypad_graphic_falls_back_to_the_game_default(self):
        self.assertEqual(
            self.game.default_location_graphic, "demo/locations/default_location.png"
        )
        self.assertEqual(self.game.default_item_graphic, "demo/items/default_item.png")
        keypad = self.game.get_asset("KEYPAD", Item)
        self.assertEqual(keypad.graphic, "")
        self.assertEqual(keypad.graphic_safe, "demo/items/default_item.png")

    def test_full_update_is_idempotent(self):
        def counts():
            return {
                "locations": Location.objects.filter(game=self.game).count(),
                "exits": Exit.objects.filter(game=self.game).count(),
                "items": Item.objects.filter(game=self.game).count(),
            }

        before = counts()
        call_command(
            "nilpoint_update_game",
            "--slug",
            self.game.nilpoint_slug,
            "--full",
            stdout=io.StringIO(),
        )
        self.assertEqual(counts(), before)
        self.game.refresh_from_db()
        self.assertEqual(self.game.release, 4)

    def test_check_interactions_resolves_the_demo_classes(self):
        out = io.StringIO()
        call_command(
            "nilpoint_check_interactions",
            "--game",
            self.game.nilpoint_slug,
            hooks=True,
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("All 3 configured interaction(s) resolved.", output)
        self.assertIn(Lamp.dotted_path(), output)
        self.assertIn(Keypad.dotted_path(), output)
        self.assertIn(HiddenStoreroom.dotted_path(), output)
        # The exit rule is one hook, and the command shows which.
        self.assertIn("hooks: visible", output)


class DemoCharacterTests(DemoGameTestCase):
    """New characters are seeded with their own copies of the items."""

    def test_new_character_gets_its_items(self):
        pc = self.make_pc("hero")
        # The character catches up to the game's release, skipping the
        # game-only step 4 (the storeroom needs no character seeding).
        self.assertEqual(pc.release, 4)
        self.assertEqual(pc.tagline, "")

        seeded = {
            (li.item.asset_id, li.location.asset_id)
            for li in LocationItem.objects.filter(pc=pc)
        }
        self.assertEqual(
            seeded,
            {
                ("WELCOME_NOTE", "LOBBY"),
                ("KEYPAD", "HALLWAY"),
                ("DESK_LAMP", "WORKSHOP"),
            },
        )

    def test_characters_get_separate_copies(self):
        hero = self.make_pc("hero")
        sidekick = self.make_pc("sidekick")
        self.assertEqual(LocationItem.objects.filter(pc=hero).count(), 3)
        self.assertEqual(LocationItem.objects.filter(pc=sidekick).count(), 3)
        # The lobby note is per character: each has their own presence row.
        self.assertEqual(
            LocationItem.objects.filter(item__asset_id="WELCOME_NOTE").count(), 2
        )
        lobby = self.game.get_asset("LOBBY", Location)
        self.assertEqual(hero.items_at(lobby).count(), 1)


class DemoWalkthroughTests(DemoGameTestCase):
    """The demo plays through the real view dispatch, per character."""

    def setUp(self):
        super().setUp()
        self.pc = self.make_pc("hero")
        self.user = self.pc.player.user

    def _dispatch(self, action, data, method="post", pc=None):
        """Full-stack dispatch: action in the query string, data in the body.

        For GET, `RequestFactory` builds the query string from `data`, so the
        action travels there instead of in the path.
        """
        pc = pc or self.pc
        if method == "get":
            data = {"action": action, **data}
            request = self.factory.get("/", data)
        else:
            request = self.factory.post(f"/?action={action}", data)
        request.user = pc.player.user
        request.COOKIES["pc"] = str(pc.id)
        view = DemoGameView()
        return getattr(view, method)(request, nilpoint_slug=self.game.nilpoint_slug)

    def _interact(self, instance, action=None, method="post", pc=None, **extra):
        data = {
            "target_type": holder_type(instance),
            "object_id": instance.pk,
            **extra,
        }
        if action is not None:
            data["action_name"] = action
        return self._dispatch("interact", data, method=method, pc=pc)

    def test_note_can_be_taken_walked_and_dropped(self):
        note = LocationItem.objects.get(pc=self.pc, item__asset_id="WELCOME_NOTE")

        response = self._dispatch("take_item", {"location_item": note.pk})
        self.assertEqual(
            response._log, [{"message": "Took Welcome note", "level": "success"}]
        )
        self.assertFalse(LocationItem.objects.filter(pk=note.pk).exists())
        carried = InventoryItem.objects.get(pc=self.pc, item__asset_id="WELCOME_NOTE")

        hallway_exit = Exit.objects.get(
            exit_from__asset_id="LOBBY", exit_to__asset_id="HALLWAY"
        )
        self._dispatch("use_exit", {"exit": hallway_exit.pk})
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location.asset_id, "HALLWAY")

        self._dispatch("drop_item", {"inventory_item": carried.pk})
        dropped = LocationItem.objects.get(pc=self.pc, item__asset_id="WELCOME_NOTE")
        self.assertEqual(dropped.location.asset_id, "HALLWAY")
        # The other character's note is untouched by all of this.
        sidekick = self.make_pc("sidekick")
        self.assertEqual(
            LocationItem.objects.get(
                pc=sidekick, item__asset_id="WELCOME_NOTE"
            ).location.asset_id,
            "LOBBY",
        )

    def test_lamp_toggle_is_private_to_each_character(self):
        sidekick = self.make_pc("sidekick")
        hero_lamp = LocationItem.objects.get(pc=self.pc, item__asset_id="DESK_LAMP")
        sidekick_lamp = LocationItem.objects.get(
            pc=sidekick, item__asset_id="DESK_LAMP"
        )

        response = self._interact(hero_lamp, "toggle")
        self.assertEqual(
            response._log, [{"message": "The lamp flickers on.", "level": "success"}]
        )
        # The action's response tells the open item detail to re-request
        # itself, so its state display does not keep the pre-toggle copy.
        self.assertIn("item_state_changed", response.htmx_triggers)
        self.assertTrue(LocationItem.objects.get(pk=hero_lamp.pk).item_state.get("lit"))
        self.assertIsNone(
            LocationItem.objects.get(pk=sidekick_lamp.pk).item_state.get("lit")
        )

        self._interact(hero_lamp, "toggle")
        self.assertFalse(
            LocationItem.objects.get(pk=hero_lamp.pk).item_state.get("lit")
        )

    def test_keypad_unlocks_with_the_configured_code(self):
        keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")

        response = self._interact(keypad, "unlock", code="0000")
        self.assertEqual(
            response._log, [{"message": "The keypad buzzes.", "level": "success"}]
        )
        self.assertIsNone(self.pc.item_state.get("storeroom_open"))

        response = self._interact(keypad, "unlock", code="1234")
        self.assertEqual(
            response._log,
            [
                {
                    "message": "The keypad beeps and the light turns green.",
                    "level": "success",
                }
            ],
        )
        self.assertTrue(self.pc.item_state.get("storeroom_open"))
        # One fact, one home: the keypad record keeps no parallel copy of
        # the lock state that could fall out of step with the door.
        self.assertIsNone(
            LocationItem.objects.get(pk=keypad.pk).item_state.get("unlocked")
        )

    def test_unlock_is_refused_once_unlocked_and_lock_reopens(self):
        keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")
        self._interact(keypad, "unlock", code="1234")

        # The view enforces the interaction's `can` gate, not just the UI.
        response = self._interact(keypad, "unlock", code="1234")
        self.assertIn(b"Can't enter the code that right now", response.content)
        self.assertTrue(self.pc.item_state.get("storeroom_open"))

        response = self._interact(keypad, "lock")
        self.assertEqual(
            response._log, [{"message": "The keypad locks.", "level": "success"}]
        )
        self.assertFalse(self.pc.item_state.get("storeroom_open"))

    def test_keypad_panel_switches_between_form_and_buttons(self):
        keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")

        response = self._interact(keypad, method="get")
        content = response.content.decode()
        self.assertIn("The keypad light is red.", content)
        self.assertIn("keypad-form", content)
        # Loading the panel changes nothing, so it does not ask the detail
        # to refresh (a load-time firing would loop).
        self.assertNotIn("item_state_changed", response.htmx_triggers)

        self._interact(keypad, "unlock", code="1234")
        response = self._interact(keypad, method="get")
        content = response.content.decode()
        self.assertIn("The keypad light is green.", content)
        self.assertIn("Lock it again", content)
        self.assertNotIn("keypad-form", content)

    def test_unlocking_is_scoped_to_the_characters_own_state(self):
        sidekick = self.make_pc("sidekick")
        hero_keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")

        self._interact(hero_keypad, "unlock", code="1234")
        self.assertTrue(self.pc.item_state.get("storeroom_open"))
        self.assertIsNone(sidekick.item_state.get("storeroom_open"))

    def _walk_to_hallway(self, pc=None):
        lobby_exit = Exit.objects.get(
            exit_from__asset_id="LOBBY", exit_to__asset_id="HALLWAY"
        )
        self._dispatch("use_exit", {"exit": lobby_exit.pk}, pc=pc)
        pc = pc or self.pc
        pc.refresh_from_db()
        self.assertEqual(pc.current_location.asset_id, "HALLWAY")

    def _storeroom_door(self):
        return Exit.objects.get(
            exit_from__asset_id="HALLWAY", exit_to__asset_id="STOREROOM"
        )

    def test_the_storeroom_door_opens_only_for_the_character_who_entered_the_code(
        self,
    ):
        sidekick = self.make_pc("sidekick")
        hallway = self.game.get_asset("HALLWAY", Location)
        door = self._storeroom_door()

        # Before the code: the door is in nobody's exit list.
        self._walk_to_hallway()
        self._walk_to_hallway(pc=sidekick)
        self.assertNotIn(door, hallway.exits.visible_to(self.pc))
        self.assertNotIn(door, hallway.exits.visible_to(sidekick))

        # Naming the exit directly still refuses - hidden means unusable -
        # and neither character is moved.
        for pc in (self.pc, sidekick):
            response = self._dispatch("use_exit", {"exit": door.pk}, pc=pc)
            self.assertEqual(response.content.decode(), DEFAULT_EXIT_REFUSAL)
            pc.refresh_from_db()
            self.assertEqual(pc.current_location.asset_id, "HALLWAY")

        # The hero's code opens the door for the hero alone.
        hero_keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")
        self._interact(hero_keypad, "unlock", code="1234")

        self.assertIn(door, hallway.exits.visible_to(self.pc))
        self.assertNotIn(door, hallway.exits.visible_to(sidekick))

        # And the exit list itself shows only what each character can see.
        response = self._dispatch("get_player_location_panel", {}, method="get")
        self.assertIn("A plain door in the wall", response.content.decode())
        response = self._dispatch(
            "get_player_location_panel", {}, method="get", pc=sidekick
        )
        self.assertNotIn("A plain door in the wall", response.content.decode())

        # The hero walks through; inside, the way back out is a plain exit.
        response = self._dispatch("use_exit", {"exit": door.pk})
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location.asset_id, "STOREROOM")
        storeroom = self.game.get_asset("STOREROOM", Location)
        way_out = Exit.objects.get(
            exit_from__asset_id="STOREROOM", exit_to__asset_id="HALLWAY"
        )
        self.assertIn(way_out, storeroom.exits.visible_to(self.pc))

        # The sidekick's door is still shut - their state never changed.
        self._dispatch("use_exit", {"exit": door.pk}, pc=sidekick)
        sidekick.refresh_from_db()
        self.assertEqual(sidekick.current_location.asset_id, "HALLWAY")

    def _location_panel(self):
        """The controls panel HTML: the exits a character can see right now."""
        response = self._dispatch("get_player_location_panel", {}, method="get")
        return response.content.decode()

    def test_relocking_the_keypad_closes_the_storeroom_door(self):
        hallway = self.game.get_asset("HALLWAY", Location)
        door = self._storeroom_door()
        keypad = LocationItem.objects.get(pc=self.pc, item__asset_id="KEYPAD")

        # At the hallway the door is shut: not in the rule's list, and not
        # on the panel the player is actually looking at.
        self._walk_to_hallway()
        self.assertNotIn(door, hallway.exits.visible_to(self.pc))
        self.assertNotIn("A plain door in the wall", self._location_panel())

        # Unlocking lifts the latch, and the exits list shows it.
        self._interact(keypad, "unlock", code="1234")
        self.assertTrue(self.pc.item_state.get("storeroom_open"))
        self.assertIn(door, hallway.exits.visible_to(self.pc))
        self.assertIn("A plain door in the wall", self._location_panel())

        # Locking clears the one key the panel and the door both read.  The
        # action also fires item_state_changed, which the controls panel
        # subscribes to, so what the player sees cannot go stale.
        response = self._interact(keypad, "lock")
        self.assertEqual(
            response._log, [{"message": "The keypad locks.", "level": "success"}]
        )
        self.assertIn("item_state_changed", response.htmx_triggers)
        self.assertIs(self.pc.item_state.get("storeroom_open"), False)
        self.assertNotIn(door, hallway.exits.visible_to(self.pc))
        self.assertNotIn("A plain door in the wall", self._location_panel())

        # The keypad's own panel agrees without a second state to consult.
        response = self._interact(keypad, method="get")
        self.assertIn("The keypad light is red.", response.content.decode())

        # Hidden means unusable again: a forced use refuses and the hero
        # stays put.
        response = self._dispatch("use_exit", {"exit": door.pk})
        self.assertEqual(response.content.decode(), DEFAULT_EXIT_REFUSAL)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location.asset_id, "HALLWAY")

        # And the code works again from scratch.
        self._interact(keypad, "unlock", code="1234")
        self.assertIn(door, hallway.exits.visible_to(self.pc))
        self.assertIn("A plain door in the wall", self._location_panel())


class DemoWiringTests(DemoGameTestCase):
    """The demo is registered and overridable the way the docs describe."""

    def test_demo_game_is_a_configured_game(self):
        self.assertIn(DemoGame, nilpoint_settings.games())

    def test_player_character_archetype_is_the_demo_subclass(self):
        self.assertEqual(
            nilpoint_settings.get_archetype("demogame", "PlayerCharacter"),
            "nilpoint_demo.DemoPC",
        )

    def test_game_and_character_are_registered_in_the_admin(self):
        # The admin is the only way to make a playable instance.
        self.assertIn(DemoGame, admin.site._registry)
        self.assertIn(DemoPC, admin.site._registry)

    def test_demo_uses_the_default_landing(self):
        """The demo no longer overrides the landing: it uses nilpoint's.

        The default landing carries the standard panels - including the
        state-dependent scene/controls subscriptions that keep rule-driven
        exits live - so a game writes its own landing only when it needs
        extra UI the default does not have.
        """
        pc = self.make_pc("hero")
        request = self.factory.get("/?action=landing")
        request.user = pc.player.user
        request.COOKIES["pc"] = str(pc.id)
        view = DemoGameView()
        content = view.get(
            request, nilpoint_slug=self.game.nilpoint_slug
        ).content.decode()

        for panel_id in (
            "nilpoint-character-panel",
            "nilpoint-scene",
            "nilpoint-controls",
            "nilpoint-location-item-panel",
            "nilpoint-inventory-panel",
        ):
            self.assertIn(f'id="{panel_id}"', content)
        # The debug deck is parked (commented) in the default landing, so no
        # game renders it until one opts into a landing of its own.
        self.assertNotIn("deck-debug", content)

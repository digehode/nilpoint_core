"""Per-player rules for exits and locations.

Exits carry an `ExitInteraction` (listed? usable? refusal message) and
locations a `LocationInteraction` (description? graphic?), the same way
items carry an `InteractiveItem`: the rules read per-player state, actions
write it, and an asset with no interaction configured behaves exactly as
before.  Everything here checks the three layers - the class families and
their family validation, the model helpers, and the `use_exit` view gate.
"""

import io
import re
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from nilpoint import models
from nilpoint.exceptions import UnresolvableInteraction
from nilpoint.interactions import (
    DEFAULT_EXIT_REFUSAL,
    ExitInteraction,
    HasItem,
    RequiresPCState,
    SetState,
    StateToggle,
)
from nilpoint.models import Exit, Player, PlayerCharacter
from nilpoint.tests.test_interaction_fixtures import (
    BrokenExitGate,
    BrokenRoomView,
    HiddenUnlessLit,
    LockedUntilUnlatched,
    SqueezeWotsit,
    TorchSight,
    WotsitLever,
)
from nilpoint.views import NilpointGameBasic

User = get_user_model()


class TwoRoomWorld(TestCase):
    """A two-room world, one character, and a plain door between them.

    The plain door is deliberately unconfigured: every default in the
    system is the behaviour it had before any of this existed.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        self.player = Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="Rules Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        self.pc = PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.room_a = models.Location.objects.create(
            asset_id="room_a",
            name="Room A",
            description="Plain walls.",
            game=self.game,
            initial=True,
        )
        self.room_b = models.Location.objects.create(
            asset_id="room_b",
            name="Room B",
            description="The other side.",
            game=self.game,
        )
        self.plain_exit, self.way_back = Exit.create_two_way_exit(
            self.room_a,
            "To Room B",
            self.room_b,
            "Back to Room A",
            "AB",
        )
        self.pc.current_location = self.room_a
        self.pc.save()
        self.factory = RequestFactory()

    def _use_exit(self, exit_obj, pc=None):
        """POST the use_exit action the way the interface would."""
        pc = pc if pc is not None else self.pc
        request = self.factory.post("/dispatch?action=use_exit", {"exit": exit_obj.pk})
        request.user = self.user
        request.COOKIES["pc"] = str(pc.id)

        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_character = pc
        return view.handle_use_exit(request)


class ExitFamilyTests(TwoRoomWorld):
    """Which behaviour classes an exit may name."""

    def test_exit_resolves_an_exit_interaction(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        interaction = self.plain_exit.get_interaction(pc=self.pc)
        self.assertIsInstance(interaction, HiddenUnlessLit)
        self.assertIs(interaction.pc, self.pc)

    def test_exit_rejects_an_item_interaction(self):
        """An item's class would silently do nothing on a door - it is an
        error the check command can see instead."""
        self.plain_exit.interaction = SqueezeWotsit.dotted_path()
        self.plain_exit.save()

        with self.assertRaises(UnresolvableInteraction) as ctx:
            self.plain_exit.get_interaction_class()
        self.assertIn("not an ExitInteraction subclass", str(ctx.exception))

    def test_exit_rejects_an_unimportable_path(self):
        self.plain_exit.interaction = "nowhere.NoSuchInteraction"
        self.plain_exit.save()

        with self.assertRaises(UnresolvableInteraction) as ctx:
            self.plain_exit.get_interaction_class()
        self.assertIn("cannot be imported", str(ctx.exception))


class ExitRuleTests(TwoRoomWorld):
    """visible_to / usable_by / refusal_for over per-player state."""

    def test_an_unconfigured_exit_is_plain(self):
        self.assertTrue(self.plain_exit.visible_to(self.pc))
        self.assertTrue(self.plain_exit.usable_by(self.pc))
        self.assertEqual(self.plain_exit.refusal_for(self.pc), DEFAULT_EXIT_REFUSAL)

    def test_visibility_follows_character_state(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.visible_to(self.pc))
        self.assertFalse(self.plain_exit.usable_by(self.pc))

        self.pc.item_state.put("lit", True)
        self.assertTrue(self.plain_exit.visible_to(self.pc))
        self.assertTrue(self.plain_exit.usable_by(self.pc))

    def test_a_listed_exit_can_still_be_locked(self):
        self.plain_exit.interaction = LockedUntilUnlatched.dotted_path()
        self.plain_exit.save()

        self.assertTrue(self.plain_exit.visible_to(self.pc))
        self.assertFalse(self.plain_exit.usable_by(self.pc))
        self.assertEqual(self.plain_exit.refusal_for(self.pc), "The latch is fast.")

        self.pc.item_state.put("unlatched", True)
        self.assertTrue(self.plain_exit.usable_by(self.pc))

    def test_each_character_has_its_own_door(self):
        """The rules read one character's state; another character's identical
        door is judged on theirs, so nothing bleeds between players."""
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()
        sidekick_user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        sidekick = PlayerCharacter.objects.create(
            handle="sidekick",
            player=Player.objects.create(user=sidekick_user),
            game=self.game,
        )

        self.pc.item_state.put("lit", True)

        self.assertTrue(self.plain_exit.visible_to(self.pc))
        self.assertFalse(self.plain_exit.visible_to(sidekick))

    def test_raising_gate_fails_closed(self):
        """A broken rule hides or refuses rather than taking the page down."""
        self.plain_exit.interaction = BrokenExitGate.dotted_path()
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.usable_by(self.pc))
        # Even its own refusal message is broken, so the default stands.
        self.assertEqual(self.plain_exit.refusal_for(self.pc), DEFAULT_EXIT_REFUSAL)

    def test_misconfigured_exit_fails_closed(self):
        """A path that will not import hides the exit, not the page -
        nilpoint_check_interactions reports the underlying problem."""
        self.plain_exit.interaction = "nowhere.NoSuchInteraction"
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.visible_to(self.pc))
        self.assertFalse(self.plain_exit.usable_by(self.pc))
        self.assertEqual(self.plain_exit.refusal_for(self.pc), DEFAULT_EXIT_REFUSAL)

    def test_related_manager_filters_a_locations_exits(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        # Dark: only the unconfigured way back is listed from Room B, and
        # nothing from Room A.
        self.assertNotIn(self.plain_exit, self.room_a.exits.visible_to(self.pc))
        self.assertIn(self.way_back, self.room_b.exits.visible_to(self.pc))

        self.pc.item_state.put("lit", True)
        self.assertIn(self.plain_exit, self.room_a.exits.visible_to(self.pc))

    def test_the_global_manager_filters_too(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        visible = Exit.objects.visible_to(self.pc)
        self.assertNotIn(self.plain_exit, visible)
        self.assertIn(self.way_back, visible)


class UseExitGateTests(TwoRoomWorld):
    """The view enforces visible and usable - a POST cannot go around it."""

    def test_a_plain_exit_moves_the_character(self):
        response = self._use_exit(self.plain_exit)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_b.pk)
        self.assertIn("player_location_changed", response.htmx_triggers)

    def test_an_invisible_exit_cannot_be_forced(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        response = self._use_exit(self.plain_exit)
        self.assertEqual(response.content.decode(), DEFAULT_EXIT_REFUSAL)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_a.pk)

    def test_a_visible_but_locked_exit_refuses_with_its_own_message(self):
        self.plain_exit.interaction = LockedUntilUnlatched.dotted_path()
        self.plain_exit.save()

        response = self._use_exit(self.plain_exit)
        self.assertEqual(response.content.decode(), "The latch is fast.")
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_a.pk)

    def test_unlocking_opens_the_door_for_that_character_only(self):
        self.plain_exit.interaction = LockedUntilUnlatched.dotted_path()
        self.plain_exit.save()
        self.pc.item_state.put("unlatched", True)

        response = self._use_exit(self.plain_exit)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_b.pk)
        self.assertIn("player_location_changed", response.htmx_triggers)

    def test_a_raising_gate_is_refused_not_crashed(self):
        self.plain_exit.interaction = BrokenExitGate.dotted_path()
        self.plain_exit.save()

        response = self._use_exit(self.plain_exit)
        self.assertEqual(response.content.decode(), DEFAULT_EXIT_REFUSAL)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_a.pk)

    def test_an_exit_from_another_game_is_rejected(self):
        other_game = models.Game.objects.create(
            instance_name="Elsewhere",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        other_room = models.Location.objects.create(
            asset_id="elsewhere", name="Elsewhere", description="", game=other_game
        )
        other_room_2 = models.Location.objects.create(
            asset_id="elsewhere_2", name="Further", description="", game=other_game
        )
        foreign_exit = Exit.objects.create(
            name="Somewhere else",
            exit_from=other_room,
            exit_to=other_room_2,
            game=other_game,
            asset_id="FOREIGN",
        )

        response = self._use_exit(foreign_exit)
        self.assertEqual(
            response.content.decode(), "Invalid Exit - not part of this game"
        )
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_location_id, self.room_a.pk)


class GenericExitGateTests(TwoRoomWorld):
    """The shipped generic gates, configured on the asset."""

    def test_requires_pc_state_reads_its_key_from_options(self):
        self.plain_exit.interaction = RequiresPCState.dotted_path()
        self.plain_exit.interaction_options = {"state_key": "storeroom_open"}
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.visible_to(self.pc))
        self.pc.item_state.put("storeroom_open", True)
        self.assertTrue(self.plain_exit.visible_to(self.pc))

    def test_requires_pc_state_without_a_key_fails_closed(self):
        self.plain_exit.interaction = RequiresPCState.dotted_path()
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.visible_to(self.pc))

    def test_has_item_gates_usability_on_inventory(self):
        self.plain_exit.interaction = HasItem.dotted_path()
        self.plain_exit.interaction_options = {"asset_id": "BRASS_KEY"}
        self.plain_exit.save()

        # The door is visible - the player can see that it is locked.
        self.assertTrue(self.plain_exit.visible_to(self.pc))
        self.assertFalse(self.plain_exit.usable_by(self.pc))

        key = models.Item.objects.create(
            asset_id="BRASS_KEY",
            name="Brass Key",
            description="A small brass key.",
            game=self.game,
        )
        models.InventoryItem.objects.create(pc=self.pc, item=key)
        self.assertTrue(self.plain_exit.usable_by(self.pc))

    def test_has_item_without_a_key_fails_closed(self):
        self.plain_exit.interaction = HasItem.dotted_path()
        self.plain_exit.save()

        self.assertFalse(self.plain_exit.usable_by(self.pc))


class LocationRuleTests(TwoRoomWorld):
    """description_for / graphic_for over per-player state."""

    def test_an_unconfigured_location_renders_its_own_values(self):
        self.assertEqual(self.room_a.description_for(self.pc), "Plain walls.")
        self.assertEqual(self.room_a.graphic_for(self.pc), self.room_a.graphic_safe)

    def test_location_rejects_an_exit_interaction(self):
        self.room_a.interaction = HiddenUnlessLit.dotted_path()
        self.room_a.save()

        with self.assertRaises(UnresolvableInteraction) as ctx:
            self.room_a.get_interaction_class()
        self.assertIn("not a LocationInteraction subclass", str(ctx.exception))

    def test_overrides_follow_character_state(self):
        self.room_a.interaction = TorchSight.dotted_path()
        self.room_a.save()

        # Dark: falls through to the room's own description and graphic.
        self.assertEqual(self.room_a.description_for(self.pc), "Plain walls.")
        self.assertEqual(self.room_a.graphic_for(self.pc), self.room_a.graphic_safe)

        self.pc.item_state.put("lit", True)
        self.assertEqual(
            self.room_a.description_for(self.pc), "Flooded with warm light!"
        )
        self.assertEqual(self.room_a.graphic_for(self.pc), "test/torchlit.png")

    def test_overrides_are_per_character(self):
        self.room_a.interaction = TorchSight.dotted_path()
        self.room_a.save()
        sidekick_user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        sidekick = PlayerCharacter.objects.create(
            handle="sidekick",
            player=Player.objects.create(user=sidekick_user),
            game=self.game,
        )

        self.pc.item_state.put("lit", True)
        self.assertEqual(
            self.room_a.description_for(self.pc), "Flooded with warm light!"
        )
        self.assertEqual(self.room_a.description_for(sidekick), "Plain walls.")

    def test_a_raising_hook_falls_back_to_the_databases_values(self):
        self.room_a.interaction = BrokenRoomView.dotted_path()
        self.room_a.save()

        self.assertEqual(self.room_a.description_for(self.pc), "Plain walls.")
        self.assertEqual(self.room_a.graphic_for(self.pc), self.room_a.graphic_safe)

    def test_a_misconfigured_location_falls_back_too(self):
        self.room_a.interaction = "nowhere.NoSuchInteraction"
        self.room_a.save()

        self.assertEqual(self.room_a.description_for(self.pc), "Plain walls.")
        self.assertEqual(self.room_a.graphic_for(self.pc), self.room_a.graphic_safe)


class PCStateActionTests(TwoRoomWorld):
    """`state_target="pc"` writes the character's own state; the default
    still writes the player's copy of the record."""

    def test_set_state_can_write_character_state(self):
        action = SetState(
            "open",
            state_key="storeroom_open",
            state_target="pc",
            value=True,
            message="The latch lifts.",
        )
        interaction = HiddenUnlessLit(self.plain_exit, pc=self.pc)

        message = action.handle(None, interaction, None)

        self.assertTrue(self.pc.item_state.get("storeroom_open"))
        self.assertEqual(message, "The latch lifts.")

    def test_state_toggle_can_flip_character_state(self):
        action = StateToggle(
            "push",
            state_key="lit",
            state_target="pc",
            on_message="click",
            off_message="clack",
        )
        interaction = HiddenUnlessLit(self.plain_exit, pc=self.pc)

        action.handle(None, interaction, None)
        self.assertTrue(self.pc.item_state.get("lit"))
        action.handle(None, interaction, None)
        self.assertFalse(self.pc.item_state.get("lit"))

    def test_pc_target_without_a_character_raises(self):
        action = SetState("open", state_key="k", state_target="pc", value=True)
        interaction = HiddenUnlessLit(self.plain_exit)

        with self.assertRaises(TypeError):
            action.handle(None, interaction, None)

    def test_the_default_target_still_writes_the_records_state(self):
        action = SetState("switch", state_key="lit", value=True)
        record = models.InventoryItem.objects.create(
            pc=self.pc,
            item=models.Item.objects.create(
                asset_id="torch", name="Torch", description="", game=self.game
            ),
        )
        interaction = HiddenUnlessLit(self.plain_exit, instance=record, pc=self.pc)

        action.handle(record, interaction, None)

        self.assertTrue(record.item_state.get("lit"))
        self.assertFalse(self.pc.item_state.get("lit"))


class CheckCommandHooksTests(TwoRoomWorld):
    """`--hooks` makes the hooks a class really defines visible, so a
    typo'd hook name stands out."""

    def _run(self, **options):
        out = io.StringIO()
        call_command(
            "nilpoint_check_interactions",
            stdout=out,
            stderr=out,
            game=self.game.nilpoint_slug,
            **options,
        )
        return out.getvalue()

    def test_hooks_are_listed_per_class(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()
        self.room_a.interaction = TorchSight.dotted_path()
        self.room_a.save()

        output = self._run(hooks=True)
        self.assertIn("hooks: visible", output)
        self.assertIn("hooks: describe, graphic", output)

    def test_a_class_that_overrides_nothing_lists_none(self):
        self.plain_exit.interaction = ExitInteraction.dotted_path()
        self.plain_exit.save()

        output = self._run(hooks=True)
        self.assertIn("hooks: (none)", output)

    def test_a_wrong_family_fails_the_check(self):
        self.plain_exit.interaction = WotsitLever.dotted_path()
        self.plain_exit.save()

        with self.assertRaises(SystemExit):
            self._run(hooks=True)
        # It refused to run to completion rather than passing quietly on a
        # wrong family; the FAIL lines are checked by the demo tests.

    def test_hooks_are_optional(self):
        self.plain_exit.interaction = HiddenUnlessLit.dotted_path()
        self.plain_exit.save()

        output = self._run()
        self.assertNotIn("hooks:", output)
        self.assertIn("resolved", output)


class RuleDrivenPanelReloadTests(TwoRoomWorld):
    """The panels whose content rules judge reload when state changes.

    Exit visibility and a location's description/graphic are judged from
    per-player state - which any interaction action, or a take/drop, can
    write.  The landing subscribes the scene, description and exits panels
    to the events those changes fire, so a door that opens or closes
    mid-session is never left stale: the exits list re-requests itself.

    This is engine wiring rather than per-game wiring on purpose: the
    shipped `RequiresPCState`/`HasItem` gates have no action of their own
    to hang a trigger on - the state they read is written elsewhere.
    """

    STATE_EVENTS = (
        "player_location_changed",
        "location_items_changed",
        "inventory_items_changed",
        "item_state_changed",
    )

    def _panel_triggers(self, panel_id):
        """The hx-trigger string of one panel in the default landing."""
        request = self.factory.get("/?action=landing")
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)

        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_characters = [self.pc]
        view.player_character = self.pc
        content = view.handle_landing(request).content.decode()

        match = re.search(
            rf'id="{panel_id}"[^>]*?hx-trigger="([^"]*)"',
            content,
        )
        self.assertIsNotNone(match, f"{panel_id} was not rendered")
        return match.group(1)

    def test_exits_panel_reloads_when_player_state_changes(self):
        """The exits list follows state written by any action or take/drop."""
        triggers = self._panel_triggers("nilpoint-exits")
        for event in self.STATE_EVENTS:
            self.assertIn(event, triggers)

    def test_description_panel_reloads_when_player_state_changes(self):
        """The description reads the same state the exits list does."""
        triggers = self._panel_triggers("nilpoint-location-description")
        for event in self.STATE_EVENTS:
            self.assertIn(event, triggers)

    def test_scene_panel_reloads_when_player_state_changes(self):
        """The graphic follows the same state a location rule may read."""
        triggers = self._panel_triggers("nilpoint-scene")
        for event in self.STATE_EVENTS:
            self.assertIn(event, triggers)


class LandingStructureTests(TwoRoomWorld):
    """The default landing's grouping and heading hierarchy.

    The landing is two groups - location (scene, description, items,
    exits) then character (inventory, item detail, log) - under a header
    row, so layout is pure CSS over stable ids and a game writes its own
    landing only for structural changes.  One h1 (the game title), group
    titles as visually-hidden h2s, panel headings as h3s: a screen reader
    gets a hierarchy instead of five competing h1s.
    """

    def _landing(self):
        """A view wired up against the default game, request included."""
        request = self.factory.get("/?action=landing")
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)

        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_characters = [self.pc]
        view.player_character = self.pc
        return view, request

    def _landing_html(self):
        view, request = self._landing()
        return view.handle_landing(request).content.decode()

    def _assert_inside(self, content, outer_id, inner_id):
        """One element with `inner_id` sits inside the element with `outer_id`."""
        outer = content.index(f'id="{outer_id}"')
        inner = content.index(f'id="{inner_id}"')
        close = content.index("</section>", outer)
        self.assertTrue(outer < inner < close, f"{inner_id} is not inside {outer_id}")

    def test_panels_are_grouped_into_location_and_character(self):
        content = self._landing_html()

        for panel_id in (
            "nilpoint-scene",
            "nilpoint-location-description",
            "nilpoint-location-item-panel",
            "nilpoint-exits",
        ):
            self._assert_inside(content, "nilpoint-location-group", panel_id)
        for panel_id in (
            "nilpoint-inventory-panel",
            "nilpoint-item-detail-panel",
            "nilpoint-log",
        ):
            self._assert_inside(content, "nilpoint-character-group", panel_id)

    def test_the_console_wraps_the_game_container_in_a_bezel(self):
        content = self._landing_html()

        self.assertIn('<div class="nilpoint-bezel">', content)
        self.assertLess(
            content.index('class="nilpoint-bezel"'),
            content.index('id="nilpoint-game-container"'),
        )

    def test_panels_share_the_nilpoint_panel_class(self):
        """Every panel box carries the shared `.nilpoint-panel` styling hook."""
        content = self._landing_html()

        for panel_id in (
            "nilpoint-character-panel",
            "nilpoint-scene",
            "nilpoint-location-description",
            "nilpoint-location-item-panel",
            "nilpoint-exits",
            "nilpoint-inventory-panel",
            "nilpoint-item-detail-panel",
            "nilpoint-log",
        ):
            start = content.index(f'id="{panel_id}"')
            tag = content[start : content.index(">", start)]
            self.assertIn('class="nilpoint-panel"', tag, panel_id)

    def test_the_landing_has_one_h1_and_hidden_group_titles(self):
        content = self._landing_html()

        self.assertEqual(content.count("<h1"), 1)
        for title in ("Location", "Character"):
            self.assertIn(
                f'<h2 id="nilpoint-{title.lower()}-group-title"'
                f' class="nilpoint-visually-hidden">{title}</h2>',
                content,
            )
        self.assertIn('aria-labelledby="nilpoint-location-group-title"', content)
        self.assertIn('aria-labelledby="nilpoint-character-group-title"', content)

    def test_panel_headings_are_h3s(self):
        """The location name captions the scene; list panels carry HUD labels."""
        view, request = self._landing()

        graphic = view.handle_get_location_graphic(request).content.decode()
        self.assertIn(
            '<h3 class="nilpoint-scene-caption">Room A</h3>',
            graphic,
        )

        description = view.handle_get_location_description(request).content.decode()
        self.assertNotIn("<h3", description)

        exits = view.handle_get_location_exits(request).content.decode()
        self.assertIn('<h3 class="nilpoint-panel-label">Exits</h3>', exits)

        inventory = view.handle_get_inventory_panel(request).content.decode()
        self.assertIn('<h3 class="nilpoint-panel-label">Inventory</h3>', inventory)

    def test_the_log_is_a_live_region_with_its_listener(self):
        content = self._landing_html()

        self.assertIn('id="nilpoint-log"', content)
        self.assertIn('role="log"', content)
        self.assertIn('aria-live="polite"', content)
        self.assertIn("window.__nilpointLog", content)

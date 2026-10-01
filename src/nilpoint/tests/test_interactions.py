"""Tests for the InteractiveItem system.

Two layers are covered: the interaction classes in isolation (no HTTP, no view
plumbing) and the dispatch view that runs their phases for a request.
"""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.template.loader import render_to_string

from nilpoint import models
from nilpoint.exceptions import UnresolvableInteraction
from nilpoint.interactions import (
    Action,
    InteractiveItem,
    get_interaction,
    get_interaction_asset,
    holder_type,
)
from nilpoint.models import Player, PlayerCharacter
from nilpoint.templatetags.nilpoint_tags import nilpoint_interact_actions
from nilpoint.tests.test_interaction_fixtures import (
    CountingInteraction,
    MessyActionInteraction,
    SqueezeWotsit,
    WotsitLever,
)
from nilpoint.views import (
    HtmxTriggerResponse,
    NilpointGameBasic,
    _get_interaction_target_model,
    _get_interaction_target_names,
)

User = get_user_model()


class ActionTests(TestCase):
    """Action is a plain declaration, so it needs no database."""

    def test_display_label_derived_from_name(self):
        self.assertEqual(Action("push_button").display_label, "Push Button")

    def test_explicit_label_wins(self):
        self.assertEqual(
            Action("push_button", label="Push it").display_label, "Push it"
        )

    def test_repr_names_the_action(self):
        self.assertIn("push_button", repr(Action("push_button", label="Push it")))


class InteractiveItemTests(TestCase):
    """The base class and its resolution machinery, against real Items."""

    def setUp(self):
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        self.item = models.Item.objects.create(
            asset_id="wotsit",
            name="A Wotsit",
            description="A wotsit",
            game=self.game,
        )

    def test_no_interaction_configured_returns_none(self):
        self.assertIsNone(self.item.get_interaction_class())
        self.assertIsNone(self.item.get_interaction())
        self.assertIsNone(self.item.describe_interaction())

    def test_dotted_path_round_trips(self):
        self.item.interaction = WotsitLever.dotted_path()
        self.item.save()
        self.item.refresh_from_db()
        self.assertIs(self.item.get_interaction_class(), WotsitLever)
        self.assertEqual(
            self.item.get_interaction_class().dotted_path(),
            "nilpoint.tests.test_interaction_fixtures.WotsitLever",
        )

    def test_one_class_serves_many_items(self):
        """The whole point of the class approach: behaviour is shared by
        naming it, not by duplicating methods on the Game."""
        other = models.Item.objects.create(
            asset_id="second_wotsit",
            name="Another Wotsit",
            description="Also a wotsit",
            game=self.game,
            interaction=WotsitLever.dotted_path(),
        )
        self.item.interaction = WotsitLever.dotted_path()
        self.item.save()

        self.assertIs(self.item.get_interaction_class(), WotsitLever)
        self.assertIs(other.get_interaction_class(), WotsitLever)

    def test_unimportable_path_raises_with_context(self):
        self.item.interaction = "nowhere.NoSuchInteraction"
        self.item.save()
        with self.assertRaises(UnresolvableInteraction) as ctx:
            self.item.get_interaction_class()
        message = str(ctx.exception)
        self.assertIn("wotsit", message)
        self.assertIn("nowhere.NoSuchInteraction", message)

    def test_path_to_non_interaction_class_raises(self):
        self.item.interaction = "nilpoint.models.Item"
        self.item.save()
        with self.assertRaises(UnresolvableInteraction) as ctx:
            self.item.get_interaction_class()
        self.assertIn("not an InteractiveItem subclass", str(ctx.exception))

    def test_options_are_copied_and_available(self):
        self.item.interaction = WotsitLever.dotted_path()
        self.item.interaction_options = {"turns": 4}
        self.item.save()
        interaction = self.item.get_interaction()
        self.assertEqual(interaction.options, {"turns": 4})
        # Mutating the interaction's copy must not touch the model's field.
        interaction.options["turns"] = 99
        self.item.refresh_from_db()
        self.assertEqual(self.item.interaction_options, {"turns": 4})

    def _lever_item(self):
        """An Item wired to WotsitLever, for the tests that need a class bound."""
        self.item.interaction = WotsitLever.dotted_path()
        self.item.save()
        return self.item.get_interaction()

    def test_get_action_and_unknown_action(self):
        interaction = self._lever_item()
        self.assertIsNone(interaction.get_action("nope"))
        interaction.actions = [Action("pull")]
        self.assertEqual(interaction.get_action("pull").name, "pull")

    def test_handle_without_behaviour_raises(self):
        interaction = self._lever_item()
        interaction.actions = [Action("twist")]
        with self.assertRaises(NotImplementedError) as ctx:
            interaction.handle(None, Action("twist"), None)
        self.assertIn("twist", str(ctx.exception))

    def test_describe_lists_actions(self):
        self.item.interaction = WotsitLever.dotted_path()
        self.item.save()
        self.assertEqual(
            [a["name"] for a in self.item.get_interaction().describe()],
            ["pull"],
        )
        described = self.item.describe_interaction()
        self.assertEqual(described["actions"], ["pull"])
        self.assertEqual(described["labels"], {"pull": "Pull"})

    def test_module_defined_action(self):
        """A class can build its action list however it likes, including
        reading the asset's options."""
        self.item.interaction = MessyActionInteraction.dotted_path()
        self.item.interaction_options = {"verb": "whack"}
        self.item.save()
        interaction = self.item.get_interaction()
        actions = interaction.get_actions()
        self.assertEqual([a.name for a in actions], ["whack"])
        self.assertEqual(actions[0].display_label, "Whack")

    def test_action_level_can_and_handle_callables(self):
        """The short form: behaviour attached to a single Action, with no
        handle() or can() method on the class at all."""
        self.item.interaction = CountingInteraction.dotted_path()
        self.item.save()
        interaction = self.item.get_interaction()

        self.assertTrue(interaction.can(None, interaction.get_action("tap")))

        interaction.get_action("tap").handle(None, None)
        self.assertEqual(interaction.taps, 1)

    def test_available_actions_filters_by_can(self):
        interaction = self._lever_item()
        interaction.can = lambda instance, action: action.name == "pull"
        self.assertEqual(
            [a.name for a in interaction.available_actions(None)], ["pull"]
        )

    def test_available_actions_survives_a_broken_gate(self):
        """A `can` that raises must hide the button, not take the page down."""
        interaction = self._lever_item()

        def explode(instance, action):
            raise RuntimeError("boom")

        interaction.can = explode
        self.assertEqual(interaction.available_actions(None), [])


class InteractionLookupTests(TestCase):
    """get_interaction() and friends map any record to its behaviour."""

    def setUp(self):
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        self.item = models.Item.objects.create(
            asset_id="wotsit",
            name="A Wotsit",
            description="A wotsit",
            game=self.game,
            interaction=WotsitLever.dotted_path(),
        )
        self.pc = PlayerCharacter.objects.create(
            handle="hero",
            player=Player.objects.create(
                user=User.objects.create_user(
                    username=f"u_{uuid4().hex[:6]}", password="pw"
                )
            ),
            game=self.game,
        )
        self.location = models.Location.objects.create(
            asset_id="start",
            name="Start",
            description="",
            game=self.game,
            initial=True,
        )
        self.location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

    def test_get_interaction_from_asset(self):
        interaction = get_interaction(self.item, pc=self.pc)
        self.assertIsInstance(interaction, WotsitLever)
        self.assertIs(interaction.pc, self.pc)
        self.assertIsNone(interaction.instance)

    def test_get_interaction_from_location_item_binds_instance(self):
        interaction = get_interaction(self.location_item)
        self.assertIsInstance(interaction, WotsitLever)
        self.assertIs(interaction.instance, self.location_item)
        self.assertIs(interaction.item, self.item)
        self.assertIs(interaction.pc, self.pc)

    def test_get_interaction_from_none(self):
        self.assertIsNone(get_interaction(None))

    def test_get_interaction_from_unrelated_record(self):
        self.assertIsNone(get_interaction(self.location))

    def test_get_interaction_asset(self):
        self.assertIs(get_interaction_asset(self.item), self.item)
        self.assertIs(get_interaction_asset(self.location_item), self.item)
        self.assertIsNone(get_interaction_asset(self.location))

    def test_holder_type_is_wire_name(self):
        self.assertEqual(holder_type(self.location_item), "location_item")
        self.assertEqual(holder_type(self.item), "item")

    def test_location_item_is_not_carried(self):
        self.assertFalse(self.location_item.is_in_inventory)

    def test_inventory_item_is_carried(self):
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        self.assertTrue(inventory_item.is_carried)
        self.assertTrue(inventory_item.is_in_inventory)

    def test_holder_type_works_on_the_model_class(self):
        """holder_type() accepts a class as well as an instance, since the
        view resolves names to models before it has anything to inspect."""
        self.assertEqual(holder_type(models.LocationItem), "location_item")
        self.assertEqual(holder_type(models.InventoryItem), "inventory_item")


class InteractActionsTagTests(TestCase):
    """The tag renders one button per action the `can` rule allows."""

    def setUp(self):
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        self.item = models.Item.objects.create(
            asset_id="wotsit",
            name="A Wotsit",
            description="A wotsit",
            game=self.game,
            interaction=SqueezeWotsit.dotted_path(),
        )
        self.user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        self.pc = PlayerCharacter.objects.create(
            handle="hero", player=Player.objects.create(user=self.user), game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id="start", name="Start", description="", game=self.game, initial=True
        )
        self.location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        self.factory = RequestFactory()

    def _render(self, instance, **kwargs):
        request = self.factory.get("/")
        request.user = self.user
        return render_to_string(
            "nilpoint/tags/interact_actions.jinja2",
            nilpoint_interact_actions({"game": self.game}, instance, **kwargs),
        )

    def test_renders_allowed_actions(self):
        self.location_item.item_state.put("charges", 3)
        content = self._render(self.location_item)
        self.assertIn("Squeeze", content)
        self.assertIn('"action": "squeeze"', content)
        self.assertIn('"phase": "show"', content)
        self.assertIn('"target_type": "location_item"', content)

    def test_omits_actions_the_can_rule_refuses(self):
        self.location_item.item_state.put("charges", 0)
        content = self._render(self.location_item)
        self.assertIn("No actions available", content)
        self.assertNotIn('"action": "squeeze"', content)

    def test_renders_nothing_for_an_item_with_no_interaction(self):
        plain = models.Item.objects.create(
            asset_id="plain", name="Plain", description="", game=self.game
        )
        plain_location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=plain
        )
        content = self._render(plain_location_item)
        self.assertIn("No actions available", content)

    def test_broken_interaction_does_not_raise(self):
        self.item.interaction = "nowhere.NoSuchThing"
        self.item.save()
        content = self._render(self.location_item)
        self.assertIn("No actions available", content)

    def test_without_a_game_in_context_renders_nothing(self):
        result = nilpoint_interact_actions({}, self.location_item)
        self.assertEqual(result["actions"], [])


class InteractionTargetResolutionTests(TestCase):
    """Which records the interact view will accept, and by what name.

    The view is written against the general notion of an interaction target
    rather than items specifically, so that a game can make anything
    interactive later without changes here. These tests pin down the mechanism
    using the models that exist today.
    """

    def test_both_item_record_types_are_targets(self):
        names = _get_interaction_target_names()
        self.assertIn("location_item", names)
        self.assertIn("inventory_item", names)

    def test_target_type_resolves_to_its_model(self):
        self.assertIs(
            _get_interaction_target_model("location_item"), models.LocationItem
        )
        self.assertIs(
            _get_interaction_target_model("inventory_item"), models.InventoryItem
        )

    def test_unknown_target_type_resolves_to_nothing(self):
        self.assertIsNone(_get_interaction_target_model("submarine"))

    def test_shared_assets_are_targets_too(self):
        """Anything with InteractiveMixin is interactable in its own right,
        not just the player-scoped records that point at one."""
        self.assertIn("item", _get_interaction_target_names())


class InteractionDispatchTests(TestCase):
    """The `interact` action running each phase against a real class."""

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        self.player = Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )
        self.pc = PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id="start", name="Start", description="", game=self.game, initial=True
        )
        self.pc.current_location = self.location
        self.pc.save()

        self.item = models.Item.objects.create(
            asset_id="wotsit",
            name="A Wotsit",
            description="A wotsit",
            game=self.game,
            interaction=SqueezeWotsit.dotted_path(),
        )
        self.location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        self.location_item.item_state.put("charges", 3)
        self.factory = RequestFactory()

    def _dispatch(self, instance, action, phase, **extra):
        request = self.factory.post(
            "/dispatch?action=interact",
            {
                "target_type": holder_type(instance),
                "object_id": instance.pk,
                "action": action,
                "phase": phase,
                **extra,
            },
        )
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)

        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_character = self.pc
        return view.handle_interact(request)

    def test_can_phase_allows(self):
        response = self._dispatch(self.location_item, "squeeze", "can")
        self.assertEqual(response.status_code, 200)
        self.assertIn('"allowed": true', response.content.decode())

    def test_can_phase_refuses(self):
        self.location_item.item_state.put("charges", 0)
        response = self._dispatch(self.location_item, "squeeze", "can")
        self.assertIn('"allowed": false', response.content.decode())

    def test_show_phase_renders_the_partial(self):
        response = self._dispatch(self.location_item, "squeeze", "show")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("SHOW PARTIAL RENDERED", content)
        # The partial gets the stable context keys to work with.
        self.assertIn("squeeze", content)
        self.assertIn("A Wotsit", content)
        self.assertIn("handle", content)
        self.assertIn("hero", content)

    def test_handle_phase_changes_state_and_rerenders(self):
        response = self._dispatch(self.location_item, "squeeze", "handle")
        self.assertEqual(response.status_code, 200)
        self.location_item.refresh_from_db()
        self.assertEqual(self.location_item.item_state.get("charges"), 2)
        self.assertIn(b"SHOW PARTIAL RENDERED", response.content)

    def test_handle_phase_is_gated_by_can(self):
        """A request that bypasses the buttons must still be refused."""
        self.location_item.item_state.put("charges", 0)
        response = self._dispatch(self.location_item, "squeeze", "handle")
        self.assertIn(b"Can't squeeze", response.content)
        self.location_item.refresh_from_db()
        self.assertEqual(self.location_item.item_state.get("charges"), 0)

    def test_handle_phase_returns_a_string_response_verbatim(self):
        self.item.interaction = StringResponseInteraction.dotted_path()
        self.item.save()
        response = self._dispatch(self.location_item, "shout", "handle")
        self.assertIn(b"the device whirs", response.content)

    def test_handle_phase_honours_a_returned_response(self):
        self.item.interaction = ResponseReturningInteraction.dotted_path()
        self.item.save()
        response = self._dispatch(self.location_item, "ping", "handle")
        self.assertIsInstance(response, HtmxTriggerResponse)
        self.assertEqual(response.content, b"pong")
        # The action's own trigger survives, rather than being replaced by the
        # framework's default refresh.
        self.assertIn("player_location_changed", response.htmx_triggers)

    def test_unknown_action_is_refused(self):
        response = self._dispatch(self.location_item, "explode", "handle")
        self.assertIn(b"has no action 'explode'", response.content)

    def test_item_with_no_interaction_is_refused(self):
        self.item.interaction = ""
        self.item.save()
        response = self._dispatch(self.location_item, "squeeze", "handle")
        self.assertIn(b"has no interactions", response.content)

    def test_invalid_phase_is_refused(self):
        response = self._dispatch(self.location_item, "squeeze", "wiggle")
        self.assertIn(b"Invalid phase", response.content)

    def test_missing_parameters_are_refused(self):
        request = self.factory.post("/dispatch?action=interact", {"phase": "show"})
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)
        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_character = self.pc
        response = view.handle_interact(request)
        self.assertIn(b"Missing required parameters", response.content)

    def test_cannot_interact_with_another_players_item(self):
        """Player-scoped rows are private, so another character's copy of the
        same item must not be reachable by id."""
        other_user = User.objects.create_user(
            username=f"o_{uuid4().hex[:6]}", password="pw"
        )
        other_pc = PlayerCharacter.objects.create(
            handle="other",
            player=Player.objects.create(user=other_user),
            game=self.game,
        )
        theirs = models.LocationItem.objects.create(
            location=self.location, pc=other_pc, item=self.item
        )
        response = self._dispatch(theirs, "squeeze", "handle")
        self.assertIn(b"Not found or not yours", response.content)

    def test_our_own_copy_of_the_same_item_still_works(self):
        """The mirror of the test above: ownership filtering must not stop a
        character interacting with their own copy of a shared Item."""
        response = self._dispatch(self.location_item, "squeeze", "handle")
        self.assertNotIn(b"Not found", response.content)
        self.location_item.refresh_from_db()
        self.assertEqual(self.location_item.item_state.get("charges"), 2)

    def test_cannot_interact_across_games(self):
        """The item must belong to the game the request is for."""
        other_game = models.Game.objects.create(
            instance_name="Other", instance_description="", nilpoint_slug="other-game"
        )
        foreign = models.Item.objects.create(
            asset_id="foreign",
            name="Foreign",
            description="",
            game=other_game,
            interaction=SqueezeWotsit.dotted_path(),
        )
        request = self.factory.post(
            "/dispatch?action=interact",
            {
                "target_type": "location_item",
                "object_id": models.LocationItem.objects.create(
                    location=self.location, pc=self.pc, item=foreign
                ).pk,
                "action": "squeeze",
                "phase": "handle",
            },
        )
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)
        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_character = self.pc
        response = view.handle_interact(request)
        self.assertIn(b"not part of this game", response.content)


class StringResponseInteraction(InteractiveItem):
    """handle() returns a string, which the view sends back verbatim."""

    show_partial = "nilpoint/test_interact_show.jinja2#test"
    actions = [Action("shout")]

    def handle(self, instance, action, request):
        instance.item_state.put("shouted", True)
        return "the device whirs"


class ResponseReturningInteraction(InteractiveItem):
    """handle() returns a response, which the view uses as-is."""

    actions = [Action("ping")]

    def handle(self, instance, action, request):
        response = HtmxTriggerResponse(content="pong", content_type="text/plain")
        response.add_trigger("player_location_changed")
        return response


class CheckInteractionsCommandTests(TestCase):
    """nilpoint_check_interactions reports assets whose class has moved."""

    def setUp(self):
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
        )

    def _run(self, **options):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("nilpoint_check_interactions", stdout=out, stderr=out, **options)
        return out.getvalue()

    def test_reports_ok_for_a_resolvable_interaction(self):
        models.Item.objects.create(
            asset_id="wotsit",
            name="A Wotsit",
            description="",
            game=self.game,
            interaction=WotsitLever.dotted_path(),
        )
        output = self._run(actions=True)
        self.assertIn("ok", output)
        self.assertIn("pull", output)

    def test_exits_nonzero_when_a_path_cannot_be_resolved(self):
        models.Item.objects.create(
            asset_id="broken",
            name="Broken",
            description="",
            game=self.game,
            interaction="nowhere.NoSuchInteraction",
        )
        with self.assertRaises(SystemExit):
            self._run()

    def test_groups_assets_sharing_one_class(self):
        for asset_id in ("one", "two"):
            models.Item.objects.create(
                asset_id=asset_id,
                name=asset_id,
                description="",
                game=self.game,
                interaction=WotsitLever.dotted_path(),
            )
        output = self._run()
        self.assertIn("2 asset(s): one, two", output)

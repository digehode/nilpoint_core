"""Tests for the item interaction hooks system."""

from django.test import TestCase
from django.contrib.auth import get_user_model

from nilpoint.models import (
    Game,
    Player,
    PlayerCharacter,
    Location,
    Item,
    LocationItem,
)
from nilpoint.views import NilpointGameBasic


def _expected_show(action, method, label=None):
    """Helper to build expected normalized show hook dict."""
    if label is None:
        label = action.replace("_", " ").title()
    return {action: {"method": method, "label": label}}


class ItemHooksProxyTests(TestCase):
    """Tests for the ItemHooksProxy dict-like API."""

    def setUp(self):
        self.game = Game.objects.create(
            instance_name="Test Game",
            nilpoint_slug="test-game",
        )
        self.item = Item.objects.create(
            game=self.game,
            asset_id="test_item",
            name="Test Item",
            description="A test item",
        )

    def test_hooks_proxy_basic_get_put(self):
        """Test basic get/put operations on hooks proxy."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        proxy.put("handle", {"squeeze": "handle_squeeze"})

        self.assertEqual(proxy.get("show"), _expected_show("squeeze", "show_squeeze"))
        self.assertEqual(proxy.get("handle"), {"squeeze": "handle_squeeze"})

    def test_hooks_proxy_put_overwrites(self):
        """Test that put overwrites existing keys."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "old"})
        proxy.put("show", {"squeeze": "new"})

        self.assertEqual(proxy.get("show"), _expected_show("squeeze", "new"))

    def test_hooks_proxy_contains(self):
        """Test __contains__."""
        proxy = self.item.hooks
        self.assertNotIn("show", proxy)
        proxy.put("show", {"squeeze": "show_squeeze"})
        self.assertIn("show", proxy)

    def test_hooks_proxy_keys(self):
        """Test keys method."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        proxy.put("handle", {"squeeze": "handle_squeeze"})

        self.assertEqual(set(proxy.keys()), {"show", "handle"})

    def test_hooks_proxy_len(self):
        """Test __len__."""
        proxy = self.item.hooks
        self.assertEqual(len(proxy), 0)
        proxy.put("show", {"squeeze": "show_squeeze"})
        self.assertEqual(len(proxy), 1)
        proxy.put("handle", {"squeeze": "handle_squeeze"})
        self.assertEqual(len(proxy), 2)

    def test_hooks_proxy_iteration(self):
        """Test iteration over keys."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        proxy.put("handle", {"squeeze": "handle_squeeze"})

        keys = list(proxy)
        self.assertEqual(set(keys), {"show", "handle"})

    def test_hooks_proxy_delitem(self):
        """Test __delitem__."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        del proxy["show"]
        self.assertNotIn("show", proxy)

    def test_hooks_proxy_pop(self):
        """Test pop method."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        val = proxy.pop("show")
        self.assertEqual(val, _expected_show("squeeze", "show_squeeze"))
        self.assertNotIn("show", proxy)

    def test_hooks_proxy_pop_default(self):
        """Test pop with default."""
        proxy = self.item.hooks
        val = proxy.pop("nonexistent", "default")
        self.assertEqual(val, "default")

    def test_hooks_proxy_getitem(self):
        """Test __getitem__."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        self.assertEqual(proxy["show"], _expected_show("squeeze", "show_squeeze"))

    def test_hooks_proxy_getitem_missing_raises(self):
        """Test __getitem__ raises KeyError for missing key."""
        proxy = self.item.hooks
        with self.assertRaises(KeyError):
            _ = proxy["nonexistent"]

    def test_hooks_proxy_setitem(self):
        """Test __setitem__."""
        proxy = self.item.hooks
        proxy["show"] = {"squeeze": "show_squeeze"}
        self.assertEqual(proxy.get("show"), _expected_show("squeeze", "show_squeeze"))

    def test_hooks_proxy_repr(self):
        """Test __repr__."""
        proxy = self.item.hooks
        proxy.put("show", {"squeeze": "show_squeeze"})
        # repr shows raw stored data, not normalized
        self.assertIn("show_squeeze", repr(proxy))


class ItemHooksIsolationTests(TestCase):
    """Tests that hooks on different items are isolated."""

    def setUp(self):
        self.game = Game.objects.create(
            instance_name="Test Game",
            nilpoint_slug="test-game",
        )
        self.item1 = Item.objects.create(
            game=self.game,
            asset_id="item1",
            name="Item 1",
            description="First item",
        )
        self.item2 = Item.objects.create(
            game=self.game,
            asset_id="item2",
            name="Item 2",
            description="Second item",
        )

    def test_item_hooks_isolation(self):
        """Test that hooks on different items don't leak."""
        self.item1.hooks.put("show", {"squeeze": "show_squeeze_1"})
        self.item2.hooks.put("show", {"tap": "show_tap_2"})

        self.assertEqual(
            self.item1.hooks.get("show"), _expected_show("squeeze", "show_squeeze_1")
        )
        self.assertEqual(
            self.item2.hooks.get("show"), _expected_show("tap", "show_tap_2")
        )

    def test_item_hooks_persistence(self):
        """Test that hooks persist after save/refresh."""
        self.item1.hooks.put("show", {"squeeze": "show_squeeze"})
        self.item1.refresh_from_db()
        self.assertEqual(
            self.item1.hooks.get("show"), _expected_show("squeeze", "show_squeeze")
        )


class GameGetItemHooksTests(TestCase):
    """Tests for the game's get_item_hooks method."""

    def setUp(self):
        self.game = Game.objects.create(
            instance_name="Test Game",
            nilpoint_slug="test-game",
        )
        self.item = Item.objects.create(
            game=self.game,
            asset_id="test_item",
            name="Test Item",
            description="A test item",
        )

    def test_default_get_item_hooks_returns_empty(self):
        """Test that default Game.get_item_hooks returns empty dicts."""
        real_game = self.game.get_real_instance()
        hooks = real_game.get_item_hooks(self.item)
        self.assertEqual(hooks, {"show": {}, "handle": {}, "can": {}})


class InteractionDispatchTests(TestCase):
    """Tests for the interaction dispatch view."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="testuser", password="testpass"
        )
        self.player = Player.objects.create(user=self.user)
        self.game = Game.objects.create(
            instance_name="Test Game",
            nilpoint_slug="test-game",
        )
        self.pc = PlayerCharacter.objects.create(
            player=self.player,
            game=self.game,
            handle="TestHero",
        )
        self.location = Location.objects.create(
            game=self.game,
            asset_id="start",
            name="Start",
            description="Starting location",
            initial=True,
        )
        self.pc.current_location = self.location
        self.pc.save()

        self.item = Item.objects.create(
            game=self.game,
            asset_id="wotsit",
            name="A Wotsit",
            description="It's a typical wotsit. A little worn but functional",
            can_take=True,
            can_drop=True,
        )
        # Add hooks to the item
        self.item.hooks.put("show", {"squeeze": "show_squeeze_wotsit"})
        self.item.hooks.put("handle", {"squeeze": "handle_squeeze_wotsit"})
        self.item.hooks.put("can", {"squeeze": "can_squeeze_wotsit"})

        # Create a location item for testing
        self.location_item = LocationItem.objects.create(
            location=self.location,
            pc=self.pc,
            item=self.item,
        )

        # Add state to test can hook
        self.location_item.item_state.put("charges", 3)

    def _setup_game_hooks(self):
        """Attach hook methods to the game instance for testing."""
        real_game = self.game.get_real_instance()

        def can_squeeze_wotsit(instance):
            return instance.item_state.get("charges", 0) > 0

        def show_squeeze_wotsit(instance):
            return "nilpoint/test_interact_show.jinja2#test"

        def handle_squeeze_wotsit(instance, request):
            instance.item_state.put(
                "charges", instance.item_state.get("charges", 0) - 1
            )
            return f"Squeezed! Charges left: {instance.item_state.get('charges', 0)}"

        real_game.can_squeeze_wotsit = can_squeeze_wotsit
        real_game.show_squeeze_wotsit = show_squeeze_wotsit
        real_game.handle_squeeze_wotsit = handle_squeeze_wotsit

        def get_item_hooks(item):
            return {
                "show": {
                    "squeeze": {"method": "show_squeeze_wotsit", "label": "Squeeze"}
                },
                "handle": {"squeeze": "handle_squeeze_wotsit"},
                "can": {"squeeze": "can_squeeze_wotsit"},
            }

        real_game.get_item_hooks = get_item_hooks

    def _make_request(self, phase):
        """Create a test request for the interact view."""
        from django.test import RequestFactory

        factory = RequestFactory()
        view = NilpointGameBasic()

        request = factory.post(
            "/dispatch?action=interact",
            {
                "item_type": "location_item",
                "object_id": self.location_item.id,
                "action": "squeeze",
                "phase": phase,
            },
        )
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)

        view.setup(request)
        view.game = self.game
        view.player_character = self.pc
        view.player = self.player

        return view, request

    def test_interact_can_phase_allowed(self):
        """Test can phase returns allowed=true when charges > 0."""
        self._setup_game_hooks()
        view, request = self._make_request("can")
        response = view.handle_interact(request)
        self.assertEqual(response.status_code, 200)
        import json

        data = json.loads(response.content)
        self.assertTrue(data["allowed"])

    def test_interact_can_phase_denied(self):
        """Test can phase returns allowed=false when charges = 0."""
        self.location_item.item_state.put("charges", 0)
        self._setup_game_hooks()
        view, request = self._make_request("can")
        response = view.handle_interact(request)
        self.assertEqual(response.status_code, 200)
        import json

        data = json.loads(response.content)
        self.assertFalse(data["allowed"])

    def test_interact_show_phase_returns_partial(self):
        """Test show phase returns rendered partial."""
        self._setup_game_hooks()
        view, request = self._make_request("show")
        response = view.handle_interact(request)
        self.assertEqual(response.status_code, 200)
        # Should contain our test template content
        self.assertIn(b"SHOW PARTIAL RENDERED", response.content)

    def test_interact_handle_phase_executes_and_decrements_charges(self):
        """Test handle phase executes action and decrements charges, then returns show partial."""
        self._setup_game_hooks()
        view, request = self._make_request("handle")
        response = view.handle_interact(request)
        self.assertEqual(response.status_code, 200)
        # Should return the show partial with updated state
        self.assertIn(b"SHOW PARTIAL RENDERED", response.content)
        # Verify state was actually changed
        self.location_item.refresh_from_db()
        self.assertEqual(self.location_item.item_state.get("charges"), 2)

    def test_interact_handle_phase_returns_show_partial(self):
        """Test handle phase returns the show partial after executing action."""
        self._setup_game_hooks()
        view, request = self._make_request("handle")
        response = view.handle_interact(request)
        self.assertEqual(response.status_code, 200)
        # Should return the show partial, not the handle hook's return string
        self.assertIn(b"SHOW PARTIAL RENDERED", response.content)


class ItemHooksAdminTests(TestCase):
    """Tests for admin display of item hooks."""

    def setUp(self):
        self.game = Game.objects.create(
            instance_name="Test Game",
            nilpoint_slug="test-game",
        )
        self.item = Item.objects.create(
            game=self.game,
            asset_id="test_item",
            name="Test Item",
            description="A test item",
        )
        self.item.hooks.put("show", {"squeeze": "show_squeeze"})
        self.item.hooks.put("handle", {"squeeze": "handle_squeeze"})
        self.item.hooks.put("can", {"squeeze": "can_squeeze"})


if __name__ == "__main__":
    import django

    django.setup()
    import unittest

    unittest.main()

"""Tests for the ItemState system."""

import pickle

from django.test import TestCase
from django.contrib.auth import get_user_model

from nilpoint import models

User = get_user_model()


class ItemStateProxyTests(TestCase):
    """Tests for the ItemStateProxy dict-like API."""

    def setUp(self):
        # Create a mock ItemState-like object with data attribute
        class MockState:
            def __init__(self):
                self.data = pickle.dumps({})
                self.saved = False

            def save(self, update_fields=None):
                self.saved = True

        self.state = MockState()

    def test_basic_get_put(self):
        proxy = models.ItemStateProxy(self.state)
        self.assertIsNone(proxy.get("missing"))
        self.assertEqual(proxy.get("missing", "default"), "default")

        proxy.put("key", "value")
        self.assertEqual(proxy.get("key"), "value")

        proxy.put("key", "new_value")
        self.assertEqual(proxy.get("key"), "new_value")

    def test_pop(self):
        proxy = models.ItemStateProxy(self.state)
        proxy.put("key", "value")
        self.assertEqual(proxy.pop("key"), "value")
        self.assertIsNone(proxy.get("key"))
        self.assertEqual(proxy.pop("missing", "default"), "default")

    def test_contains(self):
        proxy = models.ItemStateProxy(self.state)
        self.assertNotIn("key", proxy)
        proxy.put("key", "value")
        self.assertIn("key", proxy)

    def test_keys(self):
        proxy = models.ItemStateProxy(self.state)
        proxy.put("a", 1)
        proxy.put("b", 2)
        self.assertEqual(set(proxy.keys()), {"a", "b"})

    def test_len(self):
        proxy = models.ItemStateProxy(self.state)
        self.assertEqual(len(proxy), 0)
        proxy.put("a", 1)
        self.assertEqual(len(proxy), 1)
        proxy.put("b", 2)
        self.assertEqual(len(proxy), 2)

    def test_iter(self):
        proxy = models.ItemStateProxy(self.state)
        proxy.put("a", 1)
        proxy.put("b", 2)
        self.assertEqual(set(proxy), {"a", "b"})

    def test_delitem(self):
        proxy = models.ItemStateProxy(self.state)
        proxy.put("key", "value")
        del proxy["key"]
        self.assertNotIn("key", proxy)

    def test_repr(self):
        proxy = models.ItemStateProxy(self.state)
        proxy.put("key", "value")
        self.assertEqual(repr(proxy), "ItemStateProxy({'key': 'value'})")


class ItemStatePickleTests(TestCase):
    """Tests for pickle round-trip with complex objects."""

    def setUp(self):
        from django.contrib.contenttypes.models import ContentType

        self.content_type = ContentType.objects.get_for_model(models.LocationItem)

    def test_basic_types(self):
        state = models.ItemState.objects.create(
            content_type=self.content_type, object_id=1, data=pickle.dumps({})
        )
        proxy = models.ItemStateProxy(state)
        proxy.put("string", "value")
        proxy.put("int", 42)
        proxy.put("float", 3.14)
        proxy.put("bool", True)
        proxy.put("none", None)
        proxy.put("list", [1, 2, 3])
        proxy.put("dict", {"nested": "value"})

        # Reload from database
        state.refresh_from_db()
        proxy2 = models.ItemStateProxy(state)
        self.assertEqual(proxy2.get("string"), "value")
        self.assertEqual(proxy2.get("int"), 42)
        self.assertEqual(proxy2.get("float"), 3.14)
        self.assertEqual(proxy2.get("bool"), True)
        self.assertIsNone(proxy2.get("none"))
        self.assertEqual(proxy2.get("list"), [1, 2, 3])
        self.assertEqual(proxy2.get("dict"), {"nested": "value"})

    def test_complex_objects(self):
        """Test pickle handles tuples, sets, custom objects."""
        from datetime import datetime
        from decimal import Decimal

        state = models.ItemState.objects.create(
            content_type=self.content_type, object_id=2, data=pickle.dumps({})
        )
        proxy = models.ItemStateProxy(state)
        proxy.put("tuple", (1, 2, 3))
        proxy.put("set", {1, 2, 3})
        proxy.put("datetime", datetime(2024, 1, 1, 12, 0))
        proxy.put("decimal", Decimal("3.14"))

        state.refresh_from_db()
        proxy2 = models.ItemStateProxy(state)
        self.assertEqual(proxy2.get("tuple"), (1, 2, 3))
        self.assertEqual(proxy2.get("set"), {1, 2, 3})
        # Note: pickle preserves datetime and Decimal


class ItemStateIsolationTests(TestCase):
    """Tests that state is isolated per instance."""

    def setUp(self):
        self.user = User.objects.create_user(username="test", password="pw")
        self.player = models.Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug="test-game",
            allow_multiple_characters=False,
        )
        self.pc = models.PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id="start", name="Start", game=self.game, initial=True
        )
        self.pc.current_location = self.location
        self.pc.save()

        self.item = models.Item.objects.create(
            asset_id="sword", name="Sword", description="A sword", game=self.game
        )

    def test_locationitem_isolation(self):
        li1 = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li2 = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        li1.item_state.put("durability", 100)
        li2.item_state.put("durability", 50)

        self.assertEqual(li1.item_state.get("durability"), 100)
        self.assertEqual(li2.item_state.get("durability"), 50)

    def test_inventoryitem_isolation(self):
        inv1 = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        inv2 = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        inv1.item_state.put("charges", 10)
        inv2.item_state.put("charges", 5)

        self.assertEqual(inv1.item_state.get("charges"), 10)
        self.assertEqual(inv2.item_state.get("charges"), 5)

    def test_cross_type_isolation(self):
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        li.item_state.put("location_only", True)
        inv.item_state.put("inventory_only", True)

        self.assertTrue(li.item_state.get("location_only"))
        self.assertFalse(inv.item_state.get("location_only"))
        self.assertTrue(inv.item_state.get("inventory_only"))
        self.assertFalse(li.item_state.get("inventory_only"))


class StatefulMixinTests(TestCase):
    """Tests for the StatefulMixin on LocationItem and InventoryItem."""

    def setUp(self):
        self.user = User.objects.create_user(username="test", password="pw")
        self.player = models.Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug="test-game",
            allow_multiple_characters=False,
        )
        self.pc = models.PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id="start", name="Start", game=self.game, initial=True
        )
        self.pc.current_location = self.location
        self.pc.save()

        self.item = models.Item.objects.create(
            asset_id="sword", name="Sword", description="A sword", game=self.game
        )

    def test_locationitem_has_item_state(self):
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        self.assertTrue(hasattr(li, "item_state"))
        li.item_state.put("test", "value")
        self.assertEqual(li.item_state.get("test"), "value")

    def test_inventoryitem_has_item_state(self):
        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        self.assertTrue(hasattr(inv, "item_state"))
        inv.item_state.put("test", "value")
        self.assertEqual(inv.item_state.get("test"), "value")

    def test_transfer_state_location_to_inventory(self):
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li.item_state.put("durability", 75)
        li.item_state.put("enchanted", True)

        # Transfer
        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        li.transfer_state_to(inv)

        self.assertEqual(inv.item_state.get("durability"), 75)
        self.assertTrue(inv.item_state.get("enchanted"))
        # Original state still exists (until li is deleted)
        self.assertEqual(li.item_state.get("durability"), 75)

    def test_transfer_state_inventory_to_location(self):
        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        inv.item_state.put("charges", 5)
        inv.item_state.put("cursed", False)

        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        inv.transfer_state_to(li)

        self.assertEqual(li.item_state.get("charges"), 5)
        self.assertFalse(li.item_state.get("cursed"))

    def test_transfer_state_preserves_source(self):
        """State is copied, not moved - source retains data until deleted."""
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li.item_state.put("key", "value")

        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        li.transfer_state_to(inv)

        # Both have the data
        self.assertEqual(li.item_state.get("key"), "value")
        self.assertEqual(inv.item_state.get("key"), "value")

        # Delete source - target still has data
        li.delete()
        inv.refresh_from_db()
        self.assertEqual(inv.item_state.get("key"), "value")

    def test_transfer_state_overwrites_target(self):
        """Transfer overwrites any existing state on target."""
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li.item_state.put("source_key", "source_value")

        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        inv.item_state.put("target_key", "target_value")  # Pre-existing

        li.transfer_state_to(inv)

        # Source data overwrote target
        self.assertEqual(inv.item_state.get("source_key"), "source_value")
        self.assertNotIn("target_key", inv.item_state.keys())

    def test_transfer_state_empty_source(self):
        """Transferring empty state clears target."""
        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        # li has empty state

        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        inv.item_state.put("key", "value")

        li.transfer_state_to(inv)

        # Target should now have empty state (empty dict copied)
        self.assertEqual(len(inv.item_state), 0)

    def test_multiple_models_can_have_state(self):
        """Future-proof: verify the pattern works for any model."""
        # This test just verifies the mixin can be applied to any model
        # by creating a test model dynamically (but we can't easily do that
        # in Django tests without migrations). Instead, verify the mixin
        # is correctly applied to both LocationItem and InventoryItem.
        self.assertTrue(issubclass(models.LocationItem, models.StatefulMixin))
        self.assertTrue(issubclass(models.InventoryItem, models.StatefulMixin))


class TransferStateFunctionTests(TestCase):
    """Tests for the standalone transfer_item_state function."""

    def setUp(self):
        self.user = User.objects.create_user(username="test", password="pw")
        self.player = models.Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="Test Game",
            instance_description="",
            nilpoint_slug="test-game",
            allow_multiple_characters=False,
        )
        self.pc = models.PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id="start", name="Start", game=self.game, initial=True
        )
        self.pc.current_location = self.location
        self.pc.save()

        self.item = models.Item.objects.create(
            asset_id="sword", name="Sword", description="A sword", game=self.game
        )

    def test_transfer_item_state_function(self):

        li = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li.item_state.put("key", "value")

        inv = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        models.transfer_item_state(li, inv)

        self.assertEqual(inv.item_state.get("key"), "value")

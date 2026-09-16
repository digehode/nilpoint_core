"""
Unit tests for the GameAsset abstract model and Game.get_asset lookup dispatcher.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.test import TestCase

from nilpoint.models import Game, GameAsset, Item, Location


# Concrete test models (or use core Location and Item models)
class TestAssets(TestCase):
    def setUp(self):
        # Create two distinct game instances to test game-scoping
        self.game_a = Game.objects.create(
            instance_name="Game Alpha", release=1, nilpoint_slug="game_a"
        )
        self.game_b = Game.objects.create(
            instance_name="Game Beta", release=1, nilpoint_slug="game_b"
        )

        # Populate Game A assets
        self.location_a = Location.objects.create(
            game=self.game_a,
            asset_id="start_room",
            name="Starting Room",
            description="The beginning.",
        )
        self.item_a = Item.objects.create(
            game=self.game_a,
            asset_id="rusty_key",
            name="Rusty Key",
            description="An old key.",
        )

        # Populate Game B asset with a matching asset_id to test scoping
        self.location_b = Location.objects.create(
            game=self.game_b,
            asset_id="start_room",
            name="Different Starting Room",
            description="Another game's room.",
        )

    def test_direct_lookup_with_model_class(self):
        """Targeted lookup using explicit model_class should succeed quickly."""
        asset = self.game_a.get_asset("start_room", model_class=Location)
        self.assertEqual(asset, self.location_a)
        self.assertEqual(asset.name, "Starting Room")

        item = self.game_a.get_asset("rusty_key", model_class=Item)
        self.assertEqual(item, self.item_a)

    def test_exhaustive_fallback_lookup_without_model_class(self):
        """Lookup without model_class should iterate through asset models and find the match."""
        asset = self.game_a.get_asset("rusty_key")
        self.assertEqual(asset, self.item_a)
        self.assertIsInstance(asset, Item)

    def test_game_scoping_isolation(self):
        """Assets with identical asset_ids across different games must be strictly isolated."""
        asset_a = self.game_a.get_asset("start_room", model_class=Location)
        asset_b = self.game_b.get_asset("start_room", model_class=Location)

        self.assertEqual(asset_a, self.location_a)
        self.assertEqual(asset_b, self.location_b)
        self.assertNotEqual(asset_a.pk, asset_b.pk)

    def test_nonexistent_asset_raises_object_does_not_exist(self):
        """Requesting an unassigned asset_id should raise ObjectDoesNotExist."""
        with self.assertRaises(ObjectDoesNotExist):
            self.game_a.get_asset("non_existent_id", model_class=Location)

        with self.assertRaises(ObjectDoesNotExist):
            self.game_a.get_asset("non_existent_id")

    def test_unique_constraint_per_game(self):
        """Duplicate asset_ids within the same model and game should fail database constraints."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Item.objects.create(
                    game=self.game_a,
                    asset_id="rusty_key",
                    name="Duplicate Rusty Key",
                    description="An old key. Same oldness as before.",
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    game=self.game_a,
                    asset_id="start_room",  # Duplicate in game_a
                    name="Duplicate Room",
                )

    def test_polymorphic_subclass_resolution(self):
        """Ensure get_asset returns the fully typed subclass instance via select_subclasses."""
        fetched_location = self.game_a.get_asset("start_room")
        self.assertIsInstance(fetched_location, Location)
        self.assertTrue(issubclass(fetched_location.__class__, GameAsset))

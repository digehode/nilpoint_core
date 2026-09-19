from uuid import uuid4

from django.test import TestCase
from django.contrib.auth import get_user_model

from nilpoint import models

User = get_user_model()


class PlayerScopedQueryTests(TestCase):
    """Per-character scoping of player-scoped state rows.

    The core regression: LocationItem rows exist per character, so a
    character's view of a location must only include their own rows,
    even when another character is at the same location with the same
    item.
    """

    def setUp(self):
        # Two players, each with a character, both in the same game
        # and at the same location.
        self.user_a = User.objects.create_user(
            username=f"pa_{uuid4().hex[:6]}", password="pw"
        )
        self.user_b = User.objects.create_user(
            username=f"pb_{uuid4().hex[:6]}", password="pw"
        )
        self.player_a = models.Player.objects.create(user=self.user_a)
        self.player_b = models.Player.objects.create(user=self.user_b)

        self.game = models.Game.objects.create(
            instance_name=f"Game_{uuid4().hex[:6]}",
            instance_description="desc",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
            allow_multiple_characters=False,
        )

        self.pc_a = models.PlayerCharacter.objects.create(
            handle="char_a", player=self.player_a, game=self.game
        )
        self.pc_b = models.PlayerCharacter.objects.create(
            handle="char_b", player=self.player_b, game=self.game
        )

        self.location = models.Location.objects.create(
            asset_id=f"start_{uuid4().hex[:6]}",
            name="Start",
            description="",
            game=self.game,
            initial=True,
        )
        self.pc_a.current_location = self.location
        self.pc_a.save()
        self.pc_b.current_location = self.location
        self.pc_b.save()

        self.item = models.Item.objects.create(
            asset_id=f"it_{uuid4().hex[:6]}",
            name="Wotsit",
            description="desc",
            game=self.game,
        )

        # Both characters have the same item at the same location
        self.li_a = models.LocationItem.objects.create(
            location=self.location, pc=self.pc_a, item=self.item
        )
        self.li_b = models.LocationItem.objects.create(
            location=self.location, pc=self.pc_b, item=self.item
        )

        # Only character A has the item in their inventory
        self.inv_a = models.InventoryItem.objects.create(pc=self.pc_a, item=self.item)

    def test_for_character_filters_location_items(self):
        rows = list(models.LocationItem.objects.for_character(self.pc_a))
        self.assertEqual(rows, [self.li_a])
        rows = list(models.LocationItem.objects.for_character(self.pc_b))
        self.assertEqual(rows, [self.li_b])

    def test_items_at_defaults_to_current_location_and_is_scoped(self):
        # The regression: pc_a must NOT see pc_b's row for the same
        # item at the same location.
        rows = list(self.pc_a.items_at())
        self.assertEqual(rows, [self.li_a])
        self.assertNotIn(self.li_b, rows)
        self.assertEqual(rows[0].item, self.item)

    def test_items_at_with_explicit_location(self):
        other = models.Location.objects.create(
            asset_id=f"other_{uuid4().hex[:6]}",
            name="Elsewhere",
            description="",
            game=self.game,
            initial=False,
        )
        li_other = models.LocationItem.objects.create(
            location=other, pc=self.pc_a, item=self.item
        )

        self.assertEqual(list(self.pc_a.items_at(other)), [li_other])
        # Current-location default is unaffected
        self.assertEqual(list(self.pc_a.items_at()), [self.li_a])

    def test_items_at_without_current_location_is_empty(self):
        pc = models.PlayerCharacter.objects.create(
            handle="wanderer", player=self.player_a, game=self.game
        )
        self.assertEqual(list(pc.items_at()), [])

    def test_inventory_items_is_scoped(self):
        rows = list(self.pc_a.inventory_items())
        self.assertEqual(rows, [self.inv_a])
        self.assertEqual(rows[0].item, self.item)
        self.assertEqual(list(self.pc_b.inventory_items()), [])

    def test_reverse_related_names_unchanged(self):
        # The related_names are part of the existing public API and must
        # survive adopting the PlayerScoped base.
        self.assertEqual(list(self.pc_a.location_items.all()), [self.li_a])
        self.assertEqual(list(self.pc_a.inventory.all()), [self.inv_a])

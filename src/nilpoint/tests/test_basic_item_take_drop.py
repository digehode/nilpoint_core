"""
Tests for the basic item take/drop functionality.

Tests cover:
- Valid take/drop operations
- Invalid IDs (non-existent, wrong type)
- Items not held by the user
- Items in wrong location
- Items in wrong game
- LocationItem/InventoryItem not belonging to the user
- can_take=False blocks take
- can_drop=False blocks drop
- No PC selected
- GET requests should fail (POST required)
- HTMX triggers are properly returned
"""

from uuid import uuid4

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.db import transaction

from nilpoint import models
from nilpoint.views import NilpointGameBasic

User = get_user_model()


class ItemTakeDropTests(TestCase):
    """Tests for take/drop item handlers."""

    def setUp(self):
        # Create test user, player, game, PC
        self.user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        self.player = models.Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name=f"Game_{uuid4().hex[:6]}",
            instance_description="desc",
            nilpoint_slug=f"g_{uuid4().hex[:6]}",
            allow_multiple_characters=False,
        )
        self.game._game_type = "cypherpunkgame"
        self.game.save()

        self.pc = models.PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.location = models.Location.objects.create(
            asset_id=f"start_{uuid4().hex[:6]}",
            name="Start",
            description="",
            game=self.game,
            initial=True,
        )
        self.pc.current_location = self.location
        self.pc.save()

        # Create a second location for "wrong location" tests
        self.other_location = models.Location.objects.create(
            asset_id=f"other_{uuid4().hex[:6]}",
            name="Elsewhere",
            description="",
            game=self.game,
            initial=False,
        )

        # Create another user/PC for "not yours" tests
        self.user2 = User.objects.create_user(
            username=f"u2_{uuid4().hex[:6]}", password="pw"
        )
        self.player2 = models.Player.objects.create(user=self.user2)
        self.pc2 = models.PlayerCharacter.objects.create(
            handle="hero2", player=self.player2, game=self.game
        )
        self.pc2.current_location = self.location
        self.pc2.save()

        # Create a second game for cross-game tests
        self.game2 = models.Game.objects.create(
            instance_name=f"Game2_{uuid4().hex[:6]}",
            instance_description="desc",
            nilpoint_slug=f"g2_{uuid4().hex[:6]}",
            allow_multiple_characters=False,
        )
        self.game2._game_type = "cypherpunkgame"
        self.game2.save()

        # Create item that can be taken and dropped (default)
        self.item = models.Item.objects.create(
            asset_id=f"it_{uuid4().hex[:6]}",
            name="Sword",
            description="A sharp blade",
            game=self.game,
            can_take=True,
            can_drop=True,
        )

        # Item that cannot be taken
        self.item_notake = models.Item.objects.create(
            asset_id=f"it_nt_{uuid4().hex[:6]}",
            name="Heavy Rock",
            description="Too heavy to take",
            game=self.game,
            can_take=False,
            can_drop=True,
        )

        # Item that cannot be dropped
        self.item_nodrop = models.Item.objects.create(
            asset_id=f"it_nd_{uuid4().hex[:6]}",
            name="Cursed Amulet",
            description="Cannot be dropped",
            game=self.game,
            can_take=True,
            can_drop=False,
        )

        # Item in another game
        self.item_other_game = models.Item.objects.create(
            asset_id=f"it_og_{uuid4().hex[:6]}",
            name="Foreign Item",
            description="From another game",
            game=self.game2,
            can_take=True,
            can_drop=True,
        )

    def _post_request(self, action, data, user=None, pc=None):
        """Helper to make a POST request to the view.

        Action goes in query string, other data in POST body.
        """
        if user is None:
            user = self.user
        if pc is None:
            pc = self.pc
        rf = RequestFactory()
        request = rf.post(f"/?action={action}", data)
        request.user = user
        request.COOKIES["pc"] = str(pc.id)
        view = NilpointGameBasic()
        return view.post(request, nilpoint_slug=self.game.nilpoint_slug)

    def _get_request(self, action, data, user=None, pc=None):
        """Helper to make a GET request to the view (should fail).

        Action goes in query string, other data in GET params.
        """
        if user is None:
            user = self.user
        if pc is None:
            pc = self.pc
        rf = RequestFactory()
        # For GET, put everything in query string via data dict
        full_data = {"action": action, **data}
        request = rf.get("/", full_data)
        request.user = user
        request.COOKIES["pc"] = str(pc.id)
        view = NilpointGameBasic()
        return view.get(request, nilpoint_slug=self.game.nilpoint_slug)

    # ===== Valid take/drop =====

    def test_take_item_success(self):
        """Taking a valid LocationItem moves it to inventory."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        response = self._post_request("take_item", {"location_item": location_item.id})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Took Sword", response.content.decode())

        # Check inventory now has the item
        inv_items = list(self.pc.inventory_items())
        self.assertEqual(len(inv_items), 1)
        self.assertEqual(inv_items[0].item, self.item)

        # Check location item is gone
        loc_items = list(self.pc.items_at())
        self.assertEqual(len(loc_items), 0)

    def test_drop_item_success(self):
        """Dropping a valid InventoryItem moves it to current location."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Dropped Sword", response.content.decode())

        # Check location now has the item
        loc_items = list(self.pc.items_at())
        self.assertEqual(len(loc_items), 1)
        self.assertEqual(loc_items[0].item, self.item)
        self.assertEqual(loc_items[0].location, self.location)

        # Check inventory is empty
        inv_items = list(self.pc.inventory_items())
        self.assertEqual(len(inv_items), 0)

    def test_take_drop_cycle(self):
        """Take then drop returns item to original location."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        # Take
        response = self._post_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response.status_code, 200)

        # Drop
        inv_item = self.pc.inventory_items().first()
        response = self._post_request("drop_item", {"inventory_item": inv_item.id})
        self.assertEqual(response.status_code, 200)

        # Item back at original location
        loc_items = list(self.pc.items_at())
        self.assertEqual(len(loc_items), 1)
        self.assertEqual(loc_items[0].location, self.location)

    # ===== HTMX Triggers =====

    def test_take_returns_player_location_changed_trigger(self):
        """Take response includes player_location_changed trigger."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        triggers = response.get("HX-Trigger", "")
        self.assertIn("player_location_changed", triggers)

    def test_drop_returns_player_location_changed_trigger(self):
        """Drop response includes player_location_changed trigger."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )
        triggers = response.get("HX-Trigger", "")
        self.assertIn("player_location_changed", triggers)

    # ===== POST required =====

    def test_take_get_request_fails(self):
        """GET request to take_item returns error."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        response = self._get_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("POST required", response.content.decode())

    def test_drop_get_request_fails(self):
        """GET request to drop_item returns error."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        response = self._get_request("drop_item", {"inventory_item": inventory_item.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("POST required", response.content.decode())

    # ===== Missing/invalid parameters =====

    def test_take_missing_location_item_param(self):
        """Missing location_item parameter returns error."""
        response = self._post_request("take_item", {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("No location_item given", response.content.decode())

    def test_drop_missing_inventory_item_param(self):
        """Missing inventory_item parameter returns error."""
        response = self._post_request("drop_item", {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("No inventory_item given", response.content.decode())

    def test_take_invalid_location_item_id(self):
        """Non-integer location_item ID returns error."""
        response = self._post_request("take_item", {"location_item": "not-a-number"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid location_item id", response.content.decode())

    def test_drop_invalid_inventory_item_id(self):
        """Non-integer inventory_item ID returns error."""
        response = self._post_request("drop_item", {"inventory_item": "not-a-number"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid inventory_item id", response.content.decode())

    def test_take_nonexistent_location_item(self):
        """Non-existent LocationItem ID returns error."""
        response = self._post_request("take_item", {"location_item": 999999})
        self.assertEqual(response.status_code, 200)
        self.assertIn("not found or not yours", response.content.decode())

    def test_drop_nonexistent_inventory_item(self):
        """Non-existent InventoryItem ID returns error."""
        response = self._post_request("drop_item", {"inventory_item": 999999})
        self.assertEqual(response.status_code, 200)
        self.assertIn("not found or not yours", response.content.decode())

    # ===== Ownership checks =====

    def test_take_another_players_location_item(self):
        """Cannot take another player's LocationItem."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc2, item=self.item
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("not found or not yours", response.content.decode())

        # Original owner still has it
        loc_items = list(self.pc2.items_at())
        self.assertEqual(len(loc_items), 1)

    def test_drop_another_players_inventory_item(self):
        """Cannot drop another player's InventoryItem."""
        inventory_item = models.InventoryItem.objects.create(
            pc=self.pc2, item=self.item
        )

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("not found or not yours", response.content.decode())

        # Original owner still has it
        inv_items = list(self.pc2.inventory_items())
        self.assertEqual(len(inv_items), 1)

    # ===== Location checks =====

    def test_take_item_at_wrong_location(self):
        """Cannot take item that's at a different location than the player."""
        location_item = models.LocationItem.objects.create(
            location=self.other_location, pc=self.pc, item=self.item
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("not at your current location", response.content.decode())

        # Item still at other location
        loc_items = models.LocationItem.objects.filter(id=location_item.id)
        self.assertTrue(loc_items.exists())

    def test_drop_without_current_location(self):
        """Cannot drop if player has no current location."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        # Remove player's location
        with transaction.atomic():
            sid = transaction.savepoint()
            try:
                self.pc.current_location = None
                self.pc.save()

                response = self._post_request(
                    "drop_item", {"inventory_item": inventory_item.id}
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("not at a location", response.content.decode())
            finally:
                transaction.savepoint_rollback(sid)

    # ===== can_take / can_drop checks =====

    def test_take_item_with_can_take_false(self):
        """Cannot take item with can_take=False."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item_notake
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("cannot be taken", response.content.decode())

        # Item still at location
        loc_items = list(self.pc.items_at())
        self.assertEqual(len(loc_items), 1)

    def test_drop_item_with_can_drop_false(self):
        """Cannot drop item with can_drop=False."""
        inventory_item = models.InventoryItem.objects.create(
            pc=self.pc, item=self.item_nodrop
        )

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("cannot be dropped", response.content.decode())

        # Item still in inventory
        inv_items = list(self.pc.inventory_items())
        self.assertEqual(len(inv_items), 1)

    # ===== Cross-game checks =====

    def test_take_item_from_other_game(self):
        """Cannot take LocationItem for item from different game."""
        # Create location item with item from other game
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item_other_game
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        # The view checks that the item belongs to the current game
        self.assertEqual(response.status_code, 200)
        self.assertIn("Item is not part of this game", response.content.decode())

    def test_drop_item_from_other_game(self):
        """Cannot drop InventoryItem for item from different game."""
        inventory_item = models.InventoryItem.objects.create(
            pc=self.pc, item=self.item_other_game
        )

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Item is not part of this game", response.content.decode())

    # ===== No PC selected =====

    def test_take_with_no_pc(self):
        """Take fails when no PC is selected."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        rf = RequestFactory()
        request = rf.post("/?action=take_item", {"location_item": location_item.id})
        request.user = self.user
        # No PC cookie
        view = NilpointGameBasic()
        response = view.post(request, nilpoint_slug=self.game.nilpoint_slug)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No player character selected", response.content.decode())

    def test_drop_with_no_pc(self):
        """Drop fails when no PC is selected."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        rf = RequestFactory()
        request = rf.post("/?action=drop_item", {"inventory_item": inventory_item.id})
        request.user = self.user
        # No PC cookie
        view = NilpointGameBasic()
        response = view.post(request, nilpoint_slug=self.game.nilpoint_slug)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No player character selected", response.content.decode())

    # ===== Response content type =====

    def test_take_returns_text_plain(self):
        """Take response has text/plain content type."""
        location_item = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )

        response = self._post_request("take_item", {"location_item": location_item.id})
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_drop_returns_text_plain(self):
        """Drop response has text/plain content type."""
        inventory_item = models.InventoryItem.objects.create(pc=self.pc, item=self.item)

        response = self._post_request(
            "drop_item", {"inventory_item": inventory_item.id}
        )
        self.assertEqual(response["Content-Type"], "text/plain")

    # ===== Multiple items =====

    def test_take_multiple_items_independently(self):
        """Multiple items can be taken independently."""
        item2 = models.Item.objects.create(
            asset_id=f"it2_{uuid4().hex[:6]}",
            name="Shield",
            description="A shield",
            game=self.game,
            can_take=True,
            can_drop=True,
        )

        li1 = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=self.item
        )
        li2 = models.LocationItem.objects.create(
            location=self.location, pc=self.pc, item=item2
        )

        # Take first item
        response = self._post_request("take_item", {"location_item": li1.id})
        self.assertEqual(response.status_code, 200)

        # Take second item
        response = self._post_request("take_item", {"location_item": li2.id})
        self.assertEqual(response.status_code, 200)

        # Both in inventory
        inv_items = list(self.pc.inventory_items())
        self.assertEqual(len(inv_items), 2)
        item_names = {inv.item.name for inv in inv_items}
        self.assertEqual(item_names, {"Sword", "Shield"})

    def test_drop_multiple_items_independently(self):
        """Multiple items can be dropped independently."""
        item2 = models.Item.objects.create(
            asset_id=f"it2_{uuid4().hex[:6]}",
            name="Shield",
            description="A shield",
            game=self.game,
            can_take=True,
            can_drop=True,
        )

        ii1 = models.InventoryItem.objects.create(pc=self.pc, item=self.item)
        ii2 = models.InventoryItem.objects.create(pc=self.pc, item=item2)

        # Drop first item
        response = self._post_request("drop_item", {"inventory_item": ii1.id})
        self.assertEqual(response.status_code, 200)

        # Drop second item
        response = self._post_request("drop_item", {"inventory_item": ii2.id})
        self.assertEqual(response.status_code, 200)

        # Both at location
        loc_items = list(self.pc.items_at())
        self.assertEqual(len(loc_items), 2)
        item_names = {li.item.name for li in loc_items}
        self.assertEqual(item_names, {"Sword", "Shield"})

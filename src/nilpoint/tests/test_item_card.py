"""The item card, as the location and inventory panels show it.

One partial draws a room item and a carried item, so the two panels cannot
drift apart: what differs is the movement verb (Take vs Drop) and the
permission that gates it, never the card's shape. These tests pin what the
card promises - Inspect always present and always the same action, the verb
on the right and only when `can_take` / `can_drop` allow it, an icon and a
text label on every button, and copy (not "None") when a panel is empty.
"""

import json
import re
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from nilpoint import models
from nilpoint.models import InventoryItem, LocationItem
from nilpoint.views import NilpointGameBasic

User = get_user_model()

CARD_OPEN = '<li class="nilpoint-item-card">'


class ItemCardWorld(TestCase):
    """A one-room world holding one item of every permission shape."""

    def setUp(self):
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
        self.pc = models.PlayerCharacter.objects.create(
            handle="hero", player=self.player, game=self.game
        )
        self.room = models.Location.objects.create(
            asset_id=f"room_{uuid4().hex[:6]}",
            name="Room",
            description="Plain walls.",
            game=self.game,
            initial=True,
        )
        self.pc.current_location = self.room
        self.pc.save()

        self.takeable = self._item("Takeable", can_take=True, can_drop=True)
        self.bolted = self._item("Bolted Thing", can_take=False, can_drop=True)
        self.keepsake = self._item("Keepsake", can_take=True, can_drop=False)

        self.on_floor = LocationItem.objects.create(
            item=self.takeable, location=self.room, pc=self.pc
        )
        self.nailed_down = LocationItem.objects.create(
            item=self.bolted, location=self.room, pc=self.pc
        )
        self.carried = InventoryItem.objects.create(item=self.takeable, pc=self.pc)
        self.held_keepsake = InventoryItem.objects.create(
            item=self.keepsake, pc=self.pc
        )

        self.factory = RequestFactory()

    def _item(self, name, can_take, can_drop):
        return models.Item.objects.create(
            asset_id=f"it_{uuid4().hex[:6]}",
            name=name,
            description=f"{name} description",
            game=self.game,
            can_take=can_take,
            can_drop=can_drop,
        )

    def _panel(self, action):
        """The rendered body of one panel, wired the way the landing wires it."""
        request = self.factory.get(f"/?action={action}")
        request.user = self.user
        request.COOKIES["pc"] = str(self.pc.id)

        view = NilpointGameBasic()
        view.setup(request)
        view.game = self.game
        view.player = self.player
        view.player_characters = [self.pc]
        view.player_character = self.pc
        return getattr(view, f"handle_{action}")(request).content.decode()

    def _cards(self, panel):
        """Every card in a rendered panel, as its own chunk of markup."""
        return [chunk.split("</li>")[0] for chunk in panel.split(CARD_OPEN)[1:]]

    def _card_for(self, panel, name):
        """The one card whose title is `name`."""
        for card in self._cards(panel):
            if f'<p class="nilpoint-item-card-title">{name}</p>' in card:
                return card
        self.fail(f"no card titled {name!r} in the panel")

    def _move_vals(self, card):
        """The parsed `hx-vals` of a card's movement button.

        Parsed rather than substring-matched: the values are a JSON object for
        htmx, so anything that is not valid JSON (an extra brace, say) is a bug
        that htmx would swallow silently - matching the text would not catch it.
        Either quoting style is accepted; the card uses single quotes.
        """
        raw = re.search(r"""hx-vals=(['"])(.*?)\1""", card)
        self.assertIsNotNone(raw, "the movement button has no hx-vals")
        return json.loads(raw.group(2).replace("&quot;", '"').replace("&#x27;", "'"))


class ItemCardTests(ItemCardWorld):
    """What one card shows, in either panel."""

    def test_the_location_panel_draws_a_card_per_item(self):
        panel = self._panel("get_location_item_panel")
        self.assertEqual(len(self._cards(panel)), self.pc.items_at().count())
        self.assertIn("Takeable", panel)
        self.assertIn("Bolted Thing", panel)

    def test_the_inventory_panel_draws_a_card_per_item(self):
        panel = self._panel("get_inventory_panel")
        self.assertEqual(len(self._cards(panel)), self.pc.inventory_items().count())
        self.assertIn("Takeable", panel)
        self.assertIn("Keepsake", panel)

    def test_both_panels_render_the_same_card_structure(self):
        """Neither panel adds markup the other lacks: the partial is shared."""
        room = self._panel("get_location_item_panel")
        bag = self._panel("get_inventory_panel")
        self.assertEqual(
            set(re.findall(r'class="([^"]*nilpoint-item-card[^"]*)"', room)),
            set(re.findall(r'class="([^"]*nilpoint-item-card[^"]*)"', bag)),
        )

    def test_every_card_has_media_and_a_footer(self):
        for action in ("get_location_item_panel", "get_inventory_panel"):
            for card in self._cards(self._panel(action)):
                self.assertIn('class="nilpoint-item-card-media"', card)
                self.assertIn('class="nilpoint-item-card-graphic"', card)
                self.assertIn('class="nilpoint-item-card-footer"', card)

    def test_the_card_title_is_a_bar_not_a_heading(self):
        panel = self._panel("get_location_item_panel")
        self.assertIn('<p class="nilpoint-item-card-title">Takeable</p>', panel)
        self.assertNotIn("<h4", panel)

    def test_the_title_bar_sits_over_the_graphic(self):
        """It is inside the media block, so it overlaps the artwork's top strip."""
        panel = self._panel("get_location_item_panel")
        media = panel.split('class="nilpoint-item-card-media"')[1]
        self.assertIn("nilpoint-item-card-title", media.split("</div>")[0])


class ItemCardActionTests(ItemCardWorld):
    """Which actions a card offers, and where they sit."""

    def test_inspect_is_on_every_card_and_is_still_item_detail(self):
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            self.assertTrue(self._cards(panel))
            for card in self._cards(panel):
                self.assertIn("?action=item_detail", card)
                self.assertIn('hx-target="#nilpoint-item-detail-panel"', card)
                self.assertIn(">Inspect</span>", card)
                # The label changed with the card; the action behind it did not.
                self.assertNotIn(">Detail<", card)

    def test_the_inspect_request_carries_the_record_it_came_from(self):
        room = self._card_for(self._panel("get_location_item_panel"), "Takeable")
        bag = self._card_for(self._panel("get_inventory_panel"), "Takeable")
        self.assertIn(f"location_item={self.on_floor.id}", room)
        self.assertIn(f"inventory_item={self.carried.id}", bag)

    def test_a_room_item_offers_take_and_never_drop(self):
        panel = self._panel("get_location_item_panel")
        card = self._card_for(panel, "Takeable")
        self.assertIn("?action=take_item", card)
        self.assertEqual(self._move_vals(card), {"location_item": self.on_floor.id})
        self.assertNotIn("?action=drop_item", panel)

    def test_a_room_item_that_cannot_be_taken_offers_no_verb(self):
        card = self._card_for(self._panel("get_location_item_panel"), "Bolted Thing")
        self.assertNotIn("?action=take_item", card)
        self.assertIn(">Inspect</span>", card)

    def test_a_carried_item_offers_drop_and_never_take(self):
        panel = self._panel("get_inventory_panel")
        card = self._card_for(panel, "Takeable")
        self.assertIn("?action=drop_item", card)
        self.assertEqual(self._move_vals(card), {"inventory_item": self.carried.id})
        self.assertNotIn("?action=take_item", panel)

    def test_a_carried_item_that_cannot_be_dropped_offers_no_verb(self):
        card = self._card_for(self._panel("get_inventory_panel"), "Keepsake")
        self.assertNotIn("?action=drop_item", card)
        self.assertIn(">Inspect</span>", card)

    def test_movement_is_a_post_that_swaps_nothing(self):
        """The panel reloads off the change trigger, not off this response."""
        card = self._card_for(self._panel("get_location_item_panel"), "Takeable")
        move = card.split("nilpoint-item-card-action--move")[1]
        self.assertIn('hx-post="', move)
        self.assertIn('hx-swap="none"', move)
        self.assertNotIn("hx-get=", move)

    def test_the_footer_orders_inspect_first(self):
        card = self._card_for(self._panel("get_location_item_panel"), "Takeable")
        footer = card.split('class="nilpoint-item-card-footer"')[1]
        self.assertLess(footer.index("Inspect"), footer.index(">Take<"))

    def test_every_action_has_a_glyph_and_a_text_label(self):
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            pairs = re.findall(
                r'<span class="nilpoint-item-card-glyph" aria-hidden="true">'
                r"(.*?)</span>\s*"
                r'<span class="nilpoint-item-card-label">(.*?)</span>',
                panel,
            )
            self.assertTrue(pairs)
            for card in self._cards(panel):
                self.assertTrue(card.count("nilpoint-item-card-action") >= 2)
                for glyph, label in re.findall(
                    r'<span class="nilpoint-item-card-glyph" aria-hidden="true">'
                    r"(.*?)</span>\s*"
                    r'<span class="nilpoint-item-card-label">(.*?)</span>',
                    card,
                ):
                    self.assertTrue(glyph.strip())
                    self.assertTrue(label.strip())

    def test_the_glyph_is_hidden_from_assistive_tech(self):
        panel = self._panel("get_location_item_panel")
        self.assertEqual(
            len(re.findall(r'class="nilpoint-item-card-glyph"', panel)),
            len(
                re.findall(
                    r'class="nilpoint-item-card-glyph" aria-hidden="true"', panel
                )
            ),
        )

    def test_the_card_builds_no_urls_of_its_own(self):
        """Every request the card makes is a dispatch URL, not a hand-built one."""
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            urls = re.findall(r'hx-(?:get|post)="([^"]+)"', panel)
            self.assertTrue(urls)
            for url in urls:
                self.assertIn("?action=", url)
            self.assertNotIn("href=", panel)

    def test_no_template_comment_leaks_into_the_card(self):
        """A wrapped `{# #}` comment is not stripped by Django's lexer.

        Django only strips a `{# #}` comment that fits on one line, so a
        multi-line one is emitted as literal text. The partial documents itself
        with `{% comment %}` blocks for that reason; this keeps it that way.
        """
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            self.assertNotIn("{#", panel)
            self.assertNotIn("#}", panel)

    def test_every_hx_vals_is_valid_json(self):
        """htmx parses hx-vals as JSON; invalid JSON is dropped in silence.

        The card writes `hx-vals` by hand (single-quoted, with a space before
        the closing brace so a `{{ }}` tag never renders a stray one), so this
        guards the output: each value must parse and carry the record's id
        under the key its handler reads.
        """
        seen = 0
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            for quote, raw in re.findall(r"""hx-vals=(['"])(.*?)\1""", panel):
                seen += 1
                parsed = json.loads(raw.replace("&quot;", '"').replace("&#x27;", "'"))
                self.assertIsInstance(parsed, dict)
                self.assertTrue(parsed)
                self.assertTrue(
                    set(parsed) <= {"location_item", "inventory_item"}, parsed
                )
                self.assertTrue(all(isinstance(v, int) for v in parsed.values()))
        self.assertTrue(seen)


class ItemCardEmptyStateTests(ItemCardWorld):
    """What a panel says when there is nothing to put in it."""

    def test_an_empty_room_panel_says_there_is_nothing_to_investigate(self):
        LocationItem.objects.all().delete()
        panel = self._panel("get_location_item_panel")
        self.assertIn("There are no items you can investigate here", panel)
        self.assertNotIn(CARD_OPEN, panel)
        self.assertNotIn(">None<", panel)

    def test_an_empty_inventory_says_the_player_is_carrying_nothing(self):
        InventoryItem.objects.all().delete()
        panel = self._panel("get_inventory_panel")
        self.assertIn("You are carrying nothing of note at the moment.", panel)
        self.assertNotIn(CARD_OPEN, panel)
        self.assertNotIn(">None<", panel)

    def test_both_empty_messages_share_one_hook(self):
        LocationItem.objects.all().delete()
        InventoryItem.objects.all().delete()
        for action in ("get_location_item_panel", "get_inventory_panel"):
            panel = self._panel(action)
            self.assertIn('class="nilpoint-empty-state"', panel)

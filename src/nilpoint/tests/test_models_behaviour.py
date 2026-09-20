from uuid import uuid4

from django.test import TestCase
from django.contrib.auth import get_user_model

from nilpoint import models

User = get_user_model()


class ModelsBehaviourTests(TestCase):
    def setUp(self):
        # Create user/player
        self.user = User.objects.create_user(
            username=f"u_{uuid4().hex[:6]}", password="pw"
        )
        self.player = models.Player.objects.create(user=self.user)

        # Unique game instance to avoid any asset_id collisions
        slug = f"g_{uuid4().hex[:6]}"
        self.game = models.Game.objects.create(
            instance_name=f"Game_{uuid4().hex[:6]}",
            instance_description="desc",
            nilpoint_slug=slug,
            allow_multiple_characters=False,
            default_location_graphic="loc_default.png",
            default_item_graphic="item_default.png",
        )

        # Preserve and allow monkeypatching reverse
        self._orig_reverse = models.reverse

    def tearDown(self):
        models.reverse = self._orig_reverse

    def test_get_dispatch_url_hash_and_reverse(self):
        # Empty slug -> returns "#"
        self.game.nilpoint_slug = ""
        self.game.save()
        self.assertEqual(self.game.get_dispatch_url(), "#")

        # Non-empty slug -> uses reverse; monkeypatch reverse to deterministic stub
        def fake_reverse(name, kwargs=None):
            return f"/{name}/{kwargs['nilpoint_slug']}/"

        models.reverse = fake_reverse
        self.game.nilpoint_slug = "myslug"
        self.game.save()
        expected = f"/{self.game._game_type}:dispatch/{self.game.nilpoint_slug}/"
        self.assertEqual(self.game.get_dispatch_url(), expected)

    def test_get_player_characters_returns_empty_if_no_player(self):
        no_player_user = User.objects.create_user(
            username=f"nop_{uuid4().hex[:6]}", password="pw"
        )
        chars = self.game.get_player_characters(no_player_user, self.game)
        self.assertEqual(list(chars), [])

    def test_get_initial_location_and_location_graphic_safe_and_str(self):
        loc = models.Location.objects.create(
            asset_id=f"start_{uuid4().hex[:6]}",
            name="Start",
            description="",
            game=self.game,
            initial=True,
        )
        found = self.game.get_initial_location()
        self.assertEqual(found, loc)

        # graphic_safe uses game default when unset
        self.assertIsNone(loc.graphic)
        self.assertEqual(loc.graphic_safe, self.game.default_location_graphic)

        # when graphic set uses own value
        loc.graphic = "foo.png"
        loc.save()
        self.assertEqual(loc.graphic_safe, "foo.png")

        # __str__ contains name
        self.assertIn("Start", str(loc))

    def test_game_update_release_raises_when_current_higher_than_latest(self):
        self.game.release = 5
        self.game.save()
        # make latest_release smaller than current to force the error path
        self.game.latest_release = lambda: 1
        with self.assertRaises(Exception):
            self.game.update_release()

    def test_item_graphic_safe_and_locationitem_str_and_player_str(self):
        # Player __str__
        self.assertEqual(str(self.player), self.user.username)

        # Item graphic_safe fallback and explicit
        item = models.Item.objects.create(
            asset_id=f"it_{uuid4().hex[:6]}",
            name="Thing",
            description="desc",
            game=self.game,
        )
        self.assertEqual(item.graphic_safe, self.game.default_item_graphic)
        item.graphic = "item.png"
        item.save()
        self.assertEqual(item.graphic_safe, "item.png")

        # LocationItem __str__
        loc = models.Location.objects.create(
            asset_id=f"loc_{uuid4().hex[:6]}",
            name="L2",
            description="",
            game=self.game,
            initial=False,
        )
        pc = models.PlayerCharacter.objects.create(
            handle=f"pc_{uuid4().hex[:6]}", player=self.player, game=self.game
        )
        li = models.LocationItem.objects.create(location=loc, pc=pc, item=item)
        s = str(li)
        self.assertIn("LocationItem", s)
        self.assertIn(item.name, s)
        self.assertIn(str(pc), s)

    def test_exit_create_two_way_exit_success_and_cross_game_error(self):
        l1 = models.Location.objects.create(
            asset_id=f"e1_{uuid4().hex[:6]}",
            name="A",
            description="",
            game=self.game,
            initial=False,
        )
        l2 = models.Location.objects.create(
            asset_id=f"e2_{uuid4().hex[:6]}",
            name="B",
            description="",
            game=self.game,
            initial=False,
        )

        e1, e2 = models.Exit.create_two_way_exit(
            l1, "east", l2, "west", f"ex_{uuid4().hex[:4]}"
        )
        self.assertTrue(e1.pk and e2.pk)
        self.assertTrue(e1.asset_id.endswith("_A"))
        self.assertTrue(e2.asset_id.endswith("_B"))

        # Cross-game error
        other_game = models.Game.objects.create(
            instance_name=f"Other_{uuid4().hex[:6]}",
            instance_description="x",
            nilpoint_slug=f"other_{uuid4().hex[:4]}",
            allow_multiple_characters=False,
        )
        l3 = models.Location.objects.create(
            asset_id=f"o_{uuid4().hex[:6]}",
            name="C",
            description="",
            game=other_game,
            initial=False,
        )
        with self.assertRaises(ValueError):
            models.Exit.create_two_way_exit(l1, "n", l3, "s", f"bad_{uuid4().hex[:4]}")


class GetModelAppsCallTests(TestCase):
    def test_get_model_calls_apps_get_model_with_require_ready_true(self):
        orig = models.apps.get_model
        called = {}

        def fake_get_model(model_string, require_ready=False):
            called["args"] = (model_string, require_ready)
            return models.PlayerCharacter

        models.apps.get_model = fake_get_model
        try:
            result = models.get_model("somegame", "PlayerCharacter")
            self.assertIs(result, models.PlayerCharacter)
            self.assertIn("args", called)
            self.assertIs(called["args"][1], True)
        finally:
            models.apps.get_model = orig


class GameRealInstanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username=f"gr_{uuid4().hex[:6]}", password="pw"
        )
        self.game = models.Game.objects.create(
            instance_name="GI",
            instance_description="desc",
            nilpoint_slug=f"gi_{uuid4().hex[:6]}",
            allow_multiple_characters=False,
        )

    def test_get_real_instance_returns_self_when_no_downcast_attr(self):
        # Default behaviour: no attribute matching _game_type on instance
        self.assertIs(self.game.get_real_instance(), self.game)

    def test_get_real_instance_returns_attribute_when_present(self):
        # Attach a fake attribute matching _game_type and ensure it's returned
        fake_downcast = object()
        setattr(self.game, self.game._game_type, fake_downcast)
        self.assertIs(self.game.get_real_instance(), fake_downcast)


class GetPlayerCharactersAndPCUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username=f"pcu_{uuid4().hex[:6]}", password="pw"
        )
        self.player = models.Player.objects.create(user=self.user)
        self.game = models.Game.objects.create(
            instance_name="GPC",
            instance_description="desc",
            nilpoint_slug=f"gpc_{uuid4().hex[:6]}",
            allow_multiple_characters=False,
        )

    def test_get_player_characters_returns_characters_for_player(self):
        pc1 = models.PlayerCharacter.objects.create(
            handle="pc1", player=self.player, game=self.game
        )
        pc2 = models.PlayerCharacter.objects.create(
            handle="pc2", player=self.player, game=self.game
        )
        chars = list(self.game.get_player_characters(self.user, self.game))
        ids = {c.pk for c in chars}
        self.assertIn(pc1.pk, ids)
        self.assertIn(pc2.pk, ids)

    def test_playercharacter_update_release_noop_when_current_equals_game(self):
        pc = models.PlayerCharacter.objects.create(
            handle="pc_noop", player=self.player, game=self.game
        )
        # ensure both releases equal (defaults are 0)
        pc.release = 0
        pc.save()
        self.game.release = 0
        self.game.save()
        self.assertEqual(pc.update_release(), 0)

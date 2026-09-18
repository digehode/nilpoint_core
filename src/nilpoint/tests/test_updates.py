import types
from django.test import TestCase
from django.contrib.auth import get_user_model

from nilpoint.decorators import release_step
from nilpoint import exceptions
from nilpoint import models


User = get_user_model()


class UpdateMechanismTests(TestCase):
    def setUp(self):
        # Create a user and Player for PlayerCharacter linking
        self.user = User.objects.create_user(username="tester", password="pw")
        self.player = models.Player.objects.create(user=self.user)

        # Create a Game instance (supply required fields)
        self.game = models.Game.objects.create(
            instance_name="T1",
            instance_description="desc",
            nilpoint_slug="t1",
            allow_multiple_characters=False,
        )

        # Create a PlayerCharacter linked to the above player & game
        self.pc = models.PlayerCharacter.objects.create(
            handle="pc1", player=self.player, game=self.game
        )

        # Track names we monkeypatch onto the classes so we can clean them up in tearDown
        self.added_game_methods = []
        self.added_pc_methods = []

    def tearDown(self):
        # Remove any methods added to classes to avoid polluting other tests
        for name in self.added_game_methods:
            if hasattr(models.Game, name):
                delattr(models.Game, name)
        for name in self.added_pc_methods:
            if hasattr(models.PlayerCharacter, name):
                delattr(models.PlayerCharacter, name)

    # Helpers for adding decorated methods to the model classes
    def add_game_step(self, target, func):
        name = f"release_update_{target}"
        decorated = release_step(target)(func)
        setattr(models.Game, name, decorated)
        self.added_game_methods.append(name)

    def add_pc_step(self, target, func):
        name = f"release_update_{target}"
        decorated = release_step(target)(func)
        setattr(models.PlayerCharacter, name, decorated)
        self.added_pc_methods.append(name)

    # ---------- Game + decorator tests ----------

    def test_release_step_success_sets_release_and_saves(self):
        # Define a migration that returns True for target release 1
        def step1(self):
            # mark called
            self._step1_called = True
            return True

        self.add_game_step(1, step1)

        # Ensure latest_release > current so update_release attempts the step
        self.game.latest_release = types.MethodType(lambda self: 1, self.game)

        # initial release is 0
        self.assertEqual(self.game.release, 0)
        # call update_release which should use the decorator-wrapped method
        self.game.update_release()
        # reload from DB to verify save occurred
        g = models.Game.objects.get(pk=self.game.pk)
        self.assertEqual(g.release, 1)
        # instance attribute set by the step should exist
        self.assertTrue(getattr(self.game, "_step1_called", False))

    def test_release_step_precondition_invalid_raises_InvalidReleaseStateError(self):
        # Method declared as step for release 2 but instance is not at release 1
        def step2(self):
            return True

        self.add_game_step(2, step2)

        # Ensure game.release is not 1 (default 0)
        self.assertNotEqual(self.game.release, 1)
        with self.assertRaises(exceptions.InvalidReleaseStateError):
            # Call the method directly on instance to exercise the decorator check
            getattr(self.game, "release_update_2")()

    def test_release_step_exception_wrapped_as_MigrationFailedError(self):
        def step1_fail(self):
            raise RuntimeError("boom")

        self.add_game_step(1, step1_fail)

        # Ensure latest_release > current so update_release will attempt the step
        self.game.latest_release = types.MethodType(lambda self: 1, self.game)

        # update_release should attempt release 1 and the decorator should wrap the error
        with self.assertRaises(exceptions.MigrationFailedError) as cm:
            self.game.update_release()
        # original exception should be chained inside
        self.assertIsInstance(cm.exception.__cause__, RuntimeError)
        # release should not be advanced
        g = models.Game.objects.get(pk=self.game.pk)
        self.assertEqual(g.release, 0)

    def test_release_step_invalid_return_raises_MigrationFailedError(self):
        def step1_bad(self):
            return False  # invalid return according to decorator

        self.add_game_step(1, step1_bad)

        # Ensure latest_release > current so update_release will attempt the step
        self.game.latest_release = types.MethodType(lambda self: 1, self.game)

        with self.assertRaises(exceptions.MigrationFailedError):
            self.game.update_release()
        g = models.Game.objects.get(pk=self.game.pk)
        self.assertEqual(g.release, 0)

    def test__get_migration_map_discovers_decorated_methods(self):
        def step1(self):
            return True

        def step3(self):
            return True

        self.add_game_step(1, step1)
        self.add_game_step(3, step3)

        mapping = self.game._get_migration_map()
        # keys should be the target releases
        self.assertIn(1, mapping)
        self.assertIn(3, mapping)
        # Ensure the mapping values are callable
        self.assertTrue(callable(mapping[1]))
        self.assertTrue(callable(mapping[3]))

    def test_update_release_raises_when_step_missing(self):
        # Add only a step for release 2; current release is 0 -> target 1 missing
        def step2(self):
            return True

        self.add_game_step(2, step2)

        # Ensure latest_release > current so update_release will attempt target 1
        self.game.latest_release = types.MethodType(lambda self: 2, self.game)

        # Inspect migration map for debugging: ensure target 1 is not present.
        migration_map = self.game._get_migration_map()
        # Provide a clearer failure message if the environment is polluted.
        self.assertNotIn(1, migration_map, msg=f"Unexpected migration step for release 1 found: {list(migration_map.keys())}")

        # Verify behavior: since release 1 is missing, update_release should raise NotImplementedError
        with self.assertRaises(NotImplementedError):
            self.game.update_release()

    def test_update_release_returns_current_if_already_latest(self):
        # For Game.latest_release default is 0; if current == latest then return current
        self.game.release = 0
        self.game.save()
        self.assertEqual(self.game.update_release(), 0)

    # ---------- PlayerCharacter update behavior (gap skipping) ----------

    def test_playercharacter_updates_to_latest_and_skips_gaps(self):
        # Game will be at release 3; PC starts at 0
        self.game.release = 3
        self.game.save()

        # Define PC step for release 1 and 3, but omit 2
        def pc_step1(self):
            self._pc_step1_called = True
            return True

        def pc_step3(self):
            self._pc_step3_called = True
            return True

        self.add_pc_step(1, pc_step1)
        self.add_pc_step(3, pc_step3)

        # Ensure starting release
        self.assertEqual(self.pc.release, 0)
        # Run catch-up updater
        self.pc.update_to_latest()
        # After update PC should be same as game
        pc_refreshed = models.PlayerCharacter.objects.get(pk=self.pc.pk)
        self.assertEqual(pc_refreshed.release, 3)
        # Steps 1 and 3 called; 2 was skipped (no step) but still advanced
        self.assertTrue(getattr(self.pc, "_pc_step1_called", False))
        self.assertTrue(getattr(self.pc, "_pc_step3_called", False))

    def test_playercharacter_update_release_increments_when_step_missing(self):
        # Set game to a later release
        self.game.release = 2
        self.game.save()

        # No PC migration methods added -> update_release should increment by 1 and save
        original_release = self.pc.release
        self.pc.update_release()
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.release, original_release + 1)

    def test_playercharacter_cannot_update_beyond_game_release(self):
        # If target > latest, update_release should raise an exception
        self.game.release = 1
        self.game.save()
        # set pc release to 1 (equal) and then artificially test case where pc.release > game.release
        self.pc.release = 2
        self.pc.save()
        with self.assertRaises(Exception):
            self.pc.update_release()

    def test_playercharacter_raises_when_current_higher_than_game(self):
        # current > latest should raise
        self.game.release = 1
        self.game.save()
        self.pc.release = 5
        self.pc.save()
        with self.assertRaises(Exception):
            self.pc.update_release()
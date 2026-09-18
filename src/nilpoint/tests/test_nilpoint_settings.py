from django.test import TestCase
from django.contrib.contenttypes.models import ContentType

from nilpoint.nilpoint_settings import nilpoint_settings, DEFAULTS


class NilpointSettingsTests(TestCase):
    def setUp(self):
        # Preserve and reset user settings per test
        self._orig = dict(nilpoint_settings.user_settings)

    def tearDown(self):
        nilpoint_settings.user_settings = self._orig

    def test_get_archetype_returns_default_when_no_override_and_override_branch(self):
        # No user overrides -> default
        nilpoint_settings.user_settings = {}
        result = nilpoint_settings.get_archetype("anygame", "PlayerCharacter")
        self.assertEqual(result, DEFAULTS["archetypes"]["PlayerCharacter"])

        # Nested override present for a specific game key
        nilpoint_settings.user_settings = {
            "archetypes": {"mygamekey": {"PlayerCharacter": "nilpoint.PlayerCharacter"}}
        }
        res2 = nilpoint_settings.get_archetype("mygamekey", "PlayerCharacter")
        self.assertEqual(res2, "nilpoint.PlayerCharacter")

    def test_games_returns_model_classes_from_user_settings(self):
        # Provide the 'model' names expected by the code path (ContentType.model)
        # For the Game model the ContentType.model is usually 'game'
        ct = ContentType.objects.get_for_model
        # Build settings referencing the Game model by its content type model string
        game_ct = ContentType.objects.get_for_model(__import__("nilpoint").models.Game)
        nilpoint_settings.user_settings = {"games": [game_ct.model]}
        games = nilpoint_settings.games()
        # games() should include the Game model class
        from nilpoint import models as npmodels

        self.assertIn(npmodels.Game, games)
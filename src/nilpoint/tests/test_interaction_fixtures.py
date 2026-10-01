"""Interaction classes used by the Nilpoint interaction tests.

Keeping them here means the test module can be read as tests, and it also
gives `test_interaction_fixtures` a real dotted path to exercise, since the
resolver has to import a class from somewhere.
"""

from nilpoint.interactions import Action, InteractiveItem


class WotsitLever(InteractiveItem):
    """A single action with a label and a partial. The simplest useful case."""

    show_partial = "nilpoint/test_interact_show.jinja2#test"
    actions = [Action("pull", label="Pull")]


class SqueezeWotsit(InteractiveItem):
    """An action gated on per-player state, rendered by a core partial.

    This is the worked example used by the dispatch tests: squeezing uses up
    one of the wotsit's charges, so the action is only offered while charges
    remain.
    """

    show_partial = "nilpoint/test_interact_show.jinja2#test"
    actions = [Action("squeeze", label="Squeeze")]

    def can(self, instance, action):
        return instance.item_state.get("charges", 0) > 0

    def handle(self, instance, action, request):
        charges = instance.item_state.get("charges", 0)
        instance.item_state.put("charges", charges - 1)
        return None


class MessyActionInteraction(InteractiveItem):
    """Builds its actions from the asset's options instead of a class attribute.

    Demonstrates that `get_actions()` can be computed, so an asset's options
    can drive its action list.
    """

    show_partial = "nilpoint/test_interact_show.jinja2#test"

    def get_actions(self):
        return [Action(self.options.get("verb", "poke"))]

    def can(self, instance, action):
        return True

    def handle(self, instance, action, request):
        return None


class CountingInteraction(InteractiveItem):
    """Puts its behaviour on the Action, so the class overrides no methods.

    A one-action interaction needs no `can()` or `handle()` at all. The count
    lives on the interaction instance so a test can prove the callable that ran
    was the one attached to the Action.
    """

    show_partial = "nilpoint/test_interact_show.jinja2#test"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.taps = 0

    def get_actions(self):
        return [
            Action(
                "tap",
                label="Tap",
                can=lambda instance: True,
                handle=lambda instance, request: self._tap(),
            )
        ]

    def _tap(self):
        self.taps += 1

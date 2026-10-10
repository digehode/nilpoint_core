"""Interaction classes used by the Nilpoint interaction tests.

Keeping them here means the test module can be read as tests, and it also
gives `test_interaction_fixtures` a real dotted path to exercise, since the
resolver has to import a class from somewhere.
"""

from nilpoint.interactions import Action, InteractiveItem, StateToggle


class WotsitLever(InteractiveItem):
    """A single action with a label and its own panel partial."""

    partial = "nilpoint/test_interact_show.jinja2#test"
    actions = [Action("pull", label="Pull")]


class Squeeze(Action):
    """Use one charge of a wotsit: a hand-written action next to its interaction."""

    def handle(self, instance, interaction, request):
        charges = instance.item_state.get("charges", 0)
        instance.item_state.put("charges", charges - 1)
        return None


class SqueezeWotsit(InteractiveItem):
    """An action gated on per-player state, rendered by a custom partial.

    This is the worked example used by the dispatch tests: squeezing uses up
    one of the wotsit's charges, so the action is only offered while charges
    remain.  The interaction judges, the `Squeeze` action does.
    """

    partial = "nilpoint/test_interact_show.jinja2#test"
    actions = [Squeeze("squeeze", label="Squeeze")]

    def can(self, instance, action):
        return instance.item_state.get("charges", 0) > 0


class Poke(Action):
    """A hand-written action that works even against a bare asset."""

    def handle(self, instance, interaction, request):
        instance.item_state.put("poked", True)
        return None


class MessyActionInteraction(InteractiveItem):
    """Builds its actions from the asset's options instead of a class attribute.

    Demonstrates that `get_actions()` can be computed, so an asset's options
    can drive its action list.
    """

    partial = "nilpoint/test_interact_show.jinja2#test"

    def get_actions(self):
        return [Poke(self.options.get("verb", "poke"))]

    def can(self, instance, action):
        return True


class CountingAction(Action):
    """Count the taps made against the interaction that owns it."""

    def handle(self, instance, interaction, request):
        interaction.taps += 1
        return None


class CountingInteraction(InteractiveItem):
    """A one-action interaction whose behaviour lives on the action.

    The count lives on the interaction instance so a test can prove the
    action's `handle` is what ran, against the right interaction.
    """

    partial = "nilpoint/test_interact_show.jinja2#test"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.taps = 0

    def get_actions(self):
        return [CountingAction("tap", label="Tap")]

    def can(self, instance, action):
        return True


class SimplePushInteraction(InteractiveItem):
    """A bare interaction: no partial of its own.

    This is the default path: its panel is the framework's list of buttons,
    one per available action, a click each.  The push is a framework generic
    (`StateToggle`), so the class itself only declares it.
    """

    actions = [StateToggle("push", label="Push", state_key="pushed")]


class ClosedGate(Action):
    """An action that refuses itself, to prove both `can` gates are honoured."""

    def can(self, instance, interaction):
        return False

    def handle(self, instance, interaction, request):
        instance.item_state.put("pressed", True)
        return None


class GateKeeperInteraction(InteractiveItem):
    """The interaction allows everything; only the action's own gate refuses."""

    actions = [ClosedGate("press", label="Press")]


class NoActionsInteraction(InteractiveItem):
    """Declares no actions and no partial: the default panel shows nothing to do."""


class InterfaceOnlyInteraction(InteractiveItem):
    """No actions, but a partial: shows status or computed data only.

    The panel loads with no action named, so it never needs to know about an
    action to render.
    """

    partial = "nilpoint/test_interact_status_show.jinja2#status"

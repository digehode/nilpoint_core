"""Interactions for the demo game.

Two items are interactive, at opposite ends of the scale:

* `Lamp` - the simplest possible interactive item: one framework generic
  action (`StateToggle`), the default button-panel partial, no judgement.
* `Keypad` - the full custom job: a custom `Action` that reads a form, a
  custom partial showing that form, per-item config (the code) via
  `interaction_options`, and a `can` gate that swaps which actions are
  offered based on per-player state.

The split to see on both: the interaction owns identity and judgement
(what exists, what may be done now, what the panel shows); each `Action`
owns the effect of one named thing.
"""

from nilpoint.interactions import (
    Action,
    InteractiveItem,
    SetState,
    StateToggle,
    holder_type,
)


class Lamp(InteractiveItem):
    """A desk lamp the player can switch on and off.

    Both actions are the framework generic `StateToggle`, so the whole
    class is just the action list.  The state ("lit") lives on each
    player's own copy of the item, so one player's lamp doesn't light
    anyone else's.
    """

    actions = [
        StateToggle(
            "toggle",
            label="Flip the switch",
            state_key="lit",
            on_message="The lamp flickers on.",
            off_message="The lamp goes dark.",
        ),
    ]


class UnlockKeyPad(Action):
    """Enter the keypad's code from the form in the panel.

    The expected code is not in this class - it comes from the item's
    `interaction_options` (exposed to the interaction as `self.options`),
    so several keypads can share this action with different codes.  The
    view enforces the interaction's `can` gate before calling `handle`,
    so a request that bypasses the form still cannot unlock twice.
    """

    state_key = "unlocked"

    def handle(self, instance, interaction, request):
        code = (request.POST.get("code") or "").strip()
        if code == str(interaction.options.get("code", "")):
            self.set_state(instance, True)
            return "The keypad beeps and the light turns green."
        return "The keypad buzzes."


class Keypad(InteractiveItem):
    """A wall keypad locked with a four-digit code.

    While locked the panel is a code-entry form (custom `partial`
    below); once unlocked it falls back to the standard action buttons -
    currently just "Lock it again".  Which actions are offered is
    decided by `can`, on per-player state, so unlocking is private to
    the character who entered the code.
    """

    partial = "demo/keypad.jinja2#keypad"

    actions = [
        UnlockKeyPad("unlock", label="Enter the code"),
        SetState(
            "lock",
            label="Lock it again",
            state_key="unlocked",
            value=False,
            message="The keypad locks.",
        ),
    ]

    def can(self, instance, action):
        """Offer "unlock" only while locked, "lock" only while unlocked."""
        unlocked = bool(instance.item_state.get("unlocked", False))
        return unlocked == (action.name == "lock")

    def get_context(self, instance):
        """The panel needs the lock state, and the wire name of whatever
        record the form is posting against (the keypad always sits in the
        world, but asking `holder_type` keeps the template from having to
        know that)."""
        return {
            "unlocked": bool(instance.item_state.get("unlocked", False)),
            "target_type": holder_type(instance),
        }

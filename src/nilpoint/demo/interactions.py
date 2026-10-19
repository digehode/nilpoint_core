"""Interactions for the demo game.

Two items and one exit are interactive, at opposite ends of the scale:

* `Lamp` - the simplest possible interactive item: one framework generic
  action (`StateToggle`), the default button-panel partial, no judgement.
* `Keypad` - the full custom job: a custom `Action` that reads a form, a
  custom partial showing that form, per-item config (the code) via
  `interaction_options`, and a `can` gate that swaps which actions are
  offered based on per-player state.  Its unlock writes the one
  character-state key (`storeroom_open`) that the door rule reads and
  the lock generic clears - keypad panel and door are one fact in one
  home, so they can never disagree.
* `HiddenStoreroom` - the plainest exit rule: one hook that reads the
  character's own state, no actions, no panel.

The split to see on all three: the interaction owns identity and judgement
(what exists, what may be done now, what the panel shows); each `Action`
owns the effect of one named thing.  Rules only read state; actions write it.
"""

from nilpoint.interactions import (
    Action,
    ExitInteraction,
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

    A correct code writes exactly one key: `storeroom_open` on the
    character's own state - the key `HiddenStoreroom` reads, the key the
    lock button clears, and the key `Keypad`'s own `can` gate and panel
    show.  One fact in one home, per character: the door, the buttons
    offered, and the light in the panel all read the same value, so
    there is no second copy to fall out of step, and nothing here can
    change what another character sees.
    """

    def handle(self, instance, interaction, request):
        code = (request.POST.get("code") or "").strip()
        if code == str(interaction.options.get("code", "")):
            interaction.pc.item_state.put("storeroom_open", True)
            return "The keypad beeps and the light turns green."
        return "The keypad buzzes."


class Keypad(InteractiveItem):
    """A wall keypad locked with a four-digit code.

    While locked the panel is a code-entry form (custom `partial`
    below); once unlocked it falls back to the standard action buttons -
    currently just "Lock it again", a framework `SetState` writing
    `state_target="pc"` that re-closes the storeroom door the code
    opened.  Both actions write the one character-state key, and `can`
    reads it to decide which buttons to offer, so unlocking is private
    to the character who entered the code and the panel can never
    disagree with the door.
    """

    partial = "demo/keypad.jinja2#keypad"

    actions = [
        UnlockKeyPad("unlock", label="Enter the code"),
        SetState(
            "lock",
            label="Lock it again",
            state_target="pc",
            state_key="storeroom_open",
            value=False,
            message="The keypad locks.",
        ),
    ]

    def can(self, instance, action):
        """Offer "unlock" only while locked, "lock" only while unlocked.

        Both names judge the one key, `storeroom_open`, on the
        character's own state - the same key the panel shows and the
        door reads.
        """
        unlocked = bool(self.pc.item_state.get("storeroom_open", False))
        return unlocked == (action.name == "lock")

    def get_context(self, instance):
        """The panel needs the lock state - read from the same key the
        door rule reads - and the wire name of whatever record the form
        is posting against (the keypad always sits in the world, but
        asking `holder_type` keeps the template from having to know
        that)."""
        return {
            "unlocked": bool(self.pc.item_state.get("storeroom_open", False)),
            "target_type": holder_type(instance),
        }


class HiddenStoreroom(ExitInteraction):
    """The storeroom door: only there for a character whose code was accepted.

    Reads the character-state key the keypad's unlock writes, so the two
    agree on `"storeroom_open"` rather than knowing about each other -
    and both are per character, so one character opening the door opens
    it only for them.  Invisible also means unusable: `use_exit` enforces
    `visible and usable`, so naming the exit directly still cannot get
    past a door this character cannot see.

    The rule only reads; the keypad's actions are the only writers:
    entering the code lifts the latch (`UnlockKeyPad`), the lock button
    drops it again (the framework `SetState` with `state_target="pc"`),
    and both write the character's own state - the same single key this
    rule, `Keypad.can`, and the keypad's panel all read - so the door
    follows the keypad for the character who used it, and no one else.
    """

    def visible(self, instance):
        return bool(self.pc.item_state.get("storeroom_open"))

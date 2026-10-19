"""Interactive behaviour for Nilpoint game assets.

An asset that a player can do something to - an `Item`, an `Exit`, a
`Location` - stores the dotted path of an `InteractiveItem` subclass in
its `interaction` field.  That class is instantiated on demand and
answers questions about the asset: which actions the player may take and
what to do when one is chosen (an item), whether the exit is listed and
usable (an exit), what this player sees of the room (a location).

Declaring the behaviour as classes rather than as dicts of method names on
`Game` means the framework never has to look behaviour up by string, so
renames and typos are caught by the interpreter rather than at play time.  It
also means several items - in one game or in different games - can share a
single interaction class by inheritance instead of by copy-and-paste.

Design notes
------------

* Interaction classes are **not** Django models.  They are short-lived,
  stateless helpers built once per request; anything that varies per player
  belongs in `item_state` (see `StatefulMixin`).
* Responsibility is split down the middle.  The **interaction** is the home of
  identity and judgement: it declares the `actions`, owns the authoritative
  `can(instance, action)` gate (it sees the whole context - where the item
  is, what the player has, what the player knows), picks the `partial`, and
  computes extra panel context.  The **action** is the home of the effect:
  it implements `handle(instance, interaction, request)`, and may declare a
  `state_key` and use `get_state()`/`set_state()` to work against the
  player's copy of the item - or against the character's own state when it
  declares `state_target="pc"`.  Framework generics - `StateToggle`,
  `SetState` - cover the common cases; anything else is a small `Action`
  subclass next to the interaction that uses it.
* Both `can` gates are enforced, by the view and by `available_actions()`,
  before `handle` ever runs.  The interaction's gate is authoritative; an
  action's own `can` exists for the cases an action can judge about itself.
* Each asset kind declares which family of behaviour class it accepts in
  its `interaction_base` (default: `InteractiveItem`).  Pointing an Exit
  at an item's interaction is a configuration error, caught where the path
  resolves - and so by `nilpoint_check_interactions` - rather than
  silently doing nothing at play time.
* Rules read, actions write.  An exit or location interaction only ever
  *reads* per-player state (`pc.item_state`); the effect of changing that
  state lives on an `Action` (`SetState`/`StateToggle` with
  `state_target="pc"` write the character's own state).  Read-only rules
  over per-player state cannot bleed between players.
* The set of actions is *declared* on the interaction using `Action`, so the
  framework can enumerate actions for button rendering, admin display and
  validation without inspecting method names.
* An interaction renders exactly one partial - its `partial` attribute -
  chosen at class level so every action behaves the same way.  The default
  partial is one button per available action; a class with an interface of
  its own (a device panel, a status readout) points `partial` at it.  The
  panel is always shown when the item's detail renders, auto-loaded into the
  item detail; showing it is not an action, so a panel load never names one.
* Games should keep their interaction classes in `<app>/interactions.py`.
  The dotted path is stored in the database, so moving or renaming a class is
  a breaking change that needs a release step; `nilpoint_check_interactions`
  reports the paths in use and will fail loudly on one that no longer
  imports.

Example
-------

    # cypherpunk/interactions.py
    from nilpoint.interactions import Action, InteractiveItem, SetState

    class MysteryDevice(InteractiveItem):
        \"\"\"A device that has to be pushed before it can be switched off.\"\"\"

        partial = "cypherpunk/interact/mystery_device.jinja2#device"

        actions = [
            SetState(
                "push_button",
                label="Push button",
                state_key="pushed",
                value=True,
                message="The device whirs into a steady hum.",
            ),
            SetState(
                "turn_off",
                label="Turn off",
                state_key="pushed",
                value=False,
                message="The device falls silent.",
            ),
        ]

        def can(self, instance, action):
            if not instance.is_in_inventory:
                return False
            is_pushed = bool(instance.item_state.get("pushed", False))
            return is_pushed == (action.name == "turn_off")

    # cypherpunk/models.py, in a release step
    @release_step(7)
    def add_mystery_device(self):
        Item.objects.create(
            game=self,
            asset_id="MYSTERY_DEVICE",
            name="Mystery Device",
            description="A mysterious device with a button labelled 'push me'",
            interaction=MysteryDevice.dotted_path(),
        )
"""

import re

from django.db import models
from django.utils.module_loading import import_string

from .exceptions import UnresolvableInteraction


class InteractiveMixin(models.Model):
    """Abstract model mixin that gives a game asset its behaviour.

    Adding this mixin to a `GameAsset` adds two fields and two lookup methods:

    - `interaction` - dotted path to an `InteractiveItem` subclass, empty if
      the asset does nothing.
    - `interaction_options` - a free-form dict of per-asset settings made
      available to the interaction class as `self.options`.

    `get_interaction_class()` resolves and validates the stored path, and
    `get_interaction()` builds a bound instance of it.

    The family of behaviour a model accepts is declared by its
    `interaction_base` class attribute (None means any `InteractiveItem`
    subclass, which is what an `Item` wants); a model narrows it, e.g.
    `Exit` sets `ExitInteraction` so an item's interaction cannot be wired
    to a door by mistake.

    Developer Usage:

        class Item(InteractiveMixin, GameAsset):
            ...

        # in a release step
        device.interaction = MysteryDevice.dotted_path()
        device.save()

        # anywhere you need the behaviour
        interaction = device.get_interaction(instance=some_location_item)
        if interaction and interaction.can(
            some_location_item, interaction.get_action("push_button")
        ):
            ...
    """

    interaction = models.CharField(
        max_length=200,
        null=False,
        blank=True,
        default="",
        help_text=(
            "Dotted path to an InteractiveItem subclass that implements this "
            "asset's behaviour, e.g. 'cypherpunk.interactions.MysteryDevice'. "
            "Empty if the asset has no interactions."
        ),
    )
    interaction_options = models.JSONField(
        null=False,
        blank=True,
        default=dict,
        help_text="Per-asset options dict, made available to the interaction class",
    )

    # The family of behaviour class this model accepts; None means any
    # InteractiveItem subclass.  Set per model (Exit sets ExitInteraction,
    # Location sets LocationInteraction) - InteractiveItem itself is
    # defined later in this module, so the default can't be a direct
    # reference here.  Read in get_interaction_class().
    interaction_base = None

    class Meta:
        abstract = True

    def get_interaction_class(self):
        """Resolve `interaction` to the class it names.

        Returns:
            The behaviour class for this model's family (an `InteractiveItem`
            subclass, or a narrower one such as `ExitInteraction`), or None
            if this asset has no interaction configured.

        Raises:
            UnresolvableInteraction: if the stored path will not import, or
                names a class outside this model's `interaction_base` family.
                The message names the asset and the underlying import error.
        """
        if not self.interaction:
            return None

        try:
            interaction_class = import_string(self.interaction)
        except ImportError as exc:
            raise UnresolvableInteraction(
                f"{type(self).__name__} '{getattr(self, 'asset_id', self.pk)}' "
                f"in game '{self.game.nilpoint_slug}' names interaction "
                f"'{self.interaction}', which cannot be imported: {exc}"
            ) from exc

        base = self.interaction_base or InteractiveItem
        if not (
            isinstance(interaction_class, type) and issubclass(interaction_class, base)
        ):
            base_name = base.__name__
            article = "an" if base_name[0].lower() in "aeiou" else "a"
            raise UnresolvableInteraction(
                f"{type(self).__name__} '{getattr(self, 'asset_id', self.pk)}' "
                f"in game '{self.game.nilpoint_slug}' names interaction "
                f"'{self.interaction}', which is not {article} {base_name} subclass"
            )

        return interaction_class

    def get_interaction(self, instance=None, pc=None):
        """Build an interaction object bound to this asset.

        Args:
            instance: the player-scoped record this interaction is happening
                on (a `LocationItem` or `InventoryItem`), or None for assets
                that have no per-player record such as an `Exit`.
            pc: the `PlayerCharacter` the interaction is for.  Defaults to the
                one attached to `instance`.

        Returns:
            An `InteractiveItem` instance, or None if this asset has no
            interaction configured.
        """
        interaction_class = self.get_interaction_class()
        if interaction_class is None:
            return None
        return interaction_class(self, instance=instance, pc=pc)

    def describe_interaction(self):
        """Summarise this asset's interaction for admin display.

        Returns:
            A dict with the resolved class path, the list of action names the
            class declares, and a label per action, or None if the asset has
            no interaction configured.
        """
        interaction_class = self.get_interaction_class()
        if interaction_class is None:
            return None
        actions = interaction_class(self).get_actions()
        return {
            "class": interaction_class.dotted_path(),
            "actions": [action.name for action in actions],
            "labels": {action.name: action.display_label for action in actions},
            "options": self.interaction_options or {},
        }


class Action:
    """One named thing a player can do to an interactive asset.

    The Action is the home of the *effect*: it implements `handle()`, may
    declare the `state_key` it touches and use `get_state()`/`set_state()`
    against it, and can gate itself with an optional `can`.  Actions are
    declared on an `InteractiveItem` subclass (as its `actions` class
    attribute) so that the framework can enumerate them - for button
    rendering, admin display and request validation - without the class
    having to implement anything for the simple cases.

    Attributes:
        name: The action name, as sent to the dispatch view.  Unique within
            one interaction class, and part of the wire protocol, so treat it
            as permanent once released.
        label: The text shown on the button.  Defaults to a title-cased
            version of `name`.
        description: Optional prose, shown in admin listings.
        state_key: Optional name of a per-player state key.  Where it lives
            is decided by `state_target`: on the item's record by default,
            on the character's own state when `state_target="pc"`.
            `get_state()`/`set_state()` work against it, so a generic action
            like `StateToggle` only needs this declaration to touch state.
        state_target: `"instance"` (default) puts `state_key` on the
            player's copy of the record (`instance.item_state`); `"pc"` puts
            it on the character's own state (`pc.item_state`) - the key
            space that exit and location rules read.

    Subclassing notes:
        `handle(instance, interaction, request)` is the one required method.
        An action instance is shared by every use of its interaction class,
        so actions must stay stateless - any per-player variation belongs in
        `instance.item_state`, reached through the interaction passed in.
    """

    name = None
    label = None
    description = ""
    state_key = None
    state_target = "instance"

    def __init__(self, name, label=None, description=""):
        self.name = name
        self.label = label
        self.description = description

    @property
    def display_label(self):
        """The button text for this action: its label, or one derived from its name."""
        return self.label or self.name.replace("_", " ").title()

    def can(self, instance, interaction):
        """Whether this action is currently available, judged by its own data.

        Args:
            instance: the player-scoped record the interaction is happening
                on, or None for assets with none (an Exit).
            interaction: the bound `InteractiveItem`, for access to the
                player, options and asset.

        Returns:
            True if the action may be taken.  The default allows everything.

        The interaction's `can` is the authoritative gate - it sees the whole
        context (where the item is, what the player has, what the player
        knows) - and both gates are enforced.  Override here only for what an
        action can judge about itself from its own declared data, such as a
        toggle that only means anything when its key exists.
        """
        return True

    def handle(self, instance, interaction, request):
        """Perform this action.

        Args:
            instance: the player-scoped record for this player.
            interaction: the bound `InteractiveItem`.
            request: the current `HttpRequest`.

        Returns:
            None to have the framework re-render the panel with the new
            state, a string to send that text back to the player, or an
            `HttpResponse` (such as `HtmxTriggerResponse`) to return it as-is.

        Raises:
            NotImplementedError: if the action does not implement the
                behaviour.
        """
        raise NotImplementedError(
            f"{type(self).__name__} '{self.name}' has no behaviour. "
            "Subclass Action and implement handle()."
        )

    def get_state(self, instance, default=None, interaction=None):
        """Read `state_key` from its home, or `default` if unset.

        The home is the player's record (the `LocationItem`/`InventoryItem`
        the interaction is happening on) unless `state_target` is `"pc"`,
        in which case it is the character's own state.  Pass the bound
        `interaction` when targeting PC state - it carries the `pc`.
        """
        return self._state(instance, interaction).get(self.state_key, default)

    def set_state(self, instance, value, interaction=None):
        """Write `value` to `state_key` at its home (see `get_state`)."""
        self._state(instance, interaction).put(self.state_key, value)

    def _state(self, instance, interaction=None):
        """The state dict this action reads and writes, with useful errors."""
        if self.state_key is None:
            raise TypeError(
                f"{type(self).__name__} '{self.name}' declares no state_key; "
                "read and write instance.item_state directly."
            )
        if self.state_target == "pc":
            pc = getattr(interaction, "pc", None) or getattr(instance, "pc", None)
            if pc is None:
                raise TypeError(
                    f"{type(self).__name__} '{self.name}' targets PC state and "
                    "needs a player character; pass the bound interaction."
                )
            return pc.item_state
        if instance is None:
            raise TypeError(
                f"{type(self).__name__} '{self.name}' needs the player's "
                "record (LocationItem/InventoryItem) to touch state; "
                "targets with no record are stateless or write PC state "
                'with state_target="pc".'
            )
        return instance.item_state

    def __repr__(self):
        return f"Action({self.name!r}, label={self.label!r})"


class StateToggle(Action):
    """Flip a boolean stored under `state_key`.

    The first press turns the key True (from its default False); each press
    after flips it.  `on_message`/`off_message` are logged to the player, or
    leave them empty for a silent action.  `state_key` lives on the player's
    record unless `state_target="pc"`, which writes the character's own
    state instead - the key space exit and location rules read.

    Usage:
        actions = [StateToggle("power", state_key="pushed",
                               label="Push button",
                               on_message="On", off_message="Off")]

        # a latch that decides whether a door exists for this character
        actions = [StateToggle("push", state_key="storeroom_open",
                               state_target="pc")]
    """

    state_key = None
    state_target = "instance"
    on_message = ""
    off_message = ""

    def __init__(
        self,
        name,
        label=None,
        description="",
        *,
        state_key=None,
        state_target=None,
        on_message="",
        off_message="",
    ):
        super().__init__(name, label, description)
        # Constructor kwargs override the class defaults, so the same generic
        # can be configured differently on each line of an action list.
        self.state_key = state_key if state_key is not None else self.state_key
        self.state_target = (
            state_target if state_target is not None else self.state_target
        )
        self.on_message = on_message if on_message else self.on_message
        self.off_message = off_message if off_message else self.off_message

    def handle(self, instance, interaction, request):
        on = not self.get_state(instance, default=False, interaction=interaction)
        self.set_state(instance, on, interaction=interaction)
        return (self.on_message if on else self.off_message) or None


class SetState(Action):
    """Set `state_key` to a fixed `value`.

    `message` is logged to the player; leave it empty for a silent action.
    `state_key` lives on the player's record unless `state_target="pc"`,
    which writes the character's own state instead - the key space exit and
    location rules read.

    Usage:
        actions = [SetState("unlock", state_key="unlocked", value=True,
                            message="The lock clicks open.")]

        # on a keypad: open the storeroom door for this character only
        actions = [SetState("unlock", state_key="storeroom_open",
                            state_target="pc", value=True,
                            message="The keypad beeps green.")]
    """

    state_key = None
    state_target = "instance"
    value = None
    message = ""

    def __init__(
        self,
        name,
        label=None,
        description="",
        *,
        state_key=None,
        state_target=None,
        value=None,
        message="",
    ):
        super().__init__(name, label, description)
        self.state_key = state_key if state_key is not None else self.state_key
        self.state_target = (
            state_target if state_target is not None else self.state_target
        )
        self.value = value if value is not None else self.value
        self.message = message if message else self.message

    def handle(self, instance, interaction, request):
        self.set_state(instance, self.value, interaction=interaction)
        return self.message or None


class InteractiveItem:
    """Base class for the behaviour of an interactive asset.

    Subclasses declare their `actions` (each an `Action` - a framework
    generic or a subclass of its own) and override `can` for judgement.  The
    effect of each action lives on the `Action` itself.  Instances of this
    class are built per request and hold no state; per-player data belongs in
    the `item_state` of the `LocationItem`/`InventoryItem` passed in as
    `instance`.

    Attributes:
        partial: Template partial (`"app/template.jinja2#fragment"`) for the
            interaction's panel - the one thing that is shown whenever the
            item's detail renders.  Defaults to the framework's list of
            buttons, one per available action.  A class with an interface of
            its own overrides this with the path of its own partial; an
            interaction with no actions at all still has a panel (the default
            renders "No actions available", useful for a status readout).
        actions: The declared `Action` list, or None if `get_actions()` is
            overridden to compute it.
    """

    partial = "nilpoint/action_panel.jinja2#action_list"
    actions = ()

    def __init__(self, item, instance=None, pc=None):
        """Bind this interaction to an asset.

        Args:
            item: the `GameAsset` that carries the interaction.  For an item
                in the world this is the `Item`; `item_state` lives on
                `instance` instead.
            instance: the player-scoped record for this player, if there is
                one (`LocationItem` or `InventoryItem`).
            pc: the `PlayerCharacter` involved.  Defaults to `instance.pc`.
        """
        self.item = item
        self.instance = instance
        self.pc = pc if pc is not None else getattr(instance, "pc", None)
        self.options = dict(getattr(item, "interaction_options", None) or {})

    @classmethod
    def dotted_path(cls):
        """The path to store in an asset's `interaction` field.

        Using this in release steps means renames are caught by the IDE rather
        than by a lookup in the database.
        """
        return f"{cls.__module__}.{cls.__qualname__}"

    def get_actions(self):
        """Return the `Action` list this interaction offers.

        Override to compute actions from `self.options` or the bound instance.
        The default returns a copy of the `actions` class attribute.
        """
        return list(self.actions)

    def get_action(self, name):
        """Return the declared `Action` called `name`, or None if there isn't one."""
        for action in self.get_actions():
            if action.name == name:
                return action
        return None

    def available_actions(self, instance=None):
        """Return the `Action` list the player can currently take.

        This is what the UI renders buttons for.  An action is offered only
        when the interaction's `can` gate *and* the action's own `can` gate
        both allow it.  A gate that raises hides the button rather than
        taking the panel down.
        """
        instance = instance if instance is not None else self.instance
        available = []
        for action in self.get_actions():
            try:
                allowed = self.can(instance, action) and action.can(instance, self)
            except Exception:
                # A broken gate must not take the whole panel down.
                allowed = False
            if allowed:
                available.append(action)
        return available

    def can(self, instance, action):
        """Whether `action` is currently available.

        Args:
            instance: the player-scoped record, or None for assets that have
                none.
            action: the `Action` being tested.

        Returns:
            True if the action may be taken.  The default allows everything.

        This is the authoritative gate: it sees the whole context - where the
        item is (`instance.is_in_inventory`), what the player has
        (`interaction.pc.inventory_items()`), what the player knows
        (`interaction.pc.item_state`), and the item's own options.  Override
        it for judgement; the effect of the action lives on the `Action`.
        The view and `available_actions()` also honour the action's own `can`.
        """
        return True

    def get_context(self, instance):
        """Extra template context for the interaction's panel.

        Return a dict to be merged into the context the framework passes to
        the partial.  `instance`, `item`, `asset`, `state`, `pc` and
        `interaction` are always present; this is for anything else a partial
        needs.
        """
        return {}

    @property
    def label(self):
        """A human-readable name for this interaction, for templates and logs.

        Defaults to the asset's name, which is usually what a player would call
        it.  Override when an interaction covers something with no name of its
        own, or spans several assets.
        """
        return str(getattr(self.item, "name", None) or type(self).__name__)

    def describe(self):
        """Summarise this interaction for admin display.

        Returns:
            A list of dicts with `name`, `label`, `class`, `state_key` and
            `partial` per action.  `class` names the implementing `Action`
            subclass, so a framework generic is distinguishable from a game's
            one-off.
        """
        return [
            {
                "name": action.name,
                "label": action.display_label,
                "class": type(action).__name__,
                "state_key": action.state_key,
                "partial": self.partial or None,
            }
            for action in self.get_actions()
        ]


DEFAULT_EXIT_REFUSAL = "You can't use that exit at the moment"


class ExitInteraction(InteractiveItem):
    """Behaviour for an `Exit`: whether it is listed, and whether it may be used.

    An exit with no interaction configured is a plain door: always listed,
    always usable.  A configured one is judgement over per-player state -
    `self.pc.item_state`, `self.pc.inventory_items()`, `self.options` -
    and implements only the hooks it needs:

        class ServiceDoor(ExitInteraction):
            def visible(self, instance):
                return bool(self.pc.item_state.get("storeroom_open"))

    The hooks only ever *read* state; the effect of changing it (entering
    the code, turning the handle) lives on an `Action` writing a key the
    exit reads (`SetState(..., state_target="pc")` writes the character's
    own state).  Read-only rules over per-player state cannot bleed
    between players.

    A hook that raises counts as closed - hidden, or refused - the same
    way a raising action gate hides its button rather than taking the
    panel down.
    """

    def visible(self, instance):
        """Whether the exit appears in this player's exit list.  Default True.

        An invisible exit can never be used: `use_exit` enforces
        `visible and usable`, so a hand-crafted request cannot walk
        through a door the player cannot see.
        """
        return True

    def usable(self, instance):
        """Whether this player may use the exit.  Default True."""
        return True

    def refusal(self, instance):
        """The message logged when the exit refuses this player."""
        return DEFAULT_EXIT_REFUSAL


class LocationInteraction(InteractiveItem):
    """Behaviour for a `Location`: overrides for what one player sees.

    Most rooms need nothing: with no interaction configured they render
    their own description and graphic.  A hook returns the override for
    this player, or None to fall through to the asset's own value (which
    `graphic_safe` already pads with the game's default graphic):

        class TorchSight(LocationInteraction):
            def describe(self, instance):
                if self.pc.item_state.get("lit_path"):
                    return self.item.description + " By torchlight..."
                return None

    As with exits, the hooks only read state - an `Action` elsewhere
    writes it.  A hook that raises falls through to the asset's own value,
    so a broken view rule shows the plain room rather than an error page.
    """

    def describe(self, instance):
        """The description for this player, or None for the location's own."""
        return None

    def graphic(self, instance):
        """The graphic path for this player, or None for `graphic_safe`."""
        return None


class RequiresPCState(ExitInteraction):
    """An exit that exists only while a character-state key holds truthy.

    Configure the key on the asset:

        exit.interaction = RequiresPCState.dotted_path()
        exit.interaction_options = {"state_key": "storeroom_open"}

    or subclass and declare `state_key` to reuse one configuration across
    assets.  A missing key fails closed: no key, no exit.
    """

    state_key = None

    def visible(self, instance):
        key = self.state_key or self.options.get("state_key")
        return bool(key and self.pc.item_state.get(key, False))


class HasItem(ExitInteraction):
    """An exit usable only while the character carries an item (a key).

    Configure the asset:

        exit.interaction = HasItem.dotted_path()
        exit.interaction_options = {"asset_id": "BRASS_KEY"}

    The exit stays listed - the player can see the locked door - and
    `usable` is what refuses them, with the default refusal message (or
    the class's own `refusal`).
    """

    asset_id = None

    def usable(self, instance):
        key = self.asset_id or self.options.get("asset_id")
        if not key:
            return False
        return self.pc.inventory_items().filter(item__asset_id=key).exists()


def get_interaction_asset(obj):
    """Return the interactive asset that `obj` refers to.

    Args:
        obj: either an interactive asset (`Item`, `Exit`, ...) or a
            player-scoped record that points at one (`LocationItem`,
            `InventoryItem`).

    Returns:
        The asset, or None if `obj` does not lead to an interactive asset.
    """
    if isinstance(obj, InteractiveMixin):
        return obj
    return getattr(obj, "item", None)


def get_interaction(obj, pc=None):
    """Return the interaction for `obj`, ready to use.

    A single entry point for the view, the template tags and the admin, so all
    of them agree on how an object turns into behaviour.

    Args:
        obj: an interactive asset, or a player-scoped record that points at
            one.
        pc: the `PlayerCharacter` involved.  Defaults to the one on the
            record.

    Returns:
        An `InteractiveItem` instance, or None if there is no interaction.
    """
    if obj is None:
        return None

    if isinstance(obj, InteractiveMixin):
        return obj.get_interaction(pc=pc)

    asset = get_interaction_asset(obj)
    if asset is None:
        return None
    return asset.get_interaction(instance=obj, pc=pc)


def holder_type(obj):
    """Return the wire name for the type of `obj`.

    This is the `target_type` parameter the dispatch view expects when it is
    asked to interact with something, e.g. `"location_item"`.  Accepts either
    an instance or the model class itself.

    A player-scoped record names itself through its `wire_name` attribute, so
    a game that subclasses `InventoryItem` inherits the right name instead of
    needing to keep two in step. Anything else falls back to its underscored
    model name.
    """
    model = obj if isinstance(obj, type) else type(obj)
    wire_name = getattr(model, "wire_name", None)
    if wire_name:
        return wire_name

    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", model._meta.model_name).replace(
        "__", "_"
    )

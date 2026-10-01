"""Interactive behaviour for Nilpoint game assets.

An asset that a player can do something to - an `Item` today, and in due
course an `Exit` or a `Location` - stores the dotted path of an
`InteractiveItem` subclass in its `interaction` field.  That class is
instantiated on demand and answers three questions: which actions the player
may take, what to show for one, and what to do when it is chosen.

Declaring the behaviour as a class rather than as a dict of method names on
`Game` means the framework never has to look behaviour up by string, so
renames and typos are caught by the interpreter rather than at play time.  It
also means several items - in one game or in different games - can share a
single interaction class by inheritance instead of by copy-and-paste.

Design notes
------------

* Interaction classes are **not** Django models.  They are short-lived,
  stateless helpers built once per request; anything that varies per player
  belongs in `item_state` (see `StatefulMixin`).
* The set of actions is *declared* on the class using `Action`, so the
  framework can enumerate actions for button rendering, admin display and
  validation without inspecting method names.
* Behaviour is ordinary Python.  Subclasses override `can`, `show` and
  `handle`, or attach a small callable to a single `Action` when a class only
  offers one or two things.
* Games should keep their interaction classes in `<app>/interactions.py`.
  The dotted path is stored in the database, so moving or renaming a class is
  a breaking change that needs a release step; `nilpoint_check` reports the
  paths in use and will fail loudly on one that no longer imports.

Example
-------

    # cypherpunk/interactions.py
    from nilpoint.interactions import Action, InteractiveItem

    class MysteryDevice(InteractiveItem):
        \"\"\"A device that can be pushed once, then switched off again.\"\"\"

        show_partial = "cypherpunk/interact/mystery_device.jinja2#device"

        actions = [
            Action("push_button", label="Push button"),
            Action("turn_off", label="Turn off"),
        ]

        def can(self, instance, action):
            if not instance.is_in_inventory:
                return False
            return bool(instance.item_state.get("pushed")) == (action == "turn_off")

        def handle(self, instance, action, request):
            instance.item_state.put("pushed", action == "push_button")
            return "Device activated" if action == "push_button" else "Device off"

    # cypherpunk/models.py, in a release step
    @release_step(7)
    def add_mystery_device(self):
        Item.objects.create(
            game=self,
            asset_id="MYSTERY_DEVICE",
            name="Mystery Device",
            description="A mysterious device with a button labelled 'push me'",
            interaction=MysteryDevice.dotted_path(),
            interaction_options={"charges": 3},
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

    Developer Usage:

        class Item(InteractiveMixin, GameAsset):
            ...

        # in a release step
        device.interaction = MysteryDevice.dotted_path()
        device.save()

        # anywhere you need the behaviour
        interaction = device.get_interaction(instance=some_location_item)
        if interaction and interaction.can(some_location_item, "push_button"):
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

    class Meta:
        abstract = True

    def get_interaction_class(self):
        """Resolve `interaction` to the class it names.

        Returns:
            The `InteractiveItem` subclass, or None if this asset has no
            interaction configured.

        Raises:
            UnresolvableInteraction: if the stored path will not import, or
                names something that is not an `InteractiveItem` subclass.
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

        if not (
            isinstance(interaction_class, type)
            and issubclass(interaction_class, InteractiveItem)
        ):
            raise UnresolvableInteraction(
                f"{type(self).__name__} '{getattr(self, 'asset_id', self.pk)}' "
                f"in game '{self.game.nilpoint_slug}' names interaction "
                f"'{self.interaction}', which is not an InteractiveItem subclass"
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

    Actions are declared on an `InteractiveItem` subclass (as its `actions`
    class attribute) so that the framework can enumerate them - for button
    rendering, admin display and request validation - without the class having
    to implement anything for the simple cases.

    Attributes:
        name: The action name, as sent to the dispatch view.  Unique within
            one interaction class, and part of the wire protocol, so treat it
            as permanent once released.
        label: The text shown on the button.  Defaults to a title-cased
            version of `name`.
        show: Template partial (`"app/template.jinja2#fragment"`) rendered for
            this action.  Defaults to the class's `show_partial`.
        can: Optional `callable(instance) -> bool` gating this action alone.
            Ignored if the class overrides `InteractiveItem.can()`.
        handle: Optional `callable(instance, request)` implementing the action.
            If absent, the class's `InteractiveItem.handle()` is used.
        description: Optional prose, shown in admin listings.
    """

    __slots__ = ("name", "label", "show", "can", "handle", "description")

    def __init__(
        self, name, label=None, show=None, can=None, handle=None, description=""
    ):
        self.name = name
        self.label = label
        self.show = show
        self.can = can
        self.handle = handle
        self.description = description

    @property
    def display_label(self):
        """The button text for this action: its label, or one derived from its name."""
        return self.label or self.name.replace("_", " ").title()

    def __repr__(self):
        return f"Action({self.name!r}, label={self.label!r})"


class InteractiveItem:
    """Base class for the behaviour of an interactive asset.

    Subclasses declare their `actions` and override `can`, `show` and `handle`.
    They are not Django models and they hold no state: an instance is built per
    request, and per-player data belongs in the `item_state` of the
    `LocationItem`/`InventoryItem` passed in as `instance`.

    Attributes:
        show_partial: Default template partial for every action that does not
            set its own `show`.  Actions that need no UI can leave this None.
        labels: Optional name -> label overrides, for classes that would
            rather not build `Action` objects by hand.
        actions: The declared `Action` list, or None if `get_actions()` is
            overridden to compute it.
    """

    show_partial = None
    labels = {}
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
        The default returns the `actions` class attribute, with any entries
        given as bare names in `labels` promoted to `Action` objects.
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

        This is what the UI renders buttons for.  Actions whose `can` gate
        refuses them are left out.
        """
        instance = instance if instance is not None else self.instance
        available = []
        for action in self.get_actions():
            try:
                allowed = self.can(instance, action)
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
            True if the action may be taken.  The default defers to a `can`
            callable attached to the action, and otherwise allows it.

        Note:
            Override this to gate several actions at once.  Overriding it
            means `can` callables attached to individual actions are ignored.
        """
        if action.can is not None:
            return bool(action.can(instance))
        return True

    def show(self, instance, action):
        """Return the template partial to render for `action`.

        Returns:
            A `"app/template.jinja2#fragment"` string, or None if the action
            has no UI of its own.  The default uses the action's `show`, then
            the class's `show_partial`.
        """
        if action.show:
            return action.show
        return self.show_partial

    def handle(self, instance, action, request):
        """Perform `action`.

        Args:
            instance: the player-scoped record for this player.
            action: the `Action` to perform.
            request: the current `HttpRequest`.

        Returns:
            None to have the framework re-render `show()` with the new state,
            a string to send that text back to the player, or an
            `HttpResponse` (such as `HtmxTriggerResponse`) to return it as-is.

        Raises:
            NotImplementedError: if neither the action nor the class
                implements the behaviour.
        """
        if action.handle is not None:
            return action.handle(instance, request)
        raise NotImplementedError(
            f"{type(self).__name__} has no behaviour for action '{action.name}'. "
            f"Implement handle() or attach a callable to the Action."
        )

    def get_context(self, instance, action):
        """Extra template context for `show()` renders.

        Return a dict to be merged into the context the framework passes to the
        partial.  `instance`, `item`, `action`, `state`, `pc` and
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
            A list of dicts with `name`, `label` and `show` per action.
        """
        return [
            {
                "name": action.name,
                "label": action.display_label,
                "show": action.show or self.show_partial,
            }
            for action in self.get_actions()
        ]


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

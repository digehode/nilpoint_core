"""Core models for nilpoint"""

from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import reverse
from django.apps import apps

from model_utils.managers import InheritanceManager
from .nilpoint_settings import nilpoint_settings

# TODO: move to using InheritanceManager in game instead of custom downcast functions?


def get_model(game, archetype):
    """Uses nillpoint_settings to return the appropriate class for the
    archetype, or the default if none has been set in settings.py.

    An archetype is the default Nilpoint class for things like
    PlayerCharacter. For a game built upon Nilpoint, there are likely
    to be classes that need to be customised through inheritence. To
    ensure the instances are created with the right type, the
    archetype can be substituted in settings.py.
    """

    # Get the string configuration (e.g., 'my_other_app.MyModel')
    model_string = nilpoint_settings.get_archetype(game, archetype)
    # Dynamically resolve it to the actual Python class
    # This is safe to call now because the app registry is fully loaded at runtime
    ConfiguredModel = apps.get_model(model_string, require_ready=True)
    return ConfiguredModel


class Game(models.Model):
    """The top-level Game object, to which all other game items will refer.

    Subclass to create new games. Override the 'get_name' function to
    identify the game. 'instance_name' is used to distinguish between
    multiple instances of the same game on a given server.

    """

    objects = InheritanceManager()
    name = "Generic Game"
    description = "This is a generic game. You should be subclassing "
    "this to create actual games. Or, if you have and you're still seing "
    "this, make use of the 'get_real_instance' method to get the downcast "
    "version of this object."

    instance_name = models.CharField(
        max_length=100,
        null=False,
        blank=False,
        help_text="The name of this game instance",
    )

    instance_description = models.TextField(
        null=False,
        blank=True,
        help_text="Description of the game instance",
    )

    nilpoint_slug = models.SlugField(
        help_text="A unique string that identifies this game in URLs",
        null=False,
        unique=True,
    )

    allow_multiple_characters = models.BooleanField(
        help_text="Can a player have multiple player characters in this game?",
        blank=False,
        default=False,
    )

    default_location_graphic = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Static path to default location graphic. Uses nilpoint default if not set.",
        default=None,
    )

    default_item_graphic = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Static path to default item graphic. Uses nilpoint default if not set.",
        default=None,
    )

    css = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Path for including game-specific css",
    )

    release = models.IntegerField(
        help_text="Current release of the game instance. Ties in with the game definition so updates can be applied progressively",
        null=False,
        blank=False,
        default=0,
    )

    # Game type holds the subclass to which this can be downcast
    _game_type = models.CharField(max_length=50, editable=False)

    def initialise_player_character(self, pc):
        """When a new player character is created for this game, this function is called to set them up ready to play.

        Includes inventory items, location items, etc.
        """

        # TODO: replace or supercede with data migrations or fixtures of some sort?

        pass

    def initialise_game_instance(self):
        """When a game instance is created, this function is used to initialise things like associated locations,
        items, etc."""

        pass

    def save(self, *args, **kwargs):
        """Checks and automatically sets, if necessary, the _game_type"""
        if not self._game_type:
            # Automatically set the type based on the class name
            self._game_type = self.__class__.__name__.lower()
        # TODO: set the default location and item graphics if they're None
        super().save(*args, **kwargs)

    def get_real_instance(self):
        """Dynamically fetch the game subclass instance of the Game object"""
        if hasattr(self, self._game_type):
            return getattr(self, self._game_type)
        return self

    def __str__(self):
        return f"{self.get_real_instance().name} - {self.instance_name}"

    def get_dispatch_url(self):
        """Get the dispatch URL for the game"""
        if self.nilpoint_slug is not None and self.nilpoint_slug != "":
            return reverse(
                f"{self._game_type}:dispatch",
                kwargs={"nilpoint_slug": self.nilpoint_slug},
            )
        else:
            return "#"

    def get_player_characters(self, user, game):
        """Returns a list of player characters for the current user and current game.

        If the user doesn't have a player object, returns an empty list.
        """
        try:
            player = Player.objects.get(user=user)
            characters = (
                PlayerCharacter.objects.filter(player=player, game=game)
                .select_subclasses()
                .all()
            )
            return characters
        except Player.DoesNotExist:
            return []

    def get_initial_location(self):
        """Return the initial location for the game, or None if there isn't one"""
        return self.locations.filter(initial=True).first()

    def latest_release(self):
        """Subclasses use this to return the current latest release.

        Release 0 is always blank. All subclasses should include release_update_x for each release, x.
        """
        return 0

    def _get_migration_map(self):
        """Discovers all methods decorated with @release_step."""
        migration_map = {}
        for attr_name in dir(self):
            method = getattr(self, attr_name, None)
            if callable(method) and hasattr(method, "_target_release"):
                migration_map[method._target_release] = method
        return migration_map

    def update_release(self):
        """Updates to the next release"""
        migration_map = self._get_migration_map()
        current = self.release
        latest = self.latest_release()
        if current == latest:
            return current
        if current > latest:
            raise Exception(
                f"Current release ({current}) is higher than latest release ({latest})"
            )

        target = current + 1

        update_method = migration_map.get(target)
        if not callable(update_method):
            raise NotImplementedError(
                f"No migration step defined for release {target} "
                f"on {self.__class__.__name__}."
            )

        update_method()


class Player(models.Model):
    """Represents a player

    Refers to a user for uniquely identifying the person

    Contains all aspects that are not specific to a single game that
    are not part of the user model.

    This should be subclassed to include any instance specific things.

    """

    user = models.OneToOneField(
        get_user_model(), null=False, on_delete=models.CASCADE, related_name="player"
    )

    def __str__(self):
        return self.user.username


class Location(models.Model):
    """Represents a location in the game."""

    objects = InheritanceManager()

    name = models.CharField(
        help_text="A short name of the place, will be shown to the user",
        max_length=100,
        null=False,
        blank=False,
    )
    description = models.TextField(
        null=False,
        blank=True,
        help_text="Description of the location",
    )
    game = models.ForeignKey(
        Game, null=False, on_delete=models.CASCADE, related_name="locations"
    )
    graphic = models.CharField(
        help_text="Static path for the graphic", max_length=100, null=True, blank=True
    )
    initial = models.BooleanField(
        help_text="Is this the starting location?",
        blank=False,
        default=False,
    )

    @property
    def graphic_safe(self):
        if not self.graphic:
            return self.game.default_location_graphic
        return self.graphic

    def __str__(self):
        return f"Location {self.id} - {self.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game"],
                condition=models.Q(initial=True),
                name="unique_initial_location_per_game",
            )
        ]


class Exit(models.Model):
    """Represents a way out of the current location"""

    name = models.CharField(
        help_text="A name for the exit",
        max_length=100,
        null=False,
        blank=False,
    )

    exit_from = models.ForeignKey(
        Location, null=False, on_delete=models.CASCADE, related_name="exits"
    )
    exit_to = models.ForeignKey(
        Location, null=False, on_delete=models.CASCADE, related_name="entrances"
    )

    def create_two_way_exit(location1, name1, location2, name2):
        e1 = Exit(name=name1, exit_from=location1, exit_to=location2)
        e2 = Exit(name=name2, exit_from=location2, exit_to=location2)
        e1.save()
        e2.save()
        return (e1, e2)


class PlayerCharacter(models.Model):
    """Represents a player for a given game

    Refers to the generic Player and through that to a user.

    Links game-specific data such as preferences, progress, etc.

    Can be sub-classed for specific instances, but the goal is to keep
    this fairly generic and use foreign-keys in game-specific
    models/views/etc. to refer to the character.

    """

    objects = InheritanceManager()

    handle = models.CharField(max_length=100, null=False, blank=False)
    player = models.ForeignKey(
        Player, null=False, on_delete=models.CASCADE, related_name="characters"
    )
    game = models.ForeignKey(
        Game, null=False, on_delete=models.CASCADE, related_name="player_characters"
    )
    current_location = models.ForeignKey(
        Location,
        null=True,
        on_delete=models.SET_NULL,
    )

    release = models.IntegerField(
        help_text="Current release of the game instance to which this PC is updated. Ties in with the game definition so updates can be applied progressively",
        null=False,
        blank=False,
        default=0,
    )

    def _get_migration_map(self):
        """Discovers all methods decorated with @release_step."""
        migration_map = {}
        for attr_name in dir(self):
            method = getattr(self, attr_name, None)
            if callable(method) and hasattr(method, "_target_release"):
                migration_map[method._target_release] = method
        return migration_map

    def update_release(self):
        """Updates to the next release"""
        # TODO: check against game instance
        migration_map = self._get_migration_map()
        current = self.release
        latest = self.game.release
        if current == latest:
            return current
        if current > latest:
            raise Exception(
                f"Current PC release ({current}) is higher than latest game release ({latest})"
            )

        target = current + 1
        if target > latest:
            raise Exception(
                f"PC {self.id} ({self.handle}) can't update beyond current game release ({latest})."
            )
        update_method = migration_map.get(target)

        # While games need a contiguous version progression, PlayerCharacters don't
        # If there isn't a function for the current release, we just push up the release number
        if callable(update_method):
            update_method()
        else:
            self.release += 1
            self.save()

    def __str__(self):
        return f"PC({self.handle}) in {self.game.instance_name}"


class Item(models.Model):
    """An item that exists in the world or an inventory.

    This is the ideal of the item. It can be linked to a location or
    inventory, using the LocationItem or InventoryItem to represent a
    real/interactable version of the item.

    Instances of this model are shared by all players and no player or
    location data is associated here.

    """

    objects = InheritanceManager()

    name = models.CharField(
        help_text="A short name of the item, will be shown to the user",
        max_length=100,
        null=False,
        blank=False,
    )
    description = models.TextField(
        null=False,
        blank=False,
        help_text="Description of the item",
    )
    game = models.ForeignKey(
        Game, null=False, on_delete=models.CASCADE, related_name="items"
    )
    graphic = models.CharField(
        help_text="Static path for the graphic", max_length=100, null=True, blank=True
    )

    @property
    def graphic_safe(self):
        if not self.graphic:
            return self.game.default_item_graphic
        return self.graphic


class LocationItem(models.Model):
    """For a given player character and location, represents the presence of an item."""

    location = models.ForeignKey(
        Location, null=False, on_delete=models.CASCADE, related_name="items"
    )
    pc = models.ForeignKey(
        PlayerCharacter,
        null=False,
        on_delete=models.CASCADE,
        related_name="location_items",
    )
    item = models.ForeignKey(
        Item, null=False, on_delete=models.CASCADE, related_name="locations"
    )


class InventoryItem(models.Model):
    """For a given player character represents the presence of an item in the inventory."""

    pc = models.ForeignKey(
        PlayerCharacter, null=False, on_delete=models.CASCADE, related_name="inventory"
    )
    item = models.ForeignKey(
        Item, null=False, on_delete=models.CASCADE, related_name="inventories"
    )

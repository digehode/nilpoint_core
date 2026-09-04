"""Core models for nilpoint"""

from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import reverse
from django.apps import apps

from model_utils.managers import InheritanceManager
from .nilpoint_settings import nilpoint_settings

# TODO: move to using InheritanceManager in game instead of custom downcast functions?

# TODO: Add a unique key to the Location model and use that for player locations, etc.  This way we can create a setup function in a game that initialises locations, etc.  Do the same for things like PlayerCharacter, etc.  This will allow us to create a game setup script that can be run to create the initial game state, but also allow it to be rerun if we make changes to the game setup, version updates, etc.  Possibly replicate some migration process later on. If we try to just use DB ids, then we can't easily rerun the setup script without breaking things.  We can provide some functions like "create or update location" "create or update item" etc. to use in the setup funciton.


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

    css = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Path for including game-specific css",
    )

    # Game type holds the subclass to which this can be downcast
    _game_type = models.CharField(max_length=50, editable=False)

    def save(self, *args, **kwargs):
        """Checks and automatically sets, if necessary, the _game_type"""
        if not self._game_type:
            # Automatically set the type based on the class name
            self._game_type = self.__class__.__name__.lower()
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

    np_key = models.CharField(help_text="A unique key for this location", max_length=100, null=False, blank=False, unique=True)

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

    def __str__(self):
        return f"PC({self.handle}) in {self.game.instance_name}"

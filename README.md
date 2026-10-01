---
title: Nilpoint
subtitle: A Django engine for building adventure and narrative web games
---

# Nilpoint

## Introduction

Nilpoint is an adventure game engine for Django. It allows the creation of games that involve exploration through multiple locations, an inventory and progression through conditions such as having collected an item, answered a riddle, etc.

Most of Nilpoint can be subclassed to add game-specific functionality, and multiple games can be run on a single server.

Games can be played by multiple people, each exploring their own version of the game world.

Nilpoint was created to enable the game "Cyperpunk", an adventure game of cryptography and cryptanalysis.

## Overview -TODO

- Nilpoint is a reusable core package for adventure games.
- It provides shared models, views, templates, and release/update logic
- It is designed to be extended by game-specific apps

## Core concepts

### Game

A Game in Nilpoint is a class that ties together all objects, player characters, locations, etc.  Instances of each game object will be the same, but can have different players in different states of play.

Different kinds of game are created by subclassing the core Game object.

### Player

A Player is an adapter from whatever user model your Django project is using to Nilpoint.  It doesn't currently do much other than sit between the user model and Nilpoint's models, but that may change in future.

A Player object is referred to by PlayerCharacter objects.

### PlayerCharacter

A PlayerCharacter is a Player's character in a given game.  Games may allow a single Player to have multiple PlayerCharacters, or not. If Player plays multiple games, they will have a PlayerCharacter for each of them.

PlayerCharacters have a "handle" which is the name that the game will use for them.  They also keep track of the location of the player in the game, and are referred-to by any records that relate to a single player in a given game, such as inventory items, etc.

When a new PlayerCharacter is created, it creates all of the records required by the intersection of a player and a game. This could be LocationItems, InventoryItems, etc.

### Location

A Location is a place in a Game.  When a Game instance is created, all of its locations are instantiated too. So if you have two instances of a single game, the locations will be instantiated twice.  This allows for some level of customisation between game instances, such as changing location names, graphics, etc.

### Exit

An exit joins two locations in a single direction.  There is a utility function (`Exit.create_two_way_exit(...)` to simplify making a bidirectional exit between two locations.

### Item

Items are ideals of things that exist in the world. If multiple players have item X in their inventory, they are all referring to one Item object for that game through individual InventoryItem objects.  Similarly, if an item appears in a location, players interact with a LocationItem rather than the Item itself.

### InventoryItem / LocationItem

InventoryItem and LocationItem are how Items become visible, manipulable by players.  If an Item for a game should exist at a location, each player will need a LocationItem that maps the Location to the Item.  If they pick it up, the LocationItem for that player is deleted and an InventoryItem is created.  Other players will see no effect.

### GameAsset

GameAsset is an abstract class that classes related to a game inherit from. The purpose is to add a layer of unique ID to the asset that is unrelated to database IDs and in a scheme decided by the game creator. The goal is to allow assets to be found quickly in a way that makes sense to the creator.  This is particularly important when creating new characters, updating game items, etc.

For example, we may need to give each new PlayerCharacter an Item. The Item will exist, but the unique DB key is likely to be different on the production system than it was on the developer system.  The name of the item may also have changed since the game was instantiated.  When the Item was created, along side the user-facing data such as it's name and description, and in addition to the automatic DB id assignment, it would have been given an asset_id, dictated by the GameAsset class.  The Game class has a `get_asset` method that will find the right object based on this ID, restricted to objects related to the current game instance.

### PlayerScoped

`PlayerScoped` is an abstract base class (mirror of `GameAsset`) for player-scoped state records like `LocationItem` and `InventoryItem`. It provides:

- A `pc` ForeignKey to `PlayerCharacter` (guaranteed on all subclasses)
- `PlayerScopedManager` with `for_character(pc)` method for scoped queries
- Convenience methods on `PlayerCharacter`: `items_at(location)` and `inventory_items()`

New game state models should subclass `PlayerScoped` rather than reimplementing per-character filtering.

### StatefulMixin & ItemState

`StatefulMixin` provides per-instance state for any model (e.g., `LocationItem`, `InventoryItem`, future machines). It adds:

- `item_state` property — dict-like access to per-instance state (`get`, `put`, `pop`, `keys`, `len`, `in`, iteration)
- `transfer_state_to(other)` — copies state to another instance
- `transfer_item_state(from, to)` — standalone helper for take/drop

State is stored in `ItemState` model (GenericForeignKey + pickled BinaryField), allowing flexible per-instance schemas without migrations.

New stateful models inherit `StatefulMixin` and automatically get `item_state` property.

### Item interactions

An item can be made interactive by naming an `InteractiveItem` subclass in its
`interaction` field. That class owns everything the player can do with the
item: the action list, which actions are currently available, the partial
rendered for each one, and what happens when an action is chosen. Nothing
about a specific item's behaviour lives in core or in the `Game` subclass any
more.

Interaction classes are plain Python classes (not Django models); several
items may share one class, and per-player state belongs in `item_state` (see
`StatefulMixin`), just like the old hooks.

**The three phases:**

| Phase | Purpose | Returns |
|-------|---------|---------|
| `can` | Gate the action (check state, location, etc.) | `True`/`False` |
| `show` | Render a partial for HTMX inclusion (e.g., a panel with action buttons) | Template path string (e.g., `"mygame/interact/squeeze.jinja2#show"`) |
| `handle` | Execute the action when triggered | String message, `HtmxTriggerResponse`, or `None` |

The `can` gate is always enforced by the view before `handle` runs, not just by
the buttons in the UI. A `handle` that returns a string sends that text to the
player, one that returns an `HttpResponse` is used as-is (its triggers survive),
and one that returns `None` re-renders the partial so the new state shows.

**Define an interaction class:**

```python
# mygame/interactions.py
from nilpoint.interactions import Action, InteractiveItem

class Wotsit(InteractiveItem):
    show_partial = "mygame/interact/wotsit.jinja2#show"

    actions = [Action("squeeze", label="Squeeze")]

    def can(self, instance, action):
        return instance.item_state.get("charges", 0) > 0

    def handle(self, instance, action, request):
        charges = instance.item_state.get("charges", 0)
        instance.item_state.put("charges", charges - 1)
        return f"Squeezed! Charges left: {charges - 1}"
```

- `instance` is the `LocationItem`/`InventoryItem` the player is acting on
  (use `instance.item_state` for state, `instance.is_in_inventory` to ask where it is).
- For a class with a single simple action, the behaviour can go straight on the
  `Action`: `Action("read", label="Read it", handle=my_callable)`.
- `get_actions()` may be overridden to compute the action list from
  `self.options` (the item's `interaction_options` JsonField).

**Wire it up in a release step:**

```python
@release_step(7)
def add_wotsit(self):
    Item.objects.create(
        game=self,
        asset_id="WOTSIT",
        name="A Wotsit",
        description="A little worn but functional",
        interaction=Wotsit.dotted_path(),
        interaction_options={"charges": 3},  # optional per-item config
    )
```

Use `Wotsit.dotted_path()` (never a hand-typed string) so renames are caught by
your IDE. Moving or renaming an interaction class is a breaking change: it
needs a release step that rewrites affected items' `interaction` field. The
`nilpoint_check_interactions` management command resolves every configured
interaction and fails on any that no longer import, so the problem shows up in
development rather than in play.

**Dispatch from the client (HTMX):**

The `handle_interact` view is registered as action `"interact"` in
`NilpointGameBasic`. It runs the three phases via POST with parameters
`target_type` (`location_item`, `inventory_item`, or any other interactive
asset type), `object_id`, `action`, and `phase`.

```html
<!-- Show phase: render action UI -->
<button hx-post="{% nilpoint_action_url game 'interact' %}"
        hx-vals='{"target_type": "location_item", "object_id": {{ li.id }}, "action": "squeeze", "phase": "show"}'
        hx-target="#interaction-panel">
  Squeeze
</button>

<!-- Handle phase: execute action -->
<button hx-post="{% nilpoint_action_url game 'interact' %}"
        hx-vals='{"target_type": "location_item", "object_id": {{ li.id }}, "action": "squeeze", "phase": "handle"}'
        hx-target="#messages">
  Squeeze!
</button>
```

**Template tag for rendering available actions:**

```jinja2
{% load nilpoint_tags %}

{# Renders a button per action that passes its "can" check, for any
   interactive record (LocationItem, InventoryItem, or an interactive asset) #}
{% nilpoint_interact_actions location_item target="#interaction-panel" %}
```

The `nilpoint_check_interactions` command also summarises configured
interactions (`--actions` lists each class's actions; `--game <slug>` limits by
game).

### Item take/drop mechanics

## Game archetypes and model overrides

A Nilpoint game is created by subclassing the models.Game class and any required related classes, and subclassing the views.NilpointGameBasic view.

The Game subclass deals with all of the game setup and various bits of behaviour while the view handles requests to interact with game state.

Some game classes get instantiated by core Nilpoint logic and subclasses need to be registered in order for this logic to use the correct one.

The Nilpoint settings module (nilpoint.nilpoint_settings) handles this.

## Architecture - TODO
- Django app package layout
- Model-first design
- View layer for game flow
- Templates and admin integration
- Settings-driven customization

## How it works - TODO
- A game instance is represented as a Game object
- Each game can have multiple locations, exits, items, and player characters
- A player belongs to a user and may have characters in one or more games
- Core gameplay state is stored in database models, not in a custom runtime engine
- The game view stack loads the game by nilpoint_slug and renders common interaction states
- HTMX is used for partial UI updates and trigger-based UI responses

## Game lifecycle and releases - TODO
- Each game and player character carries a release number
- Release migrations are managed through @release_step
- This allows incremental data/model changes as game content evolves
- nilpoint_update_game can apply updates to existing game data

## Configuration and extension

### Template partial overrides via `_value_from_subclass_or_default`

`NilpointGameBasic` provides a simple override mechanism for template partials. Each handler that renders a template checks for a corresponding class attribute on the view subclass; if present, that partial is used instead of the default.

```python
# In your game's views.py
from nilpoint.views import NilpointGameBasic

class MyGameView(NilpointGameBasic):
    # Override any of these to supply your own template partials:
    landing_partial = "mygame/landing.jinja2#landing"
    overview_partial = "mygame/overview.jinja2#overview"
    location_graphic_partial = "mygame/location_graphic.jinja2#location_graphic"
    player_location_panel = "mygame/player_location.jinja2#player_location_panel"
    location_item_panel = "mygame/location_items.jinja2#location_item_panel"
    item_detail_partial = "mygame/item_detail.jinja2#item_detail"
    new_player_character_partial = "mygame/new_pc.jinja2#new_player_character"
    new_player_character_submit = "mygame:new_pc_submit"  # URL name for form POST
```

The core view's `_value_from_subclass_or_default(name, default)` method does the lookup: it checks `hasattr(self, name)` and returns the subclass's value if it exists, otherwise the provided default string.

#### Handler to attribute mapping

| Handler | Attribute | Default partial |
|---------|-----------|-----------------|
| `handle_landing` | `landing_partial` | `nilpoint/game_landing.jinja2#landing` |
| `handle_overview` | `overview_partial` | `nilpoint/game_overview.jinja2#game_overview` |
| `handle_get_location_graphic` | `location_graphic_partial` | `nilpoint/location_panel.jinja2#location_graphic` |
| `handle_get_player_location_panel` | `player_location_panel` | `nilpoint/player_location_panel.jinja2#player_location_panel` |
| `handle_get_location_item_panel` | `location_item_panel` | `nilpoint/location_item_panel.jinja2#location_item_panel` |
| `handle_get_inventory_panel` | `inventory_panel` | `nilpoint/inventory_item_panel.jinja2#inventory_panel` |
| `handle_item_detail` | `item_detail_partial` | `nilpoint/location_item_panel.jinja2#item_detail` |
| `handle_new_player_character` | `new_player_character_partial` | `nilpoint/new_player_character.jinja2#new_player_character` |
| `handle_new_player_character` | `new_player_character_submit` | auto-derived dispatch URL |

This keeps handler logic in core while letting game apps swap templates freely.

### Template Tags for HTMX Patterns

Nilpoint provides template tags in `nilpoint_tags` to simplify common HTMX patterns:

```jinja2
{% load nilpoint_tags %}

{# Panel that loads via GET on trigger #}
{% nilpoint_panel "nilpoint-scene" "get_location_graphic"
   triggers="load, player_location_changed from:body" %}

{# Action link with correct HTTP method #}
{% nilpoint_action "Detail" "item_detail" item=item.id
   target="#nilpoint-item-detail-panel" %}
{% nilpoint_action "Take" "take_item" method="post" location_item=li.id %}

{# Form that GETs on load, POSTs on submit #}
{% nilpoint_form "new-pc-form" "new_player_character" %}
```

**Available tags:**

| Tag | Purpose | Key Parameters |
|-----|---------|----------------|
| `nilpoint_panel` | HTMX panel div (GET) | `panel_id`, `action`, `triggers`, `target`, `swap` |
| `nilpoint_action` | Action link/button | `text`, `action`, `method`, `target`, `swap`, `classes` |
| `nilpoint_form` | Form (GET+POST) | `form_id`, `action`, `method`, `target`, `swap` |
| `nilpoint_interact_actions` | One button per available interaction action | `instance`, `show_phase`, `target`, `swap`, `classes` |

All tags auto-generate the dispatch URL from the `game` in context.

### NILPOINT_SETTINGS usage example - TODO
- Overriding PlayerCharacter or other core models
- Registering game content types
- Using custom subclasses per game

## Installation - TODO
- Install package
- Add to INSTALLED_APPS
- Add Nilpoint URLs
- Configure Django settings
- Set up NILPOINT_SETTINGS

## Example usage - TODO
- Creating a game instance
- Defining a game-specific player character subclass
- Registering game model classes
- Loading a game by slug
- Rendering the game landing page

## Management commands - TODO
- nilpoint_list_games
- nilpoint_update_game
- Example output and usage

## Project structure - TODO - needed?
- src/nilpoint/
  - models.py
  - views.py
  - forms.py
  - decorators.py
  - nilpoint_settings.py
  - admin.py
  - templates/
  - management/commands/
  - tests/

## Limitations / current status - TODO
- Early-stage package
- Requires a host Django project
- Not a standalone game server
- Still has placeholder/rough areas and TODOs

## Credits / attribution - TODO
- Link to ATTRIBUTION.md
- Django and HTMX, etc.

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
`interaction` field. That class owns the judgement and identity of the
interaction: the action list, which actions are currently available (`can`),
the panel shown for the interaction, and the extra context it needs. The
*effect* of each action lives on the `Action` itself (`handle`). Nothing about
a specific item's behaviour lives in core or in the `Game` subclass any more.

Every interaction renders exactly one **panel** - its `partial` attribute -
decided at class level so every action behaves the same way. The default
partial is one stacked button per available action, a click each. A class with
an interface of its own (a device panel, a status readout) sets `partial` to
its own template, and the actions live inside that one partial. An interaction
with no actions at all still has a panel (the default renders "No actions
available"), which is how a status-only interaction shows its readout.

The panel is **always shown**: the item detail renders the
`nilpoint_interaction_panel` tag, which emits a div that auto-loads
the partial into `#nilpoint-interaction-panel` via htmx. I've moved
back and forth on how to do this but I think this is the best bet.

Interaction classes are plain Python classes (not Django models); several
items may share one class, and per-player state belongs in `item_state` (see
`StatefulMixin`), just like the old hooks.

#### Hooks

| Where | Method | Purpose | Default |
|-------|--------|---------|---------|
| Interaction | `can(instance, action)` | The authoritative gate: offer `action`? (state, inventory, location...) | allows everything |
| Action | `can(instance, interaction)` | The action's own gate, for what it can judge about itself | allows everything |
| Action | `handle(instance, interaction, request)` | Execute the action when triggered | raises `NotImplementedError` |

Both `can` gates are enforced by the view before `handle` runs, not just by
the buttons in the UI. After `handle` runs the interaction area always
re-renders the panel, so an action never replaces the UI with its own output.
The return value only contributes a message to the player log: a returned
string appears as-is, the text content of a returned `HttpResponse` is logged
(any triggers it set, e.g. panel refreshes, survive), and `None` means no
message.

A small library of generic `Action`s covers the common effects - `StateToggle`
flips a boolean, `SetState` pins a key to a value - each configured by
declaring a `state_key` and a message. Anything else is a small `Action`
subclass next to the interaction that uses it.

#### How to define an interaction class

```python
# mygame/interactions.py
from nilpoint.interactions import InteractiveItem, SetState

class Wotsit(InteractiveItem):
    partial = "mygame/interact/wotsit.jinja2#show"

    actions = [
        SetState("squeeze", label="Squeeze", state_key="charges", value=2,
                 message="Squeezed!"),
    ]

    def can(self, instance, action):
        return instance.item_state.get("charges", 0) > 0

    def get_context(self, instance):
        # Extra template context for the panel partial.
        return {"charges": instance.item_state.get("charges", 0)}
```

- `instance` is the `LocationItem`/`InventoryItem` the player is acting on
  (use `instance.item_state` for state, `instance.is_in_inventory` to ask where it is).
- An action reads and writes its declared key with `self.get_state(instance)`
  / `self.set_state(instance, value)`; hand-written actions reach the whole
  picture through `interaction` (the `pc`, the item's `options`, the asset).
- `partial` is a `"app/template.jinja2#fragment"` string. The default is the
  framework's buttons panel; leave it alone for that. Inside a custom partial,
  `{% nilpoint_interact_actions instance %}` renders the buttons.
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
`NilpointGameBasic`. It accepts GET or POST with parameters `target_type`
(`location_item`, `inventory_item`, or any other interactive asset type),
`object_id`, and optionally `action_name`. The interaction action travels as
`action_name` because `action` in the query string is the dispatch router's
handler selector. A request with no `action_name` renders the panel - this is
what the item detail auto-loads, and it is not an action. A request with an
`action_name` is gated by `can` (both gates) and performed by the action's
`handle`, then re-renders the panel. Interface loads are GET requests; an
action that sends data (e.g. a code entry form) should POST it.

Most games never write interact requests by hand: the item detail renders the
whole interaction region for you.

```jinja2
{% load nilpoint_tags %}

{# The interaction panel: the interaction's `partial` auto-loads into
   #nilpoint-interaction-panel via a GET request (no action named) when the
   detail renders. #}
{% nilpoint_interaction_panel instance %}
```

Inside a custom interface partial, render the action buttons with:

```jinja2
{% nilpoint_interact_actions instance %}
```

The default `partial` does exactly this. Hand-written requests follow the same
shape:

```html
<!-- Panel load (GET, no action_name): show the interaction -->
<a hx-get="{% nilpoint_action_url game 'interact' %}"
   hx-vals='{"target_type": "location_item", "object_id": {{ li.id }}}'
   hx-target="#nilpoint-interaction-panel">
  Open
</a>

<!-- Perform an action (POST): sending data, e.g. a code from a form field -->
<button hx-post="{% nilpoint_action_url game 'interact' %}"
        hx-include="#code-form"
        hx-vals='{"target_type": "location_item", "object_id": {{ li.id }}, "action_name": "enter_code"}'
        hx-target="#nilpoint-interaction-panel">
  Submit code
</button>
```

The `nilpoint_check_interactions` command also summarises configured
interactions: `--actions` lists each class's actions and its partial,
`--game <slug>` limits by game.

### Player log messages

Any handler can send one or more short messages to the player through the same
response that refreshes the page panels. `HtmxTriggerResponse` keeps a
per-response message buffer: call `add_log_item(...)` as many times as you like
and every message is placed in the response before it is sent.

```python
response = HtmxTriggerResponse(content="Took the wotsit", content_type="text/plain")
response.add_log_item("You take the wotsit.")
response.add_log_item("It smells faintly of cheese.", level="info")
response.add_trigger("location_items_changed")
```

- `level` maps to a CSS class on the log entry: `success` (the
  default), `info`, or `error`. Feel free to send other classes, just
  make sure you add css to cover them in the browser.
- The default landing page has a `#nilpoint-log` panel; a small script
  listens for the `nilpoint_log` event that the response fires and
  appends one entry per message. If you write your own landing page,
  either steal the log script or do soemthign else with it that makes
  more sense for you.
- The log is ephemeral - nothing is stored in the database. It survives HTMX
  round-trips (the panel lives in the landing partial) but is lost on a full
  page load. Each response starts with an empty buffer, so a message from one
  request never leaks into the next.
  - THIS MAY CHANGE IN FUTURE. I'm considering using client side
    storage to hold them. Avoiding adding server side storage for now.
- The messages ride the `HX-Trigger` header, so buttons that only
  report via the log usually use `swap="none"` (see the take/drop
  buttons) - the message appears in the log instead of replacing the
  control that was clicked. Error is meant for errors the user should
  see, not system errors too: `response.add_log_item("That wotsit is
  too heavy to take", level="error")`. But it's up to you.

The log has no markup of its own, just plain CSS selectors, so a game can
restyle it by overriding the defaults:

| Selector | Purpose |
|----------|---------|
| `#nilpoint-log` | the log container (the box itself) |
| `#nilpoint-log::before` | the scanline overlay used by the default theme |
| `.nilpoint-log-entry` | a single logged message |
| `.nilpoint-log-entry.info` / `.success` / `.error` | the `level` class variant |

The default styling in `nilpoint.css` is a green-on-black terminal; a game can
restyle by overriding the same selectors, or hide the log entirely.

### Item take/drop mechanics

`handle_take_item` / `handle_drop_item` move an item by deleting the old
record and creating a fresh one in the new home, so the record's id does not
survive a move. Both responses trigger `inventory_items_changed` and
`location_items_changed`; moving through an exit triggers
`player_location_changed`.

The panels listen to those events and refresh themselves, and so does the
**item detail**: its `#nilpoint-item-detail` region re-requests the same
record whenever items move or the player changes location or character, so an
open detail never shows a stale copy. `handle_item_detail` is the gate — the
region **blanks** when the record is gone, or when
`_item_detail_is_accessible(instance, pc)` returns `False` (default: a
`LocationItem` must be where the character is; an `InventoryItem` is always
accessible). Override `_item_detail_is_accessible` on your view for your own
rules — an item that evaporates, a container that locks, and so on.
`item_detail_partial` names the content rendered inside that refresh wrapper.

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
| `handle_item_detail` | `item_detail_partial` (the content inside the refresh wrapper) | `nilpoint/item_detail_panel.jinja2#item_detail_content` |
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
| `nilpoint_interact_actions` | One button per available interaction action (each a GET with the action name); the default interaction panel | `instance`, `target`, `swap`, `classes` |
| `nilpoint_interaction_panel` | The item detail's interaction region: always auto-loads the interaction's `partial` | `instance` |

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

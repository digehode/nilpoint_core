---
title: Nilpoint
subtitle: A Django engine for building adventure and narrative web games
---

# Nilpoint

## Intro

Nilpoint is an adventure game engine for Django. It allows the creation of games that involve exploration through multiple locations, an inventory and progression through conditions such as having collected an item, answered a riddle, etc.

Most of Nilpoint can be subclassed to add game-specific functionality, and multiple games can be run on a single server.

Games can be played by multiple people, each exploring their own version of the game world.

Nilpoint was created to enable the game "Cyperpunk", an adventure game of cryptography and cryptanalysis.

## Overview
- Nilpoint is a reusable core package for adventure game backends
- It provides shared models, views, templates, and release/update logic
- It is designed to be extended by game-specific apps

## Core concepts
- Game
- Player
- PlayerCharacter
- Location
- Exit
- Item
- InventoryItem
- GameAsset
- Game archetypes and model overrides

## Architecture
- Django app package layout
- Model-first design
- View layer for game flow
- Templates and admin integration
- Settings-driven customization

## How it works
- A game instance is represented as a Game object
- Each game can have multiple locations, exits, items, and player characters
- A player belongs to a user and may have characters in one or more games
- Core gameplay state is stored in database models, not in a custom runtime engine
- The game view stack loads the game by nilpoint_slug and renders common interaction states
- HTMX is used for partial UI updates and trigger-based UI responses

## Game lifecycle and releases
- Each game and player character carries a release number
- Release migrations are managed through @release_step
- This allows incremental data/model changes as game content evolves
- nilpoint_update_game can apply updates to existing game data

## Configuration and extension
- NILPOINT_SETTINGS usage example
- Overriding PlayerCharacter or other core models
- Registering game content types
- Using custom subclasses per game

## Installation
- Install package
- Add to INSTALLED_APPS
- Add Nilpoint URLs
- Configure Django settings
- Set up NILPOINT_SETTINGS

## Example usage
- Creating a game instance
- Defining a game-specific player character subclass
- Registering game model classes
- Loading a game by slug
- Rendering the game landing page

## Management commands
- nilpoint_list_games
- nilpoint_update_game
- Example output and usage

## Project structure
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

## Limitations / current status
- Early-stage package
- Requires a host Django project
- Not a standalone game server
- Still has placeholder/rough areas and TODOs

## Credits / attribution
- Link to [ATTRIBUTION.md](ATTRIBUTION.md)
- Django and HTMX patterns?

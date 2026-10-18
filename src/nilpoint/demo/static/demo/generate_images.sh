#!/bin/sh
# Regenerates the demo's placeholder graphics with ImageMagick.
#
# Plain black images with white centered text stating what they are -
# deliberately minimal: they exist so every graphic path in the demo has
# something real to load, including the game's default location/item
# graphics (which the keypad, having no graphic of its own, falls back to).
#
# Requires ImageMagick 7 (`magick`).
set -eu
cd "$(dirname "$0")"

location() {
    magick -size 1600x900 xc:black -fill white -gravity center \
        -pointsize 96 -annotate 0 "$1" "locations/$2.png"
}

item() {
    magick -size 640x640 xc:black -fill white -gravity center \
        -pointsize 64 -annotate 0 "$1" "items/$2.png"
}

mkdir -p locations items

location "The Lobby" lobby
location "The Hallway" hallway
location "The Workshop" workshop
location "Default location graphic" default_location

item "Welcome note" welcome_note
item "Desk lamp" desk_lamp
item "Default item graphic" default_item

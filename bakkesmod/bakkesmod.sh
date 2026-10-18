#!/bin/bash
# Starts BakkesMod next to a running Rocket League (Epic, Heroic flatpak).
# install.sh fills in the paths and copies this to ~/Games/Heroic/rl-deck-kit/, which Heroic's
# flatpak can read. Run it inside the flatpak, after the game has reached the main menu:
#   flatpak run --command=bash com.heroicgameslauncher.hgl ~/Games/Heroic/rl-deck-kit/bakkesmod.sh
# It uses the game's own Proton Wine binary directly: a second umu/Proton container can't reach
# the game's wineserver, and Heroic's "script before launch" hook hangs the launch.
export WINEPREFIX="@PFX@"
export WINEFSYNC=1
export WINEDLLOVERRIDES="winemenubuilder.exe=d"
exec "@PROTON@/files/bin/wine" "C:\\Program Files\\BakkesMod\\BakkesMod.exe" \
    >"$HOME/Games/Heroic/rl-deck-kit/bakkesmod.log" 2>&1

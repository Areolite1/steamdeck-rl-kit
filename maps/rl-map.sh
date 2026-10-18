#!/bin/bash
# Picks which custom map Rocket League loads in place of Underpass (Labs_Underpass_P.upk).
# No argument: shows a list to choose from. "rl-map.sh restore" puts the real Underpass back.
# Change maps while Rocket League is closed or sitting in the main menu.
source "$HOME/.config/rl-deck-kit/paths.env" 2>/dev/null || { echo "Run install.sh first."; exit 1; }
MAPS="${RL_MAPS:-$HOME/Games/RL-Maps}"
UP="$RL_GAME_DIR/TAGame/CookedPCConsole/Labs_Underpass_P.upk"
ORIG="$MAPS/_original/Labs_Underpass_P.upk"

say() { kdialog --title "Rocket League maps" --msgbox "$1" 2>/dev/null || echo "$1"; }

# Keep the real Underpass once (a game update may replace it; then save the new one).
mkdir -p "$MAPS/_original"
if [ -f "$UP" ] && [ ! -L "$UP" ]; then cp -f "$UP" "$ORIG"; fi

if [ "$1" = restore ]; then
    rm -f "$UP" && cp "$ORIG" "$UP" && say "Underpass is back to normal."
    exit
fi

mapfile -t files < <(find "$MAPS" -path "$MAPS/_*" -prune -o -type f \( -iname '*.udk' -o -iname '*.upk' \) -print | sort)
[ ${#files[@]} -eq 0 ] && { say "No maps yet. Run download-maps.sh, or put map folders in $MAPS."; exit; }
items=()
for f in "${files[@]}"; do
    name=${f#"$MAPS/"}; name=${name%%/*}
    items+=("$f" "$name")
done
items+=(restore "Normal Underpass (no custom map)")

choice=${1:-$(kdialog --title "Rocket League maps" --menu "Map to load as Underpass:" "${items[@]}" 2>/dev/null)}
[ -z "$choice" ] && exit
[ "$choice" = restore ] && exec "$0" restore
[ -f "$choice" ] || { say "Map not found: $choice"; exit 1; }

rm -f "$UP" && ln -s "$choice" "$UP"
name=${choice#"$MAPS/"}; name=${name%%/*}
say "$name is loaded. In Rocket League open Free Play (or a LAN/private match) on Underpass."

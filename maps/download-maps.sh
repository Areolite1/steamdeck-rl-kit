#!/bin/bash
# Downloads the maps listed in maps.txt from their creators' pages into ~/Games/RL-Maps.
# Usage: download-maps.sh            all maps (about 1.4 GB)
#        download-maps.sh "Ice Rings" "Pinch Map"   only these
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOME/.config/rl-deck-kit/paths.env" 2>/dev/null || true
MAPS="${RL_MAPS:-$HOME/Games/RL-Maps}"
mkdir -p "$MAPS"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

url_for() {  # resolves gdrive:ID and bakkesplugins:ID entries to a direct download link
    case "$1" in
        gdrive:*) echo "https://drive.usercontent.google.com/download?id=${1#gdrive:}&export=download&confirm=t" ;;
        bakkesplugins:*) curl -sSfL "https://bakkesplugins.com/maps/${1#bakkesplugins:}" \
                             | grep -oE 'https://cdn.bakkesplugins.com/uploads/[^"]+\.zip' | head -1 ;;
        *) echo "$1" ;;
    esac
}

trim() { local v="$*"; v="${v#"${v%%[![:space:]]*}"}"; echo "${v%"${v##*[![:space:]]}"}"; }

while IFS='|' read -r name src credit; do
    [[ "$name" =~ ^[[:space:]]*(#|$) ]] && continue
    name="$(trim "$name")"; src="$(trim "$src")"; credit="$(trim "$credit")"
    if [ $# -gt 0 ] && ! printf '%s\n' "$@" | grep -qxF "$name"; then continue; fi
    if find "$MAPS/$name" -iname '*.ud[k]' -o -iname '*.upk' 2>/dev/null | grep -q .; then
        echo "= $name (already downloaded)"; continue
    fi
    echo "+ $name  ($credit)"
    url="$(url_for "$src")"
    [ -n "$url" ] || { echo "  no download link found, skipped"; continue; }
    curl -sSfL -o "$TMP/map.zip" "$url" || { echo "  download failed, skipped"; continue; }
    mkdir -p "$MAPS/$name"
    python3 -m zipfile -e "$TMP/map.zip" "$MAPS/$name/" || { echo "  not a zip, skipped"; rm -rf "$MAPS/$name"; }
done < "$HERE/maps.txt"
echo "Maps are in $MAPS. Pick one with \"Rocket League Maps\" (or maps/rl-map.sh)."

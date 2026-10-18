#!/bin/bash
# Steam Deck Rocket League kit: BakkesMod and a custom-map picker for the Epic
# version of Rocket League running through Heroic (flatpak) in Desktop Mode.
# Re-run any time (e.g. after moving the game or switching Proton); it only adds what's missing.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEROIC="$HOME/.var/app/com.heroicgameslauncher.hgl/config/heroic"
SHARED="$HOME/Games/Heroic/rl-deck-kit"     # Heroic's flatpak can read this folder
CONF="$HOME/.config/rl-deck-kit"
APPS="$HOME/.local/share/applications"
MAPS="$HOME/Games/RL-Maps"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*"; exit 1; }

[ -d "$HEROIC" ] || die "Heroic (flatpak) not found. Install Heroic Games Launcher from Discover, install Rocket League in it and launch it once."

say "Finding Rocket League in Heroic"
eval "$(python3 - "$HEROIC" <<'PY'
import json, os, shlex, sys
heroic = sys.argv[1]
installed = json.load(open(os.path.join(heroic, "legendaryConfig/legendary/installed.json")))
app = next((k for k, v in installed.items() if "rocket league" in v.get("title", "").lower()), None)
if not app:
    sys.exit("echo 'Rocket League is not installed in Heroic' >&2; exit 1")
game_dir = installed[app]["install_path"]
cfg = json.load(open(os.path.join(heroic, "GamesConfig", app + ".json")))[app]
prefix = cfg.get("winePrefix", "")
proton = os.path.dirname(cfg.get("wineVersion", {}).get("bin", ""))
pfx = os.path.join(prefix, "pfx") if os.path.isdir(os.path.join(prefix, "pfx", "drive_c")) else prefix
for k, v in dict(RL_APP=app, RL_GAME_DIR=game_dir, RL_PREFIX=prefix, RL_PFX=pfx, RL_PROTON=proton).items():
    print(f"{k}={shlex.quote(v)}")
PY
)"
[ -d "$RL_PFX/drive_c" ] || die "Rocket League's Wine prefix wasn't found ($RL_PFX). Launch the game once from Heroic, then run this again."
[ -x "$RL_PROTON/files/bin/wine" ] || die "Rocket League must use a Proton version in Heroic (Settings > Wine/Proton), e.g. GE-Proton."
echo "  game:   $RL_GAME_DIR"
echo "  prefix: $RL_PFX"
echo "  proton: $RL_PROTON"

mkdir -p "$CONF" "$SHARED" "$APPS" "$MAPS"
cat > "$CONF/paths.env" <<EOF
RL_APP=$(printf %q "$RL_APP")
RL_GAME_DIR=$(printf %q "$RL_GAME_DIR")
RL_PFX=$(printf %q "$RL_PFX")
RL_PROTON=$(printf %q "$RL_PROTON")
RL_MAPS=$(printf %q "$MAPS")
EOF

say "Installing BakkesMod (official release from github.com/bakkesmodorg)"
BM_EXE_DIR="$RL_PFX/drive_c/Program Files/BakkesMod"
BM_DATA="$RL_PFX/drive_c/users/steamuser/AppData/Roaming/bakkesmod/bakkesmod"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
python3 - "$TMP" <<'PY'
import hashlib, json, sys, urllib.request
out = sys.argv[1]
rel = json.load(urllib.request.urlopen("https://api.github.com/repos/bakkesmodorg/BakkesModInjectorCpp/releases/latest"))
print("  release", rel["tag_name"])
for asset in rel["assets"]:
    if asset["name"] in ("BakkesMod.exe", "bakkesmod.zip"):
        data = urllib.request.urlopen(asset["browser_download_url"]).read()
        want = (asset.get("digest") or "").removeprefix("sha256:")
        got = hashlib.sha256(data).hexdigest()
        if want and want != got:
            sys.exit(f"checksum mismatch for {asset['name']}")
        open(f"{out}/{asset['name']}", "wb").write(data)
        print(f"  {asset['name']}: {len(data) // 1024} KB, sha256 ok")
PY
mkdir -p "$BM_EXE_DIR" "$BM_DATA"
cp "$TMP/BakkesMod.exe" "$BM_EXE_DIR/"
if [ ! -f "$BM_DATA/cfg/config.cfg" ]; then
    python3 -m zipfile -e "$TMP/bakkesmod.zip" "$BM_DATA/"
else
    echo "  existing BakkesMod settings kept"
fi

# launcher runs inside Heroic's flatpak with the game's own Wine, so it joins the running game
sed -e "s|@PFX@|$RL_PFX|" -e "s|@PROTON@|$RL_PROTON|" "$KIT/bakkesmod/bakkesmod.sh" > "$SHARED/bakkesmod.sh"
chmod +x "$SHARED/bakkesmod.sh"

say "Adding start-menu shortcuts"
entry() {  # file name exec comment terminal
    cat > "$APPS/$1" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Exec=$3
Comment=$4
Icon=applications-games
Terminal=false
Categories=Game;
EOF
    chmod +x "$APPS/$1"
}
entry rlkit-bakkesmod.desktop "BakkesMod" \
    "flatpak run --command=bash com.heroicgameslauncher.hgl $SHARED/bakkesmod.sh" \
    "Start BakkesMod for Rocket League (open it once the game is at the main menu)"
entry rlkit-maps.desktop "Rocket League Maps" "$KIT/maps/rl-map.sh" \
    "Choose which custom map replaces Underpass"
chmod +x "$KIT/maps/"*.sh

say "Done"
cat <<EOF
  * BakkesMod:  launch Rocket League from Heroic, then open "BakkesMod" from the start menu. F2 = menu.
  * Maps:       run  $KIT/maps/download-maps.sh  once, then pick one with "Rocket League Maps"
                and play Underpass in Free Play.

  Enjoying this? Tips are welcome on Cash App: \$areolite2
EOF

#!/bin/bash
# Installs the Empires of the Undergrowth bot on Linux / a Steam Deck (Desktop Mode).
# No sudo. Re-run any time; it only adds what's missing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/eotu-bot"
VENV="$DATA/venv"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*"; exit 1; }

command -v python3 >/dev/null || die "python3 isn't installed."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "The bot needs Python 3.10 or newer (found $(python3 --version))."
mkdir -p "$DATA"

if [ ! -x "$VENV/bin/python" ]; then
    say "Making a private Python environment in $VENV"
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        warn "python3 -m venv didn't work; making one without pip and fetching pip"
        rm -rf "$VENV"
        python3 -m venv --without-pip "$VENV" || die "Python can't make environments here."
        curl -sSfL https://bootstrap.pypa.io/get-pip.py -o "$DATA/get-pip.py"
        "$VENV/bin/python" "$DATA/get-pip.py" -q
    fi
fi
say "Installing numpy, mss and Pillow into it"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r "$HERE/requirements.txt"

chmod +x "$HERE/eotubot.sh"
mkdir -p "$HOME/.local/bin"
ln -sf "$HERE/eotubot.sh" "$HOME/.local/bin/eotubot"

say "Checking this PC"
case "${XDG_SESSION_TYPE:-}" in
    x11) echo "  desktop: X11 (good)" ;;
    wayland) warn "desktop: Wayland. The bot reads the game window through XWayland; if clicks don't land, set [input] backend = \"uinput\" in settings.toml" ;;
    *) [ -n "${DISPLAY:-}" ] && echo "  desktop: X11 (DISPLAY=$DISPLAY)" || warn "no desktop found: run this in Desktop Mode, not Game Mode" ;;
esac
if [ -w /dev/uinput ]; then echo "  /dev/uinput: usable (fallback input)"; fi

say "Done"
cat <<EOT
  Run the bot with:   $HERE/eotubot.sh <command>    (or just "eotubot" if ~/.local/bin is on your PATH)
  1. Start the game (Desktop Mode), then:   eotubot check
  2. Teach it your screen once:              eotubot teach
  3. Play:   eotubot run host   (this PC hosts)   or   eotubot run join <host's IP>
EOT

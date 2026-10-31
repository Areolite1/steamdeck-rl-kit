#!/bin/bash
# Runs the bot: eotubot.sh check | teach | watch | try MACRO | run host | run join IP | report ...
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY="${XDG_DATA_HOME:-$HOME/.local/share}/eotu-bot/venv/bin/python"
[ -x "$PY" ] || { echo "Run $HERE/install.sh first."; exit 1; }
PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m eotubot "$@"

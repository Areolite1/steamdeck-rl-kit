"""Copies the game's (and the mod's) log and crash files that changed during a match."""
import glob
import os
import time
from pathlib import Path

from .platforms.base import game_paths


def find_logs(cfg, since):
    values = game_paths(cfg["game"]["steam_app_id"])
    found = {}
    for pattern in cfg["logs"]["paths"]:
        try:
            path = pattern.format_map(values)
        except KeyError:
            continue  # e.g. {PROTON_LOCAL} on Windows
        for f in glob.glob(path, recursive=True):
            try:
                st = os.stat(f)
            except OSError:
                continue
            if os.path.isfile(f) and st.st_mtime >= since - 60:
                found[os.path.abspath(f)] = st.st_mtime
    newest = sorted(found, key=found.get, reverse=True)
    return newest[: int(cfg["logs"].get("max_files", 30))]


def collect(cfg, since, dest):
    """Copies matching files into dest (only the last max_mb of each). Returns the names."""
    dest = Path(dest)
    limit = int(float(cfg["logs"].get("max_mb", 4)) * 1024 * 1024)
    names = []
    for f in find_logs(cfg, since):
        parts = Path(f).parts[-3:]
        name = "__".join(p.replace(":", "") for p in parts)
        try:
            size = os.path.getsize(f)
            with open(f, "rb") as src:
                if size > limit:
                    src.seek(size - limit)
                data = src.read(limit)
        except OSError:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_bytes(data)
        names.append(name)
    return names


def stamp(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

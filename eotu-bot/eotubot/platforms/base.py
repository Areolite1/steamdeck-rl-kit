"""Things every platform shares: key names, picking the game window, finding Steam."""
import os
import re
import sys
from pathlib import Path

# Key names used in macros ("key o", "key ctrl+s"). Every platform maps these.
LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
DIGITS = [str(d) for d in range(10)]
FKEYS = [f"f{n}" for n in range(1, 13)]
NAMED = ["escape", "enter", "space", "tab", "backspace", "delete", "insert", "home", "end",
         "pageup", "pagedown", "up", "down", "left", "right", "shift", "ctrl", "alt",
         "minus", "equal", "period", "comma", "slash", "semicolon", "pause"]
KEYS = set(LETTERS + DIGITS + FKEYS + NAMED)

ALIASES = {"esc": "escape", "return": "enter", "del": "delete", "pgup": "pageup",
           "pgdn": "pagedown", "control": "ctrl", "spacebar": "space", ".": "period",
           ",": "comma", "-": "minus", "=": "equal", "/": "slash", ";": "semicolon"}


def norm_key(name):
    name = name.strip().lower()
    return ALIASES.get(name, name)


def parse_combo(text):
    """'ctrl+shift+s' -> ['ctrl', 'shift', 's']; raises ValueError for unknown keys."""
    keys = [norm_key(k) for k in text.split("+") if k.strip()]
    bad = [k for k in keys if k not in KEYS]
    if not keys or bad:
        raise ValueError(f"unknown key {bad[0] if bad else text!r} (known: letters, digits, f1-f12, "
                         + ", ".join(NAMED) + ")")
    return keys


def pick_window(cands, game_cfg):
    """Choose the game window from (handle, title, class, (x, y, w, h)) candidates.

    A window counts if its title matches game.title (and not game.not_title), or if its class
    is Proton's steam_app_<id> for this game. Class matches rank higher; ties go to the bigger one.
    """
    title_re = re.compile(game_cfg.get("title", "Undergrowth"), re.I)
    class_re = re.compile(game_cfg.get("class", "UnrealWindow"), re.I)
    not_re = re.compile(game_cfg["not_title"], re.I) if game_cfg.get("not_title") else None
    app_id = str(game_cfg.get("steam_app_id", ""))
    best, best_key = None, None
    for handle, title, cls, rect in cands:
        if not rect or rect[2] < 200 or rect[3] < 150:
            continue
        title_ok = bool(title) and bool(title_re.search(title)) and not (not_re and not_re.search(title))
        cls_ok = bool(cls) and bool(class_re.search(cls))
        specific = cls_ok and app_id and app_id in cls
        if not (title_ok or specific):
            continue
        key = (int(title_ok) * 2 + int(cls_ok), rect[2] * rect[3])
        if best_key is None or key > best_key:
            best, best_key = (handle, rect), key
    return best


def steam_roots():
    """Folders where Steam may be installed on this machine."""
    roots = []
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
        except OSError:
            pass
        roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    else:
        home = Path.home()
        roots += [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
                  home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    seen, out = set(), []
    for r in roots:
        try:
            key = r.resolve()
        except OSError:
            continue
        if r.is_dir() and key not in seen:
            seen.add(key)
            out.append(r)
    return out


def steam_libraries():
    libs = []
    for root in steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text("utf-8", "replace")
        except OSError:
            continue
        for p in re.findall(r'"path"\s+"([^"]+)"', text):
            libs.append(Path(p.replace("\\\\", "\\")))
    seen, out = set(), []
    for lib in libs:
        if str(lib) not in seen and (lib / "steamapps").is_dir():
            seen.add(str(lib))
            out.append(lib)
    return out


def game_paths(app_id):
    """{'GAME_DIR': ..., 'PROTON_LOCAL': ...} for the Steam copy of the game, where found."""
    found = {}
    for lib in steam_libraries():
        acf = lib / "steamapps" / f"appmanifest_{app_id}.acf"
        try:
            m = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text("utf-8", "replace"))
        except OSError:
            continue
        if m:
            found["GAME_DIR"] = str(lib / "steamapps" / "common" / m.group(1))
            local = (lib / "steamapps" / "compatdata" / str(app_id) / "pfx" / "drive_c" / "users"
                     / "steamuser" / "AppData" / "Local")
            if local.is_dir():
                found["PROTON_LOCAL"] = str(local)
            break
    if os.environ.get("LOCALAPPDATA"):
        found["LOCALAPPDATA"] = os.environ["LOCALAPPDATA"]
    found["HOME"] = str(Path.home())
    return found


class BasePlatform:
    """What the bot needs from the machine. Coordinates are screen pixels."""
    name = "base"
    notes = ()

    def find_game(self):            # -> (x, y, w, h) of the game's picture, or None
        raise NotImplementedError

    def screen_rect(self):          # -> (x, y, w, h) of the main screen
        raise NotImplementedError

    def capture(self, rect):        # -> numpy uint8 array (h, w, 3), RGB
        raise NotImplementedError

    def move(self, x, y):
        raise NotImplementedError

    def button(self, which, down):  # which: left / right / middle
        raise NotImplementedError

    def scroll(self, notches):      # + = wheel up (zoom in), - = wheel down
        raise NotImplementedError

    def key(self, name, down):
        raise NotImplementedError

    def type_text(self, text):
        raise NotImplementedError

    def cursor(self):               # -> (x, y) or None if this machine can't tell
        return None

    def key_is_down(self, name):    # -> bool, or None if this machine can't tell
        return None

    def focus_game(self):
        pass

    def game_alive(self):
        return self.find_game() is not None

    def launch_game(self, url):
        raise NotImplementedError

    def close(self):
        pass

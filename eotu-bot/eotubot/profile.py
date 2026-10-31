"""What the bot learned from `teach` on this PC: where each spot is, and small pictures of the
screen around the watched ones. Positions are shares of the game window (0-1), so moving the
window doesn't matter; a different size or shape does (the bot warns)."""
import json
import time
from pathlib import Path

import numpy as np


class Profile:
    def __init__(self, data):
        self.dir = Path(data)
        self.path = self.dir / "profile.json"
        self.patch_dir = self.dir / "patches"
        self.spots = {}      # name -> {"x", "y", "screen", "taught"}
        self.patches = {}    # spot name -> {"screen", "x", "y", "size", "file"}
        self.window = None   # [w, h] of the game window when taught
        self._cache = {}
        if self.path.exists():
            d = json.loads(self.path.read_text("utf-8"))
            self.spots = d.get("spots", {})
            self.patches = d.get("patches", {})
            self.window = d.get("window")

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"window": self.window, "spots": self.spots, "patches": self.patches},
                                  indent=1), "utf-8")
        tmp.replace(self.path)

    def has(self, name):
        return name in self.spots

    def set_spot(self, name, fx, fy, screen, window_size):
        self.spots[name] = {"x": round(float(fx), 5), "y": round(float(fy), 5), "screen": screen,
                            "taught": time.strftime("%Y-%m-%d %H:%M")}
        self.window = list(window_size)

    def set_patch(self, name, screen, fx, fy, pixels):
        self.patch_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{screen}__{name}.npy"
        np.save(self.patch_dir / fname, pixels)
        self.patches[name] = {"screen": screen, "x": round(float(fx), 5), "y": round(float(fy), 5),
                              "size": int(pixels.shape[0]), "file": fname}
        self._cache.pop(name, None)

    def forget(self, name):
        self.spots.pop(name, None)
        p = self.patches.pop(name, None)
        self._cache.pop(name, None)
        if p:
            (self.patch_dir / p["file"]).unlink(missing_ok=True)

    def patch(self, name):
        if name not in self._cache:
            self._cache[name] = np.load(self.patch_dir / self.patches[name]["file"])
        return self._cache[name]

    def screen_patches(self):
        """screen name -> list of spot names with a saved picture."""
        out = {}
        for name, p in self.patches.items():
            out.setdefault(p["screen"], []).append(name)
        return out

    def size_warning(self, rect):
        if not self.window or not rect:
            return ""
        tw, th = self.window
        w, h = rect[2], rect[3]
        if (tw, th) == (w, h):
            return ""
        if abs(tw / th - w / h) > 0.01:
            return (f"the game window is {w}x{h} but was {tw}x{th} when you taught the bot: a "
                    f"different shape moves things around, so run `eotubot teach` again")
        return (f"the game window is {w}x{h} but was {tw}x{th} when you taught the bot; same shape, "
                f"so spots still line up, but screen recognition may be weaker")

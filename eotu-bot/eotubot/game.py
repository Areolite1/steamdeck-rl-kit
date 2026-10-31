"""The bot's hands and eyes on the game: clicks on taught spots, keys, screenshots, and the
ways you can stop it (stop/pause files, mouse in the top-left corner)."""
import fnmatch
import time
from collections import deque

from .platforms.base import parse_combo
from .vision import Minimap, Motion, detect_screen, save_png


class StopBot(Exception):
    """You asked the bot to stop."""


class GameGone(Exception):
    """The game window isn't there (closed, crashed or minimised)."""


class MissingSpot(Exception):
    """A macro needs a spot that hasn't been taught yet."""


class Control:
    """`eotubot stop` / `pause` / `resume` leave files here; the bot checks them often."""

    def __init__(self, data, platform, cfg, log):
        self.dir = data / "control"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.platform = platform
        self.corner = bool(cfg["input"].get("failsafe_corner", True))
        self.log = log

    def clear(self):
        for f in ("stop", "pause"):
            (self.dir / f).unlink(missing_ok=True)

    def check(self):
        if (self.dir / "stop").exists():
            (self.dir / "stop").unlink(missing_ok=True)
            raise StopBot("stop requested")
        if self.corner:
            c = self.platform.cursor()
            if c and c[0] <= 2 and c[1] <= 2:
                raise StopBot("the mouse was pushed into the top-left corner")
        if (self.dir / "pause").exists():
            self.log("Paused (`eotubot resume` to carry on)")
            while (self.dir / "pause").exists():
                time.sleep(0.5)
                if (self.dir / "stop").exists():
                    self.check()
            self.log("Resumed")


class Game:
    def __init__(self, platform, profile, cfg, log, control, rng):
        self.p = platform
        self.profile = profile
        self.cfg = cfg
        self.log = log
        self.control = control
        self.rng = rng
        self.t = cfg["timing"]
        self.rect = None
        self._rect_at = 0.0
        self.frames = deque(maxlen=int(cfg["evidence"].get("frames", 8)))
        self._kept_at = 0.0
        self._focused_at = 0.0
        self.motion = Motion()
        self.minimap = Minimap(cfg, profile)
        self.last_frame = None

    # -- the window and screenshots ----------------------------------------------------------
    def find(self, force=False):
        now = time.monotonic()
        if force or self.rect is None or now - self._rect_at > 2.0:
            self.rect = self.p.find_game()
            self._rect_at = now
        return self.rect

    def alive(self):
        return self.p.game_alive()

    def frame(self):
        rect = self.find()
        if not rect:
            raise GameGone("the game window isn't there")
        img = self.p.capture(rect)
        self.last_frame = img
        now = time.monotonic()
        if now - self._kept_at >= 1.0:
            self.frames.append((time.time(), img))
            self._kept_at = now
        return img

    def screen(self, frame=None):
        return detect_screen(self.frame() if frame is None else frame, self.profile, self.cfg)

    def wait_screen(self, names, timeout, every=0.5):
        names = {names} if isinstance(names, str) else set(names)
        end = time.monotonic() + timeout
        while True:
            self.control.check()
            try:
                if self.screen()[0] in names:
                    return True
            except GameGone:
                pass
            if time.monotonic() >= end:
                return False
            time.sleep(every)

    def save_recent(self, folder, prefix):
        folder.mkdir(parents=True, exist_ok=True)
        names = []
        for i, (ts, img) in enumerate(list(self.frames)):
            name = f"{prefix}_{i:02d}_{time.strftime('%H%M%S', time.localtime(ts))}.png"
            save_png(folder / name, img)
            names.append(name)
        return names

    # -- spots -------------------------------------------------------------------------------
    def spot_frac(self, ref):
        if ref.startswith("@"):
            fx, fy = (float(v) for v in ref[1:].split(","))
            return fx, fy
        spots = self.profile.spots
        if ref == "map_random":
            if "minimap_tl" not in spots or "minimap_br" not in spots:
                raise MissingSpot("minimap_tl")
            a, b = spots["minimap_tl"], spots["minimap_br"]
            m = 0.08
            fx = a["x"] + (b["x"] - a["x"]) * self.rng.uniform(m, 1 - m)
            fy = a["y"] + (b["y"] - a["y"]) * self.rng.uniform(m, 1 - m)
            return fx, fy
        if "*" in ref or "?" in ref:
            names = sorted(n for n in spots if fnmatch.fnmatch(n, ref))
            if not names:
                raise MissingSpot(ref)
            ref = self.rng.choice(names)
        if ref not in spots:
            raise MissingSpot(ref)
        return spots[ref]["x"], spots[ref]["y"]

    def spot_xy(self, ref):
        rect = self.find()
        if not rect:
            raise GameGone("the game window isn't there")
        x, y, w, h = rect
        fx, fy = self.spot_frac(ref)
        return int(round(x + fx * w)), int(round(y + fy * h))

    # -- hands -------------------------------------------------------------------------------
    def sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.25))
            self.control.check()

    def focus(self, every=10.0):
        now = time.monotonic()
        if now - self._focused_at >= every:
            self.p.focus_game()
            self._focused_at = now
            time.sleep(0.05)

    def move_to(self, ref):
        self.control.check()
        x, y = self.spot_xy(ref)
        self.p.move(x, y)
        time.sleep(0.04)
        return x, y

    def click(self, ref, button="left", double=False):
        self.move_to(ref)
        for _ in range(2 if double else 1):
            self.p.button(button, True)
            try:
                time.sleep(self.t["click_hold"])
            finally:
                self.p.button(button, False)
            if double:
                time.sleep(0.07)

    def drag(self, a, b):
        xa, ya = self.move_to(a)
        xb, yb = self.spot_xy(b)
        self.p.button("left", True)
        try:
            time.sleep(0.12)
            for i in range(1, 11):
                self.p.move(xa + (xb - xa) * i // 10, ya + (yb - ya) * i // 10)
                time.sleep(0.025)
            time.sleep(0.1)
        finally:
            self.p.button("left", False)

    def key(self, combo):
        self.control.check()
        keys = parse_combo(combo)
        pressed = []
        try:
            for k in keys:
                self.p.key(k, True)
                pressed.append(k)
                time.sleep(0.02)
            time.sleep(self.t["click_hold"])
        finally:
            for k in reversed(pressed):
                self.p.key(k, False)

    def type(self, text):
        self.control.check()
        self.p.type_text(text)

    def scroll(self, notches, ref=None):
        if ref:
            self.move_to(ref)
        self.p.scroll(notches)

    def park(self):
        """Move the mouse off the buttons, so hover highlights don't hide the saved pictures."""
        ref = self.cfg["input"].get("park", "@0.5,0.12")
        try:
            self.move_to(ref)
        except (MissingSpot, GameGone):
            pass

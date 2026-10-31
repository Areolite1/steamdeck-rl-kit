"""Macros: named lists of steps from the settings ("click mp_host_button", "wait 3", ...)."""
import fnmatch
import time

from .game import GameGone, MissingSpot
from .platforms.base import parse_combo

SPOT_VERBS = {"click": 1, "rclick": 1, "dclick": 1, "mclick": 1, "move": 1, "drag": 2}
VERBS = set(SPOT_VERBS) | {"key", "type", "scroll", "wait", "run", "wait_for"}
SPECIAL_SPOTS = {"map_random": ("minimap_tl", "minimap_br")}


class Step:
    __slots__ = ("verb", "args", "cond", "raw")

    def __init__(self, verb, args, cond, raw):
        self.verb, self.args, self.cond, self.raw = verb, args, cond, raw

    def spot_refs(self):
        if self.verb in SPOT_VERBS:
            return list(self.args)
        if self.verb == "scroll":
            return list(self.args[1:])
        return []


def parse_step(raw):
    text, cond = raw.strip(), None
    if text.startswith("if "):
        head, sep, rest = text[3:].partition(":")
        if not sep or not head.strip():
            raise ValueError(f"{raw!r}: write it as 'if SPOT: step'")
        cond, text = head.strip(), rest.strip()
    verb, _, rest = text.partition(" ")
    verb = verb.lower()
    if verb not in VERBS:
        raise ValueError(f"{raw!r}: unknown step {verb!r} (steps: {', '.join(sorted(VERBS))})")
    args = [rest] if verb == "type" else rest.split()
    n = len(args)
    if verb in SPOT_VERBS and n != SPOT_VERBS[verb]:
        raise ValueError(f"{raw!r}: {verb} takes {SPOT_VERBS[verb]} spot name(s)")
    if verb == "key":
        if n != 1:
            raise ValueError(f"{raw!r}: key takes one key or combination, like 'key ctrl+a'")
        parse_combo(args[0])
    if verb == "type" and not rest:
        raise ValueError(f"{raw!r}: type needs some text")
    if verb == "scroll":
        if n not in (1, 2):
            raise ValueError(f"{raw!r}: scroll N [SPOT]")
        int(args[0])
    if verb == "wait":
        if n != 1:
            raise ValueError(f"{raw!r}: wait SECONDS")
        float(args[0])
    if verb == "run" and n != 1:
        raise ValueError(f"{raw!r}: run MACRO")
    if verb == "wait_for":
        if n not in (1, 2):
            raise ValueError(f"{raw!r}: wait_for SCREEN [SECONDS]")
        if n == 2:
            float(args[1])
    return Step(verb, args, cond, raw)


class _Fill(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class Macros:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.steps = {}
        for name, raw_steps in cfg.get("macros", {}).items():
            try:
                self.steps[name] = [parse_step(s) for s in raw_steps]
            except ValueError as e:
                raise ValueError(f"macro {name}: {e}") from e
        self._warned = set()

    # -- checking ----------------------------------------------------------------------------
    def check(self):
        """Mistakes in the macros themselves (not about what's been taught)."""
        spots, screens = self.cfg.get("spots", {}), self.cfg.get("screens", {})
        out = []

        def known(ref):
            if ref.startswith("@") or ref in SPECIAL_SPOTS or ref in spots:
                return True
            return ("*" in ref or "?" in ref) and any(fnmatch.fnmatch(s, ref) for s in spots)

        for name, steps in self.steps.items():
            for st in steps:
                for ref in st.spot_refs():
                    if not known(ref):
                        out.append(f"macro {name}: no spot called {ref!r} in [spots]")
                if st.cond and st.cond not in spots:
                    out.append(f"macro {name}: 'if {st.cond}:' – no spot called {st.cond!r}")
                if st.verb == "run" and st.args[0] not in self.steps:
                    out.append(f"macro {name}: runs {st.args[0]!r}, which doesn't exist")
                if st.verb == "wait_for" and st.args[0] not in screens:
                    out.append(f"macro {name}: wait_for {st.args[0]!r} – no such screen")
            try:
                self._needed(name, ())
            except RecursionError:
                out.append(f"macro {name}: runs itself in a loop")
        return out

    def _needed(self, name, chain):
        if name in chain:
            raise RecursionError(name)
        need = set()
        for st in self.steps.get(name, []):
            if st.cond:
                continue
            for ref in st.spot_refs():
                if ref.startswith("@"):
                    continue
                need.update(SPECIAL_SPOTS.get(ref, (ref,)))
            if st.verb == "run":
                need |= self._needed(st.args[0], chain + (name,))
        return need

    def missing(self, name, profile):
        """Spots this macro needs that haven't been taught (sorted)."""
        if name not in self.steps:
            return [f"(no macro called {name})"]
        out = []
        for ref in sorted(self._needed(name, ())):
            if "*" in ref or "?" in ref:
                if not any(fnmatch.fnmatch(s, ref) for s in profile.spots):
                    out.append(ref)
            elif not profile.has(ref):
                out.append(ref)
        return out

    def available(self, name, profile):
        return not self.missing(name, profile)

    # -- running -----------------------------------------------------------------------------
    def run(self, name, game, ctx=None, depth=0):
        """Runs a macro. False if it couldn't (a spot isn't taught, or a wait_for timed out)."""
        if name not in self.steps:
            self.log(f"No macro called {name!r}")
            return False
        missing = self.missing(name, game.profile)
        if missing:
            if name not in self._warned:
                self._warned.add(name)
                self.log(f"Skipping {name}: teach these spots first: {', '.join(missing)}")
            return False
        if depth == 0:
            game.focus()
        ok = True
        try:
            for st in self.steps[name]:
                if st.cond and not game.profile.has(st.cond):
                    continue
                if not self._do(st, game, ctx or {}, depth):
                    ok = False
                    break
        except MissingSpot as e:
            self.log(f"{name}: spot {e} isn't taught")
            ok = False
        if depth == 0:
            game.park()
        return ok

    def _do(self, st, game, ctx, depth):
        v, a, t = st.verb, st.args, self.cfg["timing"]
        game.control.check()
        if v == "click":
            game.click(a[0])
        elif v == "rclick":
            game.click(a[0], button="right")
        elif v == "mclick":
            game.click(a[0], button="middle")
        elif v == "dclick":
            game.click(a[0], double=True)
        elif v == "move":
            game.move_to(a[0])
        elif v == "drag":
            game.drag(a[0], a[1])
        elif v == "key":
            game.key(a[0])
        elif v == "type":
            game.type(a[0].format_map(_Fill(ctx)))
        elif v == "scroll":
            game.scroll(int(a[0]), a[1] if len(a) > 1 else None)
        elif v == "wait":
            game.sleep(float(a[0]) * float(t.get("wait_scale", 1.0)))
            return True
        elif v == "run":
            return self.run(a[0], game, ctx, depth + 1)
        elif v == "wait_for":
            timeout = float(a[1]) if len(a) > 1 else float(t["load_timeout"])
            try:
                return game.wait_screen(a[0], timeout)
            except GameGone:
                return False
        time.sleep(float(t.get("step_pause", 0.25)))
        return True

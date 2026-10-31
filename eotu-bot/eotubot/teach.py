"""`eotubot teach`: you point at things in the game, the bot remembers where they are.

Hotkeys work while the game has focus: F8 = "it's here", F9 = skip, F10 = stop teaching.
With --countdown N the bot reads the mouse position N seconds after you press Enter instead
(handy without a keyboard, e.g. on a Steam Deck).
"""
import time

from .game import GameGone
from .vision import crop, patch_size

HERE, SKIP, QUIT = "here", "skip", "quit"


def teach_spot(game, profile, cfg, name, pos):
    """Saves spot `name` at screen point pos; for watched spots also a picture around it."""
    rect = game.find(force=True)
    if not rect:
        raise GameGone("the game window isn't there")
    x, y, w, h = rect
    cx, cy = pos
    if not (x <= cx < x + w and y <= cy < y + h):
        raise ValueError(f"({cx}, {cy}) is outside the game window ({x}, {y}, {w}x{h})")
    spot = cfg["spots"][name]
    fx, fy = (cx - x) / w, (cy - y) / h
    profile.set_spot(name, fx, fy, spot["screen"], (w, h))
    if spot.get("watch"):
        # Take the picture with the mouse elsewhere: buttons light up while hovered.
        game.park()
        time.sleep(0.5)
        frame = game.frame()
        game.p.move(cx, cy)
        profile.set_patch(name, spot["screen"], fx, fy, crop(frame, cx - x, cy - y,
                                                               patch_size(h, cfg["detect"]["patch"])))
    profile.save()
    return fx, fy


def wait_point(game, countdown, say):
    """Waits for F8 (returns the mouse position), F9 (SKIP) or F10 (QUIT)."""
    p = game.p
    if countdown or p.key_is_down("f8") is None:
        n = countdown or 5
        for i in range(n, 0, -1):
            say(f"      {i}...")
            time.sleep(1)
        pos = p.cursor()
        if pos is None:
            raise SystemExit("This PC can't report the mouse position, so `teach` can't work here. "
                             "On Linux, run the game in Desktop Mode (X11).")
        return pos
    was = {k: True for k in ("f8", "f9", "f10")}  # wait for keys to be released first
    while True:
        game.control.check()
        for k in ("f8", "f9", "f10"):
            down = bool(p.key_is_down(k))
            if down and not was[k]:
                if k == "f8":
                    return p.cursor()
                return SKIP if k == "f9" else QUIT
            was[k] = down
        time.sleep(0.03)


def teach(game, profile, cfg, screens=None, missing_only=False, countdown=0, say=print, ask=input):
    order = [s for s in cfg["detect"]["order"] if s in cfg["screens"]]
    targets = screens or order
    bad = [s for s in targets if s not in cfg["screens"]]
    if bad:
        raise SystemExit(f"No screen called {bad[0]!r}. Screens: {', '.join(order)}")
    mode = (f"Press Enter here, then put the mouse on it within {countdown} s" if countdown else
            "In the game: put the mouse on it and press F8. F9 = skip it, F10 = stop teaching")
    for screen in targets:
        sc = cfg["screens"][screen]
        spots = [(n, s) for n, s in cfg["spots"].items() if s["screen"] == screen]
        if missing_only:
            spots = [(n, s) for n, s in spots if not profile.has(n)]
        if not spots:
            continue
        say("")
        say(f"=== {sc['title']} ===")
        say(sc["how"])
        say("Spots on this screen, in order:")
        for i, (n, s) in enumerate(spots, 1):
            extra = " (optional)" if s.get("optional") else ""
            have = " [taught]" if profile.has(n) else ""
            say(f"  {i}. {s['ask']}{extra}{have}")
            if s.get("prep"):
                say(f"     first: {s['prep']}")
        say(mode + ".")
        reply = ask("Press Enter when the game shows this screen (s = skip screen, q = quit): ").strip().lower()
        if reply.startswith("q"):
            return
        if reply.startswith("s"):
            continue
        game.find(force=True)
        game.p.focus_game()
        for i, (n, s) in enumerate(spots, 1):
            if s.get("prep"):
                say(f"  First: {s['prep']}")
            say(f"  {i}. -> {s['ask']}")
            if countdown and i > 1:
                ask("     Press Enter, then point at it: ")
            got = wait_point(game, countdown, say)
            if got == QUIT:
                say("Stopped. What you taught so far is saved.")
                return
            if got == SKIP:
                say("     skipped")
                continue
            try:
                fx, fy = teach_spot(game, profile, cfg, n, got)
            except (ValueError, GameGone) as e:
                say(f"     not saved: {e}")
                continue
            say(f"     saved ({fx:.1%} across, {fy:.1%} down)\a")
    say("")
    say("Done. `eotubot check` shows what's still missing; `eotubot watch` shows what the bot sees.")

"""Command line: eotubot check | teach | watch | try | run | pause | resume | stop | report | settings."""
import argparse
import random
import socket
import sys
import time
import webbrowser
from pathlib import Path

from . import VERSION, config
from .game import Control, Game, GameGone, StopBot
from .macros import Macros
from .profile import Profile
from .strategy import Learner

ROLES = ("host", "join", "solo")


class Ctx:
    """Everything a command needs, made on demand."""

    def __init__(self, args):
        self.data = config.data_dir(args.data)
        self.cfg = config.load(self.data)
        self.logfile = self.data / "bot.log"
        self._platform = None

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        with open(self.logfile, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")

    @property
    def platform(self):
        if self._platform is None:
            from .platforms import get_platform
            self._platform = get_platform(self.cfg)
        return self._platform

    def game(self, seed=None):
        profile = Profile(self.data)
        control = Control(self.data, self.platform, self.cfg, self.log)
        return Game(self.platform, profile, self.cfg, self.log, control, random.Random(seed))

    def close(self):
        if self._platform is not None:
            self._platform.close()


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the LAN address
        return s.getsockname()[0]
    except OSError:
        return "this PC's IP address"
    finally:
        s.close()


# --- commands ---------------------------------------------------------------------------------

def cmd_check(args, ctx):
    cfg, ok = ctx.cfg, True
    print(f"eotu-bot {VERSION}")
    print(f"Data folder:   {ctx.data}")
    print(f"Your settings: {ctx.data / 'settings.toml'}")
    bad = config.problems(cfg)
    for b in bad:
        print(f"  settings problem: {b}")
    ok &= not bad
    try:
        p = ctx.platform
    except OSError as e:
        print(f"Input/screen:  NOT WORKING – {e}")
        return 1
    print(f"Input/screen:  {p.describe()}")
    game = ctx.game()
    rect = game.find(force=True)
    if not rect:
        print("Game window:   not found. Start the game (windowed or borderless works best) and run this again.")
        ok = False
    else:
        print(f"Game window:   {rect[2]}x{rect[3]} at ({rect[0]}, {rect[1]})")
        try:
            frame = game.frame()
            from .vision import save_png
            save_png(ctx.data / "check.png", frame)
            if frame.max() < 8:
                print("  The screenshot is black. On Windows use Borderless/Windowed instead of exclusive "
                      "fullscreen; on a Steam Deck use Desktop Mode.")
                ok = False
            else:
                print(f"Screenshot:    saved {ctx.data / 'check.png'}")
            warn = game.profile.size_warning(rect)
            if warn:
                print(f"  Note: {warn}")
            if game.profile.patches:
                name, score, _ = game.screen(frame)
                print(f"Screen now:    {name} ({score:.2f})")
        except (OSError, GameGone) as e:
            print(f"Screenshot:    failed – {e}")
            ok = False
    prof, spots = game.profile, cfg["spots"]
    need = [n for n, s in spots.items() if not s.get("optional") and not cfg["screens"][s["screen"]].get("optional")]
    print(f"Taught:        {sum(prof.has(n) for n in spots)} of {len(spots)} spots "
          f"({sum(prof.has(n) for n in need)} of {len(need)} needed)")
    missing = [n for n in need if not prof.has(n)]
    if missing:
        print("  still to teach: " + ", ".join(missing) + "   (`eotubot teach --missing`)")
    macros = Macros(cfg)
    ready = [m for m in macros.steps if macros.available(m, prof)]
    print(f"Macros ready:  {len(ready)} of {len(macros.steps)}")
    for m in macros.steps:
        if m not in ready:
            print(f"  {m}: needs {', '.join(macros.missing(m, prof))}")
    if args.peer:
        port = cfg["link"]["port"]
        try:
            socket.create_connection((args.peer, port), timeout=5).close()
            print(f"Other PC:      reached {args.peer}:{port}")
        except OSError as e:
            print(f"Other PC:      can't reach {args.peer}:{port} ({e}). Is `eotubot run host` running "
                  "there, and is the port allowed through its firewall?")
            ok = False
    return 0 if ok else 1


def cmd_teach(args, ctx):
    from .teach import teach
    game = ctx.game()
    if not game.find(force=True):
        print("Start the game first (windowed or borderless works best), then run `eotubot teach` again.")
        return 1
    teach(game, game.profile, ctx.cfg, screens=args.screens or None, missing_only=args.missing,
          countdown=args.countdown)
    return 0


def cmd_shot(args, ctx):
    """Saves the game window, plus a copy with a labelled grid (every 5% / 10%) for reading positions."""
    import numpy as np
    from .vision import save_png
    game = ctx.game()
    rect = game.find(force=True)
    if not rect:
        print("The game window isn't there.")
        return 1
    frame = game.frame()
    out = Path(args.path) if args.path else ctx.data / "shot.png"
    save_png(out, frame)
    grid = frame.copy()
    h, w = grid.shape[:2]
    for i in range(1, 20):
        colour = (255, 0, 255) if i % 2 == 0 else (0, 255, 255)
        x, y = int(w * i / 20), int(h * i / 20)
        grid[:, x] = colour
        grid[y, :] = colour
    gpath = out.with_name(out.stem + "_grid.png")
    try:
        from PIL import Image, ImageDraw
        img = Image.fromarray(grid)
        d = ImageDraw.Draw(img)
        for i in range(1, 10):
            d.text((int(w * i / 10) + 2, 2), f"x{i / 10:.1f}", fill=(255, 255, 0))
            d.text((2, int(h * i / 10) + 2), f"y{i / 10:.1f}", fill=(255, 255, 0))
        img.save(gpath)
    except ImportError:
        save_png(gpath, grid)
    name, score, _ = game.screen(frame) if game.profile.patches else ("?", 0.0, {})
    print(f"Game window {w}x{h} at ({rect[0]}, {rect[1]}); screen looks like: {name} ({score:.2f})")
    print(f"Saved {out}")
    print(f"Saved {gpath}  (magenta lines every 10%, cyan every 5% in between)")
    return 0


def cmd_teach_at(args, ctx):
    """Teaches one spot without pointing: x y in the game window's pixels, or @fx,fy shares."""
    from .teach import teach_spot
    cfg = ctx.cfg
    if args.spot not in cfg["spots"]:
        print(f"No spot called {args.spot!r}. Spots: {', '.join(cfg['spots'])}")
        return 1
    game = ctx.game()
    rect = game.find(force=True)
    if not rect:
        print("The game window isn't there.")
        return 1
    x, y, w, h = rect
    if args.x.startswith("@"):
        fx, fy = (float(v) for v in args.x[1:].split(","))
        px, py = x + fx * w, y + fy * h
    else:
        if args.y is None:
            print("Give x and y (pixels inside the game window), or @fx,fy")
            return 1
        px, py = x + float(args.x), y + float(args.y)
    fx, fy = teach_spot(game, game.profile, cfg, args.spot, (int(round(px)), int(round(py))))
    watch = " (+ picture)" if cfg["spots"][args.spot].get("watch") else ""
    print(f"Saved {args.spot} at {fx:.3f}, {fy:.3f}{watch}")
    return 0


def cmd_forget(args, ctx):
    prof = Profile(ctx.data)
    for name in args.spots:
        if prof.has(name) or name in prof.patches:
            prof.forget(name)
            print(f"Forgot {name}")
        else:
            print(f"{name} wasn't taught")
    prof.save()
    return 0


def cmd_watch(args, ctx):
    game = ctx.game()
    print("What the bot sees, once a second (Ctrl+C to stop):")
    t0 = time.monotonic()
    try:
        while not args.seconds or time.monotonic() - t0 < args.seconds:
            try:
                frame = game.frame()
            except GameGone:
                print("  (no game window)")
                time.sleep(1)
                continue
            name, score, scores = game.screen(frame)
            obs = game.minimap.read(frame, time.monotonic() - t0)
            moving = game.motion.change(frame)
            top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:4])
            print(f"  screen {name:<12} [{top}]  minimap own {obs['own']} enemy {obs['enemy']} "
                  f"threat {obs['threat']}  change {moving:.2f}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_try(args, ctx):
    game = ctx.game()
    macros = Macros(ctx.cfg, log=ctx.log)
    if args.macro not in macros.steps:
        print(f"No macro called {args.macro!r}. Macros: {', '.join(macros.steps)}")
        return 1
    missing = macros.missing(args.macro, game.profile)
    if missing:
        print(f"Teach these first: {', '.join(missing)}")
        return 1
    print(f"Running {args.macro} in {args.delay} s (switch to the game; mouse to the top-left corner stops it)")
    time.sleep(args.delay)
    try:
        for i in range(args.times):
            ok = macros.run(args.macro, game, ctx={"host_ip": args.host_ip or ""})
            print(f"  {i + 1}: {'done' if ok else 'did not finish'}")
    except StopBot as e:
        print(f"Stopped: {e}")
    return 0


def cmd_run(args, ctx):
    from .link import Link
    from .match import Runner
    cfg = ctx.cfg
    if args.role == "join" and not args.host:
        print("Say which PC hosts: eotubot run join 192.168.1.20")
        return 1
    bad = config.problems(cfg)
    if bad:
        print("Fix settings.toml first:\n  " + "\n  ".join(bad))
        return 1
    if args.port:
        cfg["link"]["port"] = args.port
    seed = args.seed if args.seed is not None else int(time.time())
    game = ctx.game(seed)
    game.control.clear()
    if not game.profile.spots:
        print("The bot hasn't been taught this PC's screen yet: run `eotubot teach` first.")
        return 1
    macros = Macros(cfg, log=ctx.log)
    learner = Learner(ctx.data)
    link = None
    if args.role != "solo":
        lc = cfg["link"]
        link = Link(args.role, lc["port"], host=args.host, log=ctx.log, ping_every=lc["ping_every"],
                    dead_after=lc["dead_after"]).start()
        if args.role == "host":
            ctx.log(f"Host bot listening on port {link.port}. On the other PC run:  eotubot run join {local_ip()}")
    runner = Runner(args.role, game, macros, learner, cfg, ctx.data, ctx.log, random.Random(seed), link=link,
                    host_ip=args.host, strategy=args.strategy)
    ctx.log(f"Bot {VERSION} starting as {args.role} (seed {seed}). Stop: mouse to the top-left corner, "
            "Ctrl+C here, or `eotubot stop`.")
    try:
        runner.run(args.matches)
    except StopBot as e:
        ctx.log(f"Stopped: {e}")
    except KeyboardInterrupt:
        ctx.log("Stopped (Ctrl+C)")
    finally:
        if link:
            link.close()
    return 0


def cmd_flag(args, ctx):
    d = ctx.data / "control"
    d.mkdir(parents=True, exist_ok=True)
    if args.cmd == "pause":
        (d / "pause").touch()
        print("The bot will pause at its next step (`eotubot resume` to carry on).")
    elif args.cmd == "resume":
        (d / "pause").unlink(missing_ok=True)
        print("Resumed.")
    else:
        (d / "stop").touch()
        print("The bot will stop at its next step.")
    return 0


def cmd_report(args, ctx):
    from .report import build
    path, n = build(ctx.data, Learner(ctx.data).table())
    print(f"Report of {n} match(es): {path}")
    if args.open:
        webbrowser.open(Path(path).as_uri())
    return 0


def cmd_settings(args, ctx):
    print(f"Built-in settings: {config.PKG / 'defaults.toml'}")
    print(f"Your changes:      {ctx.data / 'settings.toml'}")
    cfg = ctx.cfg
    print("\nMacros:")
    for name, steps in cfg["macros"].items():
        print(f"  {name}: " + " | ".join(steps))
    print("\nStrategies:")
    for name, s in cfg["strategies"].items():
        print(f"  {name}: {s.get('note', '')}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eotubot", description="Empires of the Undergrowth bot for testing a "
                                 "multiplayer mod with two PCs.")
    ap.add_argument("--data", help="data folder (default: per-user app data)")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="check this PC is ready")
    p.add_argument("--peer", help="also test the connection to the host PC at this address")
    p = sub.add_parser("teach", help="show the bot where things are on screen")
    p.add_argument("screens", nargs="*", help="only these screens (menu, lobby, match, nest, pause, victory, ...)")
    p.add_argument("--missing", action="store_true", help="only spots not taught yet")
    p.add_argument("--countdown", type=int, default=0, help="read the mouse N s after Enter instead of F8")
    p = sub.add_parser("teach-at", help="teach one spot by position (x y in window pixels, or @fx,fy)")
    p.add_argument("spot")
    p.add_argument("x")
    p.add_argument("y", nargs="?")
    p = sub.add_parser("shot", help="save a screenshot of the game (and a copy with a grid)")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("forget", help="forget taught spots")
    p.add_argument("spots", nargs="+")
    p = sub.add_parser("watch", help="print what the bot sees")
    p.add_argument("--seconds", type=float, default=0)
    p = sub.add_parser("try", help="run one macro now")
    p.add_argument("macro")
    p.add_argument("--times", type=int, default=1)
    p.add_argument("--delay", type=float, default=3.0)
    p.add_argument("--host-ip", help="value for {host_ip} in the macro")
    p = sub.add_parser("run", help="play: run host, run join HOST_IP, or run solo")
    p.add_argument("role", choices=ROLES)
    p.add_argument("host", nargs="?", help="the host PC's address (join only)")
    p.add_argument("--matches", type=int, default=0, help="stop after this many (0 = keep going)")
    p.add_argument("--strategy", help="always play this strategy")
    p.add_argument("--seed", type=int, help="random seed, to repeat a run")
    p.add_argument("--port", type=int, help="link port (default from settings: 47390)")
    for name in ("pause", "resume", "stop"):
        sub.add_parser(name, help=f"{name} a running bot")
    p = sub.add_parser("report", help="write report.html")
    p.add_argument("--open", action="store_true", help="open it in the browser")
    sub.add_parser("settings", help="where the settings are, and the macros and strategies")

    args = ap.parse_args(argv)
    ctx = Ctx(args)
    handlers = {"check": cmd_check, "teach": cmd_teach, "teach-at": cmd_teach_at, "shot": cmd_shot,
                "forget": cmd_forget, "watch": cmd_watch,
                "try": cmd_try, "run": cmd_run, "pause": cmd_flag, "resume": cmd_flag, "stop": cmd_flag,
                "report": cmd_report, "settings": cmd_settings}
    try:
        return handlers[args.cmd](args, ctx) or 0
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        ctx.close()

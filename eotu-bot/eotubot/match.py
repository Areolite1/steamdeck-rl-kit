"""Plays matches: gets both PCs into the same match, plays it, and checks the two games agree.

What counts as a problem with the mod (each one saves the last few screenshots):
  frozen / hung      the picture stopped changing (stalled, or paused for too long)
  crash              the game window disappeared mid-match
  disconnected       the mod's connection-lost message showed
  dropped_to_menu    back at the menu or lobby with no end screen
  unknown_screen     a screen the bot doesn't know stayed up (an error message?)
  one_sided_end      one PC's match ended, the other still shows it: the games disagree
  outcome_mismatch   both PCs won, or both lost: the games disagree
  no_end_seen        this PC's match ended and the other PC never saw it end
  no_start / join_failed / host_failed / menu_failed / no_answer   getting into a match failed
"""
import base64
import csv
import json
import platform
import time
from pathlib import Path, PurePosixPath

from . import VERSION
from .game import GameGone
from .logs import collect, stamp
from .strategy import Plan
from .vision import Motion, save_png

END_SCREENS = ("victory", "defeat")
MOTION_EPS = 0.05
CSV_FIELDS = ["id", "started", "length_s", "host_strategy", "host_outcome", "join_strategy",
              "join_outcome", "problems", "folder"]


class Record:
    """Everything about one match, kept in runs/<id>/ in the data folder."""

    def __init__(self, data, mid, mode, side, log):
        self.data, self.mid, self.mode, self.side, self.log = data, mid, mode, side, log
        self.dir = data / "runs" / mid
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        self.started = time.time()
        self.problems, self.notes = [], []
        self.sides = {side: {"name": platform.node()}}
        self._events = open(self.dir / "events.jsonl", "a", encoding="utf-8")

    def event(self, kind, **d):
        d = dict(d, kind=kind, at=round(time.time(), 2))
        self._events.write(json.dumps(d) + "\n")
        self._events.flush()

    def problem(self, kind, side, detail, game=None, t=None):
        shots = game.save_recent(self.dir / "shots", f"{self.side}_{kind}") if game is not None else []
        p = {"kind": kind, "side": side, "t": None if t is None else round(t, 1), "detail": detail,
             "shots": shots, "seen_by": self.side}
        self.problems.append(p)
        self.event("problem", **p)
        self.log(f"PROBLEM [{side}] {kind}: {detail}")
        return p

    def merge(self, problems):
        have = {(p["kind"], p["side"], p["detail"]) for p in self.problems}
        for p in problems or []:
            if (p.get("kind"), p.get("side"), p.get("detail")) not in have:
                self.problems.append(p)
                have.add((p.get("kind"), p.get("side"), p.get("detail")))
                self.event("problem_from_other_pc", **p)

    def finish(self, length):
        info = {"id": self.mid, "bot": VERSION, "mode": self.mode, "record_of": self.side,
                "started": stamp(self.started), "length_s": round(length or 0, 1), "sides": self.sides,
                "problems": self.problems, "notes": self.notes,
                "verdict": "problems" if self.problems else "ok"}
        (self.dir / "match.json").write_text(json.dumps(info, indent=1), "utf-8")
        self._events.close()
        path = self.data / "matches.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, CSV_FIELDS)
            if new:
                w.writeheader()
            h, j = self.sides.get("host", self.sides.get("solo", {})), self.sides.get("join", {})
            w.writerow({"id": self.mid, "started": info["started"], "length_s": info["length_s"],
                        "host_strategy": h.get("strategy", ""), "host_outcome": h.get("outcome", ""),
                        "join_strategy": j.get("strategy", ""), "join_outcome": j.get("outcome", ""),
                        "problems": ";".join(sorted({p["kind"] for p in self.problems})),
                        "folder": str(self.dir)})
        return info


class Runner:
    def __init__(self, role, game, macros, learner, cfg, data, log, rng, link=None, host_ip=None,
                 strategy=None):
        self.role, self.game, self.macros, self.learner = role, game, macros, learner
        self.cfg, self.data, self.log, self.rng = cfg, data, log, rng
        self.link, self.host_ip, self.forced = link, host_ip, strategy
        self.t = cfg["timing"]
        self.side = role
        self.other = {"host": "join", "join": "host"}.get(role)
        self.in_match = tuple(cfg["detect"]["in_match"])
        self.peer_status = None

    # -- the loop ----------------------------------------------------------------------------
    def run(self, matches=0):
        done = 0
        while matches <= 0 or done < matches:
            self.game.control.check()
            if not self.ensure_game():
                self.game.sleep(30)
                continue
            if self.link and not self.link.connected:
                who = "the joining bot" if self.role == "host" else f"the host bot at {self.host_ip}"
                self.log(f"Waiting for {who} (port {self.link.port})...")
                while not self.link.wait_connected(5):
                    self.game.control.check()
            if self.role == "host":
                self.host_match()
            elif self.role == "join":
                self.join_match()
            else:
                self.solo_match()
            done += 1
        self.log(f"Played {done} match(es). `eotubot report` makes the summary page.")

    def new_id(self):
        return time.strftime("%Y%m%d-%H%M%S") + f"-{self.rng.randrange(16 ** 4):04x}"

    # -- getting into a match ------------------------------------------------------------------
    def host_match(self):
        mid = self.new_id()
        strat = self.learner.pick(self.cfg, self.rng, self.forced)
        rec = Record(self.data, mid, "pair", "host", self.log)
        rec.sides["host"]["strategy"] = strat
        self.link.forget_except(mid)
        self.link.send("plan", match=mid, strategy=strat, name=self.link.name)
        self.log(f"=== Match {mid}: this PC hosts and plays '{strat}'")
        ok_menu = self.to_menu()
        self.link.send("at_menu", match=mid, ok=ok_menu)
        peer = self.wait_peer(rec, "at_menu", self.t["menu_timeout"] + 60)
        if peer and peer["op"] == "at_menu":
            rec.sides["join"] = {"name": peer.get("name"), "strategy": peer.get("strategy")}
        if not ok_menu:
            rec.problem("menu_failed", "host", "The host couldn't get back to the main menu", self.game)
            return self.abort(rec)
        if peer is None:
            rec.problem("no_answer", "join", "The joining bot didn't answer (is it running?)")
            return self.abort(rec)
        if peer["op"] == "abort" or not peer.get("ok"):
            rec.problem("menu_failed", "join", "The joining PC couldn't get back to the main menu")
            return self.abort(rec)
        if not self.macros.run("host_lobby", self.game):
            rec.problem("host_failed", "host", "Hosting a game didn't work (check `eotubot try host_lobby`)",
                        self.game)
            return self.abort(rec)
        self.link.send("hosted", match=mid)
        joined = self.wait_peer(rec, "joined", self.t["lobby_timeout"] + 60)
        if joined is None or joined["op"] == "abort" or not joined.get("ok"):
            if joined is None:
                rec.problem("no_answer", "join", "The joining bot didn't say whether it joined")
            self.macros.run("leave_lobby", self.game)
            return self.abort(rec)
        self.game.sleep(self.t["lobby_settle"])
        self.macros.run("ready", self.game)
        started = self.macros.run("start_match", self.game)
        self.link.send("started", match=mid, ok=started)
        if not started:
            rec.problem("host_failed", "host", "Couldn't press start (check `eotubot try start_match`)", self.game)
        return self.enter_and_play(rec, strat)

    def join_match(self):
        self.log("Waiting for the host bot to start a match...")
        plan = self.link.get("plan", None, check=self.game.control.check)
        mid = plan["match"]
        self.link.forget_except(mid)
        strat = self.learner.pick(self.cfg, self.rng, self.forced)
        rec = Record(self.data, mid, "pair", "join", self.log)
        rec.sides["join"]["strategy"] = strat
        rec.sides["host"] = {"name": plan.get("name"), "strategy": plan.get("strategy")}
        self.log(f"=== Match {mid}: this PC joins and plays '{strat}' (host plays '{plan.get('strategy')}')")
        ok_menu = self.to_menu()
        if not ok_menu:
            rec.problem("menu_failed", "join", "The joining PC couldn't get back to the main menu", self.game)
        self.link.send("at_menu", match=mid, ok=ok_menu, strategy=strat, name=self.link.name,
                       problems=rec.problems)
        if not ok_menu:
            return self.abort(rec, tell=False)
        hosted = self.wait_peer(rec, "hosted", self.t["menu_timeout"] + self.t["lobby_timeout"] + 120)
        if hosted is None or hosted["op"] == "abort":
            if hosted is None:
                rec.problem("no_answer", "host", "The host bot never said it was hosting")
            return self.abort(rec, tell=hosted is None)
        ok = self.macros.run("join_lobby", self.game, ctx={"host_ip": self.host_ip or ""})
        if ok:
            self.macros.run("ready", self.game)
        else:
            rec.problem("join_failed", "join", "Joining didn't work (check `eotubot try join_lobby`)", self.game)
        self.link.send("joined", match=mid, ok=ok, problems=rec.problems)
        if not ok:
            return self.abort(rec, tell=False)
        started = self.wait_peer(rec, "started", self.t["lobby_timeout"] + 120)
        if started is None or started["op"] == "abort":
            if started is None:
                rec.problem("no_answer", "host", "The host bot never started the match")
            return self.abort(rec, tell=started is None)
        return self.enter_and_play(rec, strat)

    def solo_match(self):
        mid = self.new_id()
        strat = self.learner.pick(self.cfg, self.rng, self.forced)
        rec = Record(self.data, mid, "solo", "solo", self.log)
        rec.sides["solo"]["strategy"] = strat
        if "solo_start" in self.macros.steps and self.macros.available("solo_start", self.game.profile):
            self.macros.run("solo_start", self.game)
        else:
            self.log("Solo: start a match yourself (a Skirmish, say). The bot takes over when it sees it.")
        while not self.game.wait_screen(self.in_match, 30):
            self.log("Still waiting for a match screen...")
        self.log(f"=== Match {mid}: playing '{strat}'")
        outcome, length = self.play(rec, strat)
        return self.finish(rec, outcome, strat, length)

    def enter_and_play(self, rec, strat):
        here = self.game.wait_screen(self.in_match, self.t["load_timeout"])
        if not here:
            rec.problem("no_start", self.side, "The match didn't start on this PC", self.game)
        self.link.send("in_match", match=rec.mid, ok=here, problems=rec.problems)
        peer = self.wait_peer(rec, "in_match", self.t["load_timeout"] + 60)
        if peer is None:
            rec.problem("no_answer", self.other, "The other bot didn't say whether its match started")
        if not here or peer is None or peer["op"] != "in_match" or not peer.get("ok"):
            if here:
                self.macros.run("leave_match", self.game)
            return self.finish(rec, "no_start", strat, 0)
        outcome, length = self.play(rec, strat)
        return self.finish(rec, outcome, strat, length)

    def wait_peer(self, rec, ops, timeout):
        ops = {ops} if isinstance(ops, str) else set(ops)
        msg = self.link.get(ops | {"abort"}, timeout, match=rec.mid, check=self.game.control.check)
        if msg:
            rec.merge(msg.get("problems"))
        return msg

    def abort(self, rec, tell=True):
        if tell and self.link:
            self.link.send("abort", match=rec.mid, problems=rec.problems)
        rec.sides[self.side]["outcome"] = "no_start"
        rec.finish(0)
        self.to_menu()
        return "no_start"

    # -- playing ---------------------------------------------------------------------------------
    def play(self, rec, strat):
        g, tc, me = self.game, self.t, self.side
        plan = Plan(strat, self.cfg, self.rng, lambda m: self.macros.available(m, g.profile))
        rec.event("plan", strategy=strat, rules=plan.describe())
        self.log(f"In the match. '{strat}': " + "; ".join(plan.describe()))
        g.minimap.baseline = []
        g.motion = Motion()
        has_end_screens = any(s in g.profile.screen_patches() for s in END_SCREENS)
        t0 = time.monotonic()
        last_status, last_shot = -1e9, 0.0
        still_since, frozen_reported = None, False
        unknown_since, unknown_reported = None, False
        peer_end, peer_end_t, link_down_since, link_reported = None, None, None, False
        outcome, t = None, 0.0
        while outcome is None:
            g.control.check()
            loop_start = time.monotonic()
            t = loop_start - t0
            try:
                frame = g.frame()
            except GameGone:
                rec.problem("crash", me, "The game window disappeared during the match (closed or crashed)", g, t)
                outcome = "crash"
                break
            screen, _, _ = g.screen(frame)
            obs = g.minimap.read(frame, t)
            moving = g.motion.change(frame) > MOTION_EPS

            # Frozen picture
            if moving:
                if frozen_reported:
                    rec.event("moving_again", t=round(t, 1))
                still_since, frozen_reported = None, False
            elif still_since is None:
                still_since = t
            frozen_for = 0.0 if still_since is None else t - still_since
            if frozen_for >= tc["frozen_after"] and not frozen_reported:
                rec.problem("frozen", me, f"The picture hasn't changed for {frozen_for:.0f} s "
                            "(game frozen, stalled or paused)", g, t)
                frozen_reported = True
            if frozen_for >= tc["hung_after"]:
                rec.problem("hung", me, f"Frozen for {frozen_for:.0f} s: leaving the match", g, t)
                outcome = "hung"
                break

            # What the screen says
            if screen in END_SCREENS:
                save_png(rec.dir / "shots" / f"{me}_{screen}.png", frame, half=True)
                outcome = screen
                break
            if screen == "disconnected":
                rec.problem("disconnected", me, "The mod's connection-lost message showed", g, t)
                outcome = "disconnected"
                break
            if screen in ("menu", "lobby"):
                if has_end_screens:
                    rec.problem("dropped_to_menu", me, f"Back at the {screen} without an end screen", g, t)
                outcome = "ended"
                break
            if screen == "unknown":
                unknown_since = t if unknown_since is None else unknown_since
                if t - unknown_since >= tc["unknown_after"] and not unknown_reported:
                    rec.problem("unknown_screen", me, f"A screen the bot doesn't know showed for "
                                f"{t - unknown_since:.0f} s (an error message?)", g, t)
                    unknown_reported = True
            else:
                unknown_since, unknown_reported = None, False
            if screen == "pause":
                self.macros.run("close_pause_menu", g)

            # The other PC
            if self.link:
                for st in self.link.take_all("status", rec.mid):
                    self.peer_status = st
                e = self.link.get("ended", 0, match=rec.mid)
                if e:
                    peer_end, peer_end_t = e, t
                    rec.merge(e.get("problems"))
                    self.log(f"The other PC's match ended ({e.get('outcome')}); waiting to see the same here")
                if peer_end is not None and t - peer_end_t >= tc["end_grace"]:
                    rec.problem("one_sided_end", me, f"The other PC's match ended ({peer_end.get('outcome')}) "
                                f"{tc['end_grace']:.0f} s ago but this PC still shows the match: "
                                "the two games disagree (desync)", g, t)
                    outcome = "left"
                    break
                if not self.link.connected:
                    link_down_since = t if link_down_since is None else link_down_since
                    if t - link_down_since >= 60 and not link_reported:
                        rec.notes.append(f"The bots lost touch at {link_down_since:.0f} s (network between the "
                                         "PCs, not the mod); this PC kept playing")
                        link_reported = True
                else:
                    link_down_since = None

            if t >= tc["match_limit"]:
                rec.notes.append(f"Time limit ({tc['match_limit']:.0f} s): the bots left the match")
                outcome = "time_limit"
                break

            # Play
            if screen in ("match", "nest"):
                for name in plan.due(t, obs):
                    ok = self.macros.run(name, g)
                    rec.event("action", name=name, ok=ok, t=round(t, 1))

            if self.link and t - last_status >= tc["status_every"]:
                self.link.send("status", match=rec.mid, t=round(t, 1), screen=screen, moving=moving, **obs)
                last_status = t
            if tc.get("shot_every") and t - last_shot >= tc["shot_every"]:
                save_png(rec.dir / "shots" / f"{me}_t{int(t):05d}.png", frame, half=True)
                last_shot = t
            g.sleep(max(0.0, tc["tick"] - (time.monotonic() - loop_start)))

        t = time.monotonic() - t0
        self.log(f"Match over on this PC after {t / 60:.1f} min: {outcome}")
        if self.link:
            self.link.send("ended", match=rec.mid, outcome=outcome, t=round(t, 1), problems=rec.problems)
        if outcome in ("left", "hung", "time_limit"):
            self.macros.run("leave_match", g)
        if self.link and peer_end is None:
            wait = tc["end_grace"] + 30
            e = self.wait_peer(rec, "ended", wait)
            if e is None or e["op"] != "ended":
                rec.problem("no_end_seen", self.other, f"This PC's match ended ({outcome}) but the other PC "
                            f"didn't see its match end within {wait:.0f} s", None, t)
        return outcome, t

    # -- after a match -----------------------------------------------------------------------------
    def finish(self, rec, outcome, strat, length):
        rec.sides[self.side]["outcome"] = outcome
        if self.link:
            self.link.send("report", match=rec.mid, outcome=outcome, strategy=strat, problems=rec.problems)
            rep = self.wait_peer(rec, "report", self.t["end_grace"] + 120)
            if rep is not None and rep["op"] == "report":
                rec.sides.setdefault(self.other, {}).update(outcome=rep.get("outcome"), strategy=rep.get("strategy"))
                mine, theirs = outcome, rep.get("outcome")
                if mine == theirs and mine in END_SCREENS:
                    rec.problem("outcome_mismatch", "both", f"Both PCs saw '{mine}': the two games disagree "
                                "about who won (desync)", None, length)
            elif outcome != "no_start":
                rec.problem("no_answer", self.other, "The other bot didn't report how its match ended")
        try:
            names = collect(self.cfg, rec.started, rec.dir / "logs")
            if names:
                rec.event("logs", files=names)
        except OSError as e:
            rec.notes.append(f"Couldn't copy the game's logs: {e}")
        if self.link and self.role == "join" and self.cfg["evidence"].get("send_to_host", True):
            self.send_files(rec)
        if self.link and self.role == "host":
            self.receive_files(rec)
        strat_cfg = self.cfg["strategies"].get(strat, {})
        if strat_cfg.get("learn", True) and outcome != "no_start":
            self.learner.record(strat, outcome)
        info = rec.finish(length)
        verdict = "no problems" if info["verdict"] == "ok" else f"{len(info['problems'])} problem(s)"
        self.log(f"=== Match {rec.mid} done: {outcome}, {verdict}. Saved in {rec.dir}")
        if outcome in END_SCREENS:
            self.macros.run("after_match", self.game)
        self.to_menu()
        return outcome

    def send_files(self, rec):
        budget = int(float(self.cfg["evidence"].get("max_send_mb", 40)) * 1024 * 1024)
        sent = 0
        for p in sorted(rec.dir.rglob("*")):
            if not p.is_file() or p.name == "match.json":
                continue
            size = p.stat().st_size
            if size > budget:
                continue
            budget -= size
            rel = p.relative_to(rec.dir).as_posix()
            if self.link.send("file", match=rec.mid, name=rel, data=base64.b64encode(p.read_bytes()).decode()):
                sent += 1
        self.link.send("files_done", match=rec.mid, count=sent)

    def receive_files(self, rec):
        dest = rec.dir / "peer"
        got = 0
        while True:
            m = self.link.get(("file", "files_done"), 120, match=rec.mid, check=self.game.control.check)
            if m is None:
                rec.notes.append("The joining PC's screenshots and logs didn't arrive")
                return
            if m["op"] == "files_done":
                break
            parts = [p for p in PurePosixPath(m.get("name", "file")).parts if p not in ("..", "/", "")]
            if not parts:
                continue
            path = dest.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(m.get("data", "")))
            got += 1
        if got:
            rec.event("peer_files", count=got)

    # -- getting back to the menu, and keeping the game running -------------------------------
    def to_menu(self):
        end = time.monotonic() + self.t["menu_timeout"]
        while time.monotonic() < end:
            self.game.control.check()
            try:
                screen = self.game.screen()[0]
            except GameGone:
                if not self.ensure_game():
                    return False
                continue
            if screen == "menu":
                return True
            if screen in END_SCREENS:
                self.macros.run("after_match", self.game)
            elif screen == "disconnected":
                self.macros.run("dismiss_disconnect", self.game)
            elif screen in self.in_match:
                self.macros.run("leave_match", self.game)
            elif screen == "lobby":
                self.macros.run("leave_lobby", self.game)
            else:
                self.game.key("escape")
            self.game.sleep(2)
        return False

    def ensure_game(self):
        if self.game.find(force=True):
            return True
        if self.cfg["game"].get("relaunch", True):
            self.log("The game isn't running: starting it through Steam")
            try:
                self.game.p.launch_game(self.cfg["game"]["launch"])
            except (OSError, NotImplementedError) as e:
                self.log(f"Couldn't start the game: {e}")
        else:
            self.log("Waiting for the game window (start the game)...")
        end = time.monotonic() + self.t["load_timeout"]
        while time.monotonic() < end:
            self.game.control.check()
            if self.game.find(force=True):
                self.game.sleep(10 * float(self.t.get("wait_scale", 1.0)))
                return True
            time.sleep(2)
        self.log("The game window still isn't there")
        return False


def record_dirs(data):
    runs = Path(data) / "runs"
    return sorted((p for p in runs.glob("*") if (p / "match.json").exists()), reverse=True) if runs.exists() else []

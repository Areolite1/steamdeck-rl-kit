"""How a match is played (rules from [strategies]) and which strategy to pick next.

Picking uses Thompson sampling: each strategy's wins and losses so far give a Beta
distribution; the bot draws once from each and plays the highest draw. Strategies that win
get picked more, and the others still get tried now and then, so the two bots keep adapting to
each other without any heavy machinery.
"""
import json
import time

from .config import Expr


class Rule:
    def __init__(self, d, rng, jitter):
        self.do = d["do"]
        self.rng, self.jitter = rng, float(jitter)
        self.every = self._j(float(d["every"])) if d.get("every") else None
        self.start = self._j(float(d.get("from", 0)))
        self.stop = self._j(float(d["until"])) if "until" in d else None
        self.when = Expr(d["when"]) if d.get("when") else None
        self.once = bool(d.get("once", False))
        self.chance = float(d.get("chance", 1.0))
        first = 0.0 if (self.once or not self.every) else rng.uniform(0, 0.3 * self.every)
        self.next_at = self.start + first
        self.done = False
        self.fired = 0

    def _j(self, v):
        return v * self.rng.uniform(1 - self.jitter, 1 + self.jitter) if v else v

    def due(self, t, env):
        if self.done or t < self.next_at:
            return False
        if self.stop is not None and t > self.stop:
            self.done = True
            return False
        if self.when is not None and not self.when(env):
            return False
        if self.once or not self.every:
            self.done = True
        else:
            self.next_at = t + self._j(self.every)
        if self.rng.random() > self.chance:
            return False
        self.fired += 1
        return True

    def describe(self):
        bits = [self.do]
        if self.every:
            bits.append(f"every {self.every:.0f}s")
        if self.start:
            bits.append(f"from {self.start:.0f}s")
        if self.stop is not None:
            bits.append(f"until {self.stop:.0f}s")
        if self.once:
            bits.append("once")
        if self.when is not None:
            bits.append(f"when {self.when.text}")
        return " ".join(bits)


class Plan:
    """One match's worth of a strategy, with its own random timings."""

    def __init__(self, name, cfg, rng, available):
        self.name = name
        strat = cfg["strategies"][name]
        jitter = cfg["strategy"].get("jitter", 0.2)
        self.rules = [Rule(r, rng, jitter) for r in strat.get("rules", [])]
        self.pool = [m for m in cfg["strategy"].get("random_pool", []) if available(m)]
        self.rng = rng

    def due(self, t, obs):
        env = dict(obs, t=t)
        out = []
        for r in self.rules:
            if r.due(t, env):
                if r.do == "*":
                    if self.pool:
                        out.append(self.rng.choice(self.pool))
                else:
                    out.append(r.do)
        return out

    def describe(self):
        return [r.describe() for r in self.rules]


class Learner:
    def __init__(self, data):
        self.path = data / "learning.json"
        self.stats = {}
        if self.path.exists():
            try:
                self.stats = json.loads(self.path.read_text("utf-8")).get("strategies", {})
            except ValueError:
                self.stats = {}

    def pick(self, cfg, rng, forced=None):
        strategies = cfg["strategies"]
        if forced:
            if forced not in strategies:
                raise SystemExit(f"No strategy called {forced!r}. Strategies: {', '.join(strategies)}")
            return forced
        learnable = [n for n, s in strategies.items() if s.get("learn", True)]
        chaos = [n for n, s in strategies.items() if not s.get("learn", True)]
        if chaos and (not learnable or rng.random() < float(cfg["strategy"].get("chaos_share", 0.15))):
            return rng.choice(chaos)

        def draw(n):
            s = self.stats.get(n, {})
            return rng.betavariate(s.get("win", 0) + 1, s.get("loss", 0) + 1)

        return max(learnable, key=draw)

    def record(self, name, outcome):
        s = self.stats.setdefault(name, {"win": 0, "loss": 0, "other": 0})
        key = {"victory": "win", "defeat": "loss"}.get(outcome, "other")
        s[key] = s.get(key, 0) + 1
        s["last"] = time.strftime("%Y-%m-%d %H:%M")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"strategies": self.stats}, indent=1), "utf-8")
        tmp.replace(self.path)

    def table(self):
        rows = []
        for n, s in sorted(self.stats.items()):
            w, lo = s.get("win", 0), s.get("loss", 0)
            rate = f"{100 * w / (w + lo):.0f}%" if w + lo else "-"
            rows.append((n, w, lo, s.get("other", 0), rate))
        return rows

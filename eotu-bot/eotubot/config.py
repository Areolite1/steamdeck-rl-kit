"""Settings (defaults.toml + the user's settings.toml) and the bot's data folder."""
import ast
import copy
import operator
import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

PKG = Path(__file__).resolve().parent

USER_TEMPLATE = """\
# Your changes to the bot's settings. Anything here replaces the same key in the built-in
# defaults.toml (shown in full by `eotubot settings`). Examples:
#
# [timing]
# wait_scale = 1.5          # this PC is slow: wait longer between clicks
#
# [macros]
# build_worker = ["click nest_minimap", "wait 1", "key b", "click brood_worker", "click nest_spot_*"]
#
# [strategy]
# chaos_share = 0.5         # more stress-test matches
"""


def data_dir(override=None):
    if override:
        p = Path(override)
    elif os.environ.get("EOTUBOT_DATA"):
        p = Path(os.environ["EOTUBOT_DATA"])
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "eotu-bot"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "eotu-bot"
    p.mkdir(parents=True, exist_ok=True)
    return p


def merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def defaults():
    return tomllib.loads((PKG / "defaults.toml").read_text("utf-8"))


def load(data, extra=None):
    cfg = defaults()
    user = Path(data) / "settings.toml"
    if not user.exists():
        user.parent.mkdir(parents=True, exist_ok=True)
        user.write_text(USER_TEMPLATE, "utf-8")
    try:
        cfg = merge(cfg, tomllib.loads(user.read_text("utf-8")))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"settings.toml has a mistake: {e}\n  ({user})") from e
    if extra:
        cfg = merge(cfg, extra)
    return cfg


def problems(cfg):
    """Mistakes in the settings, as readable lines (empty list = fine)."""
    from .macros import Macros  # here to avoid an import loop
    out = []
    spots, screens = cfg.get("spots", {}), cfg.get("screens", {})
    for name, s in spots.items():
        if s.get("screen") not in screens:
            out.append(f"spot {name}: screen {s.get('screen')!r} isn't in [screens]")
    try:
        macros = Macros(cfg)
    except ValueError as e:
        return out + [str(e)]
    out += macros.check()
    pool = set(cfg.get("strategy", {}).get("random_pool", []))
    for m in sorted(pool - set(cfg.get("macros", {}))):
        out.append(f"strategy.random_pool: no macro called {m!r}")
    for sname, strat in cfg.get("strategies", {}).items():
        for i, rule in enumerate(strat.get("rules", [])):
            do = rule.get("do")
            if do != "*" and do not in cfg.get("macros", {}):
                out.append(f"strategies.{sname} rule {i + 1}: no macro called {do!r}")
            if rule.get("when"):
                try:
                    Expr(rule["when"])
                except ValueError as e:
                    out.append(f"strategies.{sname} rule {i + 1}: {e}")
    for key in ("own", "enemy"):
        try:
            Expr(cfg.get("minimap", {}).get(key, "0"))
        except ValueError as e:
            out.append(f"minimap.{key}: {e}")
    return out


# --- A tiny, safe expression language for conditions and colour rules ------------------------
# Numbers, names, + - * /, comparisons, and/or/not. Works on plain numbers and numpy arrays.

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_CMP = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Eq: operator.eq, ast.NotEq: operator.ne}


class Expr:
    def __init__(self, text):
        self.text = text
        try:
            self.tree = ast.parse(text, mode="eval").body
        except SyntaxError as e:
            raise ValueError(f"can't read {text!r}: {e.msg}") from e
        self._check(self.tree)

    def _check(self, node):
        ok = (ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.BinOp, ast.Compare,
              ast.Name, ast.Load, ast.Constant, *_BIN, *_CMP)
        for n in ast.walk(node):
            if not isinstance(n, ok):
                raise ValueError(f"{self.text!r}: only numbers, names, + - * /, comparisons and "
                                 f"and/or/not are allowed")
            if isinstance(n, ast.Constant) and not isinstance(n.value, (int, float)):
                raise ValueError(f"{self.text!r}: only numbers are allowed as values")

    def names(self):
        return {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}

    def __call__(self, env):
        return self._eval(self.tree, env)

    def _eval(self, n, env):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise KeyError(f"unknown name {n.id!r} in {self.text!r} (known: {', '.join(sorted(env))})")
            return env[n.id]
        if isinstance(n, ast.BinOp):
            return _BIN[type(n.op)](self._eval(n.left, env), self._eval(n.right, env))
        if isinstance(n, ast.UnaryOp):
            v = self._eval(n.operand, env)
            if isinstance(n.op, ast.USub):
                return -v
            return ~v if hasattr(v, "dtype") else (not v)
        if isinstance(n, ast.Compare):
            left, result = self._eval(n.left, env), None
            for op, right_node in zip(n.ops, n.comparators):
                right = self._eval(right_node, env)
                part = _CMP[type(op)](left, right)
                result = part if result is None else _and(result, part)
                left = right
            return result
        if isinstance(n, ast.BoolOp):
            vals = [self._eval(v, env) for v in n.values]
            out = vals[0]
            for v in vals[1:]:
                out = _and(out, v) if isinstance(n.op, ast.And) else _or(out, v)
            return out
        raise ValueError(f"can't evaluate {ast.dump(n)}")


def _and(a, b):
    return (a & b) if hasattr(a, "dtype") or hasattr(b, "dtype") else (a and b)


def _or(a, b):
    return (a | b) if hasattr(a, "dtype") or hasattr(b, "dtype") else (a or b)

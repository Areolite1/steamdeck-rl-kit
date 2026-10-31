"""`eotubot report`: one HTML page with every match, the problems found and their screenshots."""
import html
import json
import time
from collections import Counter
from pathlib import Path

from .match import record_dirs

KIND_TEXT = {
    "frozen": "Picture froze",
    "hung": "Froze for good",
    "crash": "Game closed / crashed",
    "disconnected": "Connection lost",
    "dropped_to_menu": "Dropped to menu",
    "unknown_screen": "Unknown screen",
    "one_sided_end": "Desync: one side ended",
    "outcome_mismatch": "Desync: same result on both",
    "no_end_seen": "Other side never ended",
    "no_start": "Match didn't start",
    "join_failed": "Join failed",
    "host_failed": "Host failed",
    "menu_failed": "Couldn't reach menu",
    "no_answer": "Other bot silent",
}
DESYNC = {"one_sided_end", "outcome_mismatch", "no_end_seen"}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e2e2dc;--bad:#b42318;--ok:#1a7f37;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecece8;--mute:#a3a39c;--line:#33332f;--bad:#ff7b72;--ok:#56d364;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}
.mute{color:var(--mute)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.tile b{display:block;font-size:26px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--mute);font-weight:600}
.bad{color:var(--bad);font-weight:600}.ok{color:var(--ok);font-weight:600}.warn{color:var(--warn)}
.wrap{overflow-x:auto}.shots{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.shots img{height:90px;border-radius:4px;border:1px solid var(--line)}
code{font-size:13px}
"""


def _e(v):
    return html.escape(str(v if v is not None else ""))


def build(data, learner_rows=()):
    data = Path(data)
    matches = []
    for d in record_dirs(data):
        try:
            info = json.loads((d / "match.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        info["_dir"] = d
        matches.append(info)
    kinds = Counter(p["kind"] for m in matches for p in m.get("problems", []))
    played = [m for m in matches if any(s.get("outcome") not in (None, "no_start") for s in m["sides"].values())]
    desyncs = sum(1 for m in matches if any(p["kind"] in DESYNC for p in m.get("problems", [])))
    clean = sum(1 for m in played if not m.get("problems"))
    minutes = sum(m.get("length_s", 0) for m in matches) / 60

    out = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>EotU bot report</title><style>{CSS}</style></head><body><main>",
           "<h1>Empires of the Undergrowth bot report</h1>",
           f"<p class=mute>Made {_e(time.strftime('%Y-%m-%d %H:%M'))} from {_e(data)}</p>",
           "<div class=tiles>"]
    for label, value in (("Matches", len(matches)), ("Played to the end", len(played)),
                         ("Clean matches", clean), ("Desyncs", desyncs),
                         ("Problems", sum(kinds.values())), ("Minutes played", f"{minutes:.0f}")):
        out.append(f"<div class=tile><span class=mute>{_e(label)}</span><b>{_e(value)}</b></div>")
    out.append("</div>")

    if kinds:
        out.append("<h2>Problems by kind</h2><div class=wrap><table><tr><th>Kind</th><th>Count</th></tr>")
        for k, n in kinds.most_common():
            out.append(f"<tr><td>{_e(KIND_TEXT.get(k, k))} <code class=mute>{_e(k)}</code></td><td>{n}</td></tr>")
        out.append("</table></div>")

    if learner_rows:
        out.append("<h2>Strategies on this PC</h2><div class=wrap><table><tr><th>Strategy</th><th>Won</th>"
                   "<th>Lost</th><th>Other</th><th>Win rate</th></tr>")
        for name, w, lo, other, rate in learner_rows:
            out.append(f"<tr><td>{_e(name)}</td><td>{w}</td><td>{lo}</td><td>{other}</td><td>{_e(rate)}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>Matches</h2><div class=wrap><table><tr><th>Match</th><th>Length</th><th>Host</th>"
               "<th>Join</th><th>Result</th></tr>")
    for m in matches:
        sides = m["sides"]

        def side(name):
            s = sides.get(name, {})
            if not s:
                return "<span class=mute>-</span>"
            return f"{_e(s.get('strategy', '?'))}<br><span class=mute>{_e(s.get('outcome', '?'))}</span>"

        host = side("host") if "host" in sides else side("solo")
        probs = m.get("problems", [])
        verdict = (f"<span class=ok>OK</span>" if not probs else
                   f"<span class=bad>{len(probs)} problem(s)</span>")
        out.append(f"<tr><td><a href='#{_e(m['id'])}'>{_e(m['id'])}</a><br><span class=mute>{_e(m['started'])}"
                   f"</span></td><td>{m.get('length_s', 0) / 60:.1f} min</td><td>{host}</td>"
                   f"<td>{side('join')}</td><td>{verdict}</td></tr>")
    out.append("</table></div>")

    for m in matches:
        probs = m.get("problems", [])
        if not probs and not m.get("notes"):
            continue
        rel = m["_dir"].relative_to(data).as_posix()
        out.append(f"<h2 id='{_e(m['id'])}'>Match {_e(m['id'])}</h2>"
                   f"<p class=mute>Folder: <code>{_e(m['_dir'])}</code></p>")
        for note in m.get("notes", []):
            out.append(f"<p class=warn>{_e(note)}</p>")
        for p in probs:
            when = f" at {p['t']:.0f} s" if isinstance(p.get("t"), (int, float)) else ""
            out.append(f"<p><span class=bad>{_e(KIND_TEXT.get(p['kind'], p['kind']))}</span> "
                       f"on <b>{_e(p['side'])}</b>{_e(when)}: {_e(p['detail'])}</p>")
            shots = p.get("shots") or []
            if shots:
                folder = "shots" if p.get("seen_by") in (None, m.get("record_of")) else "peer/shots"
                out.append("<div class=shots>" + "".join(
                    f"<a href='{_e(rel)}/{folder}/{_e(s)}'><img loading=lazy src='{_e(rel)}/{folder}/{_e(s)}' "
                    f"alt='{_e(s)}'></a>" for s in shots[-6:]) + "</div>")
    out.append("</main></body></html>")
    path = data / "report.html"
    path.write_text("\n".join(out), "utf-8")
    return path, len(matches)

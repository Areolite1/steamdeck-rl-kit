"""Reading the screen: which screen is showing, minimap dot counts, and whether the picture moves."""
import struct
import zlib

import numpy as np

from .config import Expr


def patch_size(window_h, share):
    return max(12, int(round(window_h * share)) // 2 * 2)


def crop(frame, cx, cy, size):
    """size x size pixels centred on (cx, cy); parts outside the frame are black."""
    h, w = frame.shape[:2]
    half = size // 2
    out = np.zeros((size, size, 3), np.uint8)
    x0, y0 = int(cx) - half, int(cy) - half
    sx0, sy0 = max(x0, 0), max(y0, 0)
    sx1, sy1 = min(x0 + size, w), min(y0 + size, h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = frame[sy0:sy1, sx0:sx1]
    return out


def resize_nearest(img, size):
    if img.shape[0] == size and img.shape[1] == size:
        return img
    ys = (np.arange(size) * img.shape[0] / size).astype(int)
    xs = (np.arange(size) * img.shape[1] / size).astype(int)
    return img[ys][:, xs]


def similarity(a, b):
    """1.0 = identical, 0.0 = opposite. Mean colour difference, so small changes cost little."""
    if a.shape != b.shape:
        b = resize_nearest(b, a.shape[0])
    return 1.0 - float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) / 255.0


def detect_screen(frame, profile, cfg):
    """-> (screen name or 'unknown', score, {screen: score})."""
    det = cfg["detect"]
    h, w = frame.shape[:2]
    scores = {}
    for screen, names in profile.screen_patches().items():
        sims = []
        for name in names:
            p = profile.patches[name]
            size = patch_size(h, det["patch"])
            here = crop(frame, p["x"] * w, p["y"] * h, size)
            sims.append(similarity(resize_nearest(profile.patch(name), size), here))
        # Every saved picture of a screen must match: use the weakest one.
        scores[screen] = min(sims)
    for screen in det["priority"]:
        s = scores.get(screen, 0.0)
        if s >= det["threshold"]:
            return screen, s, scores
    return "unknown", max(scores.values(), default=0.0), scores


class Minimap:
    """Counts your (green) and enemy (red) dots on the surface minimap."""

    def __init__(self, cfg, profile):
        mm = cfg["minimap"]
        self.own_rule = Expr(mm["own"])
        self.enemy_rule = Expr(mm["enemy"])
        self.near = float(mm.get("near_nest", 0.15))
        self.profile = profile
        self.baseline = []

    def ready(self):
        return self.profile.has("minimap_tl") and self.profile.has("minimap_br")

    def rect(self, w, h):
        a, b = self.profile.spots["minimap_tl"], self.profile.spots["minimap_br"]
        x0, x1 = sorted((int(a["x"] * w), int(b["x"] * w)))
        y0, y1 = sorted((int(a["y"] * h), int(b["y"] * h)))
        return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)

    def read(self, frame, t):
        if not self.ready():
            return {"own": 0, "enemy": 0, "threat": 0, "grown": 1.0}
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.rect(w, h)
        mm = frame[y0:y1, x0:x1].astype(np.float32)
        env = {"r": mm[:, :, 0], "g": mm[:, :, 1], "b": mm[:, :, 2]}
        own = np.asarray(self.own_rule(env), bool)
        enemy = np.asarray(self.enemy_rule(env), bool)
        threat = 0
        if self.profile.has("map_own_nest"):
            n = self.profile.spots["map_own_nest"]
            ny, nx = n["y"] * h - y0, n["x"] * w - x0
            radius = self.near * max(x1 - x0, y1 - y0)
            yy, xx = np.ogrid[: y1 - y0, : x1 - x0]
            threat = int((enemy & ((yy - ny) ** 2 + (xx - nx) ** 2 <= radius ** 2)).sum())
        own_n = int(own.sum())
        if 20 <= t <= 60:
            self.baseline.append(own_n)
        base = float(np.median(self.baseline)) if self.baseline else float(own_n)
        return {"own": own_n, "enemy": int(enemy.sum()), "threat": threat,
                "grown": round(own_n / max(base, 5.0), 2)}


class Motion:
    """Tells whether the picture is still changing (a frozen game shows the same frame)."""

    def __init__(self):
        self.last = None

    def change(self, frame):
        step = max(1, frame.shape[1] // 160)
        small = frame[::step, ::step].mean(axis=2)
        if self.last is None or self.last.shape != small.shape:
            self.last = small
            return 255.0
        d = float(np.abs(small - self.last).mean())
        self.last = small
        return d


# --- PNG files without extra libraries --------------------------------------------------------

def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(rgb, level=6):
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    raw = np.zeros((h, 1 + w * 3), np.uint8)
    raw[:, 1:] = rgb.reshape(h, w * 3)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw.tobytes(), level)) + _chunk(b"IEND", b""))


def save_png(path, rgb, half=False):
    if half:
        rgb = rgb[::2, ::2]
    with open(path, "wb") as f:
        f.write(png_bytes(rgb))


def read_png(path):
    """Reads the PNGs this bot writes (8-bit RGB, no filters). For tests and `eotubot watch`."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * 3)
    assert not raw[:, 0].any(), "only unfiltered PNGs are supported"
    return raw[:, 1:].reshape(h, w, 3).copy()

"""Linux / Steam Deck (Desktop Mode): X11 through ctypes, no compiled extras needed.

- Screenshots: XGetImage on the game's own window (works on X11 and for XWayland windows),
  then the whole screen through mss, then KDE's `spectacle` as a last resort.
- Input: XTest by default. `[input] backend = "uinput"` makes a virtual mouse and keyboard in
  the kernel instead (works under Wayland too; Steam's udev rules usually allow /dev/uinput).
- Proton gives the game window the class steam_app_463530, which is how it's found.
"""
import ctypes
import ctypes.util
import fcntl
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from ctypes import (CFUNCTYPE, POINTER, Structure, Union, byref, c_char, c_char_p, c_int, c_long,
                    c_ubyte, c_uint, c_ulong, c_void_p)

import numpy as np

from .base import BasePlatform, pick_window

# --------------------------------------------------------------------------------------------
# X11
# --------------------------------------------------------------------------------------------


class XImage(Structure):
    # Only the leading fields are read; the image is freed by XDestroyImage.
    _fields_ = [("width", c_int), ("height", c_int), ("xoffset", c_int), ("format", c_int),
                ("data", c_void_p), ("byte_order", c_int), ("bitmap_unit", c_int),
                ("bitmap_bit_order", c_int), ("bitmap_pad", c_int), ("depth", c_int),
                ("bytes_per_line", c_int), ("bits_per_pixel", c_int), ("red_mask", c_ulong),
                ("green_mask", c_ulong), ("blue_mask", c_ulong)]


class XClientMessageEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", c_ulong), ("message_type", c_ulong), ("format", c_int), ("l", c_long * 5)]


class XEvent(Union):
    _fields_ = [("xclient", XClientMessageEvent), ("pad", c_long * 24)]


ERROR_HANDLER = CFUNCTYPE(c_int, c_void_p, c_void_p)
ZPIXMAP = 2
ALL_PLANES = c_ulong(-1).value
CLIENT_MESSAGE = 33
SUBSTRUCTURE_MASK = (1 << 19) | (1 << 20)

KEYSYMS = {"escape": "Escape", "enter": "Return", "space": "space", "tab": "Tab",
           "backspace": "BackSpace", "delete": "Delete", "insert": "Insert", "home": "Home",
           "end": "End", "pageup": "Prior", "pagedown": "Next", "up": "Up", "down": "Down",
           "left": "Left", "right": "Right", "shift": "Shift_L", "ctrl": "Control_L",
           "alt": "Alt_L", "minus": "minus", "equal": "equal", "period": "period",
           "comma": "comma", "slash": "slash", "semicolon": "semicolon", "pause": "Pause"}
KEYSYMS.update({f"f{n}": f"F{n}" for n in range(1, 13)})
CHAR_KEYSYMS = {" ": "space", ".": "period", ",": "comma", "-": "minus", "_": "underscore",
                ":": "colon", ";": "semicolon", "/": "slash", "\\": "backslash", "@": "at",
                "=": "equal", "+": "plus", "#": "numbersign", "!": "exclam", "?": "question",
                "[": "bracketleft", "]": "bracketright", "(": "parenleft", ")": "parenright",
                "'": "apostrophe", '"': "quotedbl", "&": "ampersand", "%": "percent"}
BUTTONS = {"left": 1, "middle": 2, "right": 3}


def _proto(lib, name, restype, *argtypes):
    f = getattr(lib, name)
    f.restype, f.argtypes = restype, list(argtypes)
    return f


class X11:
    def __init__(self):
        path = ctypes.util.find_library("X11") or "libX11.so.6"
        x = self.x = ctypes.CDLL(path)
        D, W, A = c_void_p, c_ulong, c_ulong
        _proto(x, "XOpenDisplay", c_void_p, c_char_p)
        _proto(x, "XCloseDisplay", c_int, D)
        _proto(x, "XDefaultRootWindow", W, D)
        _proto(x, "XDefaultScreen", c_int, D)
        _proto(x, "XDisplayWidth", c_int, D, c_int)
        _proto(x, "XDisplayHeight", c_int, D, c_int)
        _proto(x, "XSetErrorHandler", c_void_p, ERROR_HANDLER)
        _proto(x, "XSync", c_int, D, c_int)
        _proto(x, "XFlush", c_int, D)
        _proto(x, "XFree", c_int, c_void_p)
        _proto(x, "XInternAtom", A, D, c_char_p, c_int)
        _proto(x, "XGetWindowProperty", c_int, D, W, A, c_long, c_long, c_int, A, POINTER(A),
               POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong), POINTER(POINTER(c_ubyte)))
        _proto(x, "XQueryTree", c_int, D, W, POINTER(W), POINTER(W), POINTER(POINTER(W)), POINTER(c_uint))
        _proto(x, "XGetGeometry", c_int, D, W, POINTER(W), POINTER(c_int), POINTER(c_int),
               POINTER(c_uint), POINTER(c_uint), POINTER(c_uint), POINTER(c_uint))
        _proto(x, "XTranslateCoordinates", c_int, D, W, W, c_int, c_int, POINTER(c_int),
               POINTER(c_int), POINTER(W))
        _proto(x, "XGetImage", POINTER(XImage), D, W, c_int, c_int, c_uint, c_uint, c_ulong, c_int)
        _proto(x, "XDestroyImage", c_int, POINTER(XImage))
        _proto(x, "XQueryPointer", c_int, D, W, POINTER(W), POINTER(W), POINTER(c_int),
               POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_uint))
        _proto(x, "XQueryKeymap", c_int, D, c_char * 32)
        _proto(x, "XStringToKeysym", c_ulong, c_char_p)
        _proto(x, "XKeysymToKeycode", c_ubyte, D, c_ulong)
        _proto(x, "XKeycodeToKeysym", c_ulong, D, c_ubyte, c_int)
        _proto(x, "XSendEvent", c_int, D, W, c_int, c_long, POINTER(XEvent))

        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise OSError(f"can't open the X display (DISPLAY={os.environ.get('DISPLAY')!r})")
        self.last_error = 0
        self._handler = ERROR_HANDLER(self._on_error)  # keep a reference: X calls it later
        x.XSetErrorHandler(self._handler)
        self.root = x.XDefaultRootWindow(self.dpy)
        self.screen = x.XDefaultScreen(self.dpy)
        self.xt = None
        try:
            xt = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
            _proto(xt, "XTestQueryExtension", c_int, D, POINTER(c_int), POINTER(c_int),
                   POINTER(c_int), POINTER(c_int))
            _proto(xt, "XTestFakeMotionEvent", c_int, D, c_int, c_int, c_int, c_ulong)
            _proto(xt, "XTestFakeButtonEvent", c_int, D, c_uint, c_int, c_ulong)
            _proto(xt, "XTestFakeKeyEvent", c_int, D, c_uint, c_int, c_ulong)
            a, b, c, d = c_int(), c_int(), c_int(), c_int()
            if xt.XTestQueryExtension(self.dpy, byref(a), byref(b), byref(c), byref(d)):
                self.xt = xt
        except OSError:
            pass
        self._atoms = {}

    def _on_error(self, _dpy, event):
        # XErrorEvent: int type; Display*; XID resourceid; ulong serial; uchar error_code ...
        try:
            self.last_error = ctypes.cast(event, POINTER(c_ubyte))[8 + 8 + 8 + 8] or 1
        except (ValueError, OSError):
            self.last_error = 1
        return 0

    def sync(self):
        self.x.XSync(self.dpy, 0)
        err, self.last_error = self.last_error, 0
        return err

    def size(self):
        return self.x.XDisplayWidth(self.dpy, self.screen), self.x.XDisplayHeight(self.dpy, self.screen)

    def atom(self, name):
        if name not in self._atoms:
            self._atoms[name] = self.x.XInternAtom(self.dpy, name.encode(), 0)
        return self._atoms[name]

    def prop(self, win, name):
        typ, fmt, n, after = c_ulong(), c_int(), c_ulong(), c_ulong()
        data = POINTER(c_ubyte)()
        st = self.x.XGetWindowProperty(self.dpy, win, self.atom(name), 0, 1 << 16, 0, 0,
                                       byref(typ), byref(fmt), byref(n), byref(after), byref(data))
        self.sync()
        if st != 0 or not data:
            return None
        try:
            if fmt.value == 32:  # format-32 data comes back as C longs
                arr = ctypes.cast(data, POINTER(c_ulong))
                return [arr[i] for i in range(n.value)]
            if fmt.value == 8:
                return ctypes.string_at(data, n.value)
            return None
        finally:
            self.x.XFree(data)

    def children(self, win, depth):
        root, parent, kids, n = c_ulong(), c_ulong(), POINTER(c_ulong)(), c_uint()
        if not self.x.XQueryTree(self.dpy, win, byref(root), byref(parent), byref(kids), byref(n)):
            return []
        ids = [kids[i] for i in range(n.value)]
        if kids:
            self.x.XFree(kids)
        out = list(ids)
        if depth > 1:
            for k in ids:
                out += self.children(k, depth - 1)
        return out

    def title(self, win):
        b = self.prop(win, "_NET_WM_NAME") or self.prop(win, "WM_NAME")
        return b.decode("utf-8", "replace") if isinstance(b, bytes) else ""

    def wm_class(self, win):
        b = self.prop(win, "WM_CLASS")
        return b.replace(b"\0", b" ").decode("utf-8", "replace").strip() if isinstance(b, bytes) else ""

    def geometry(self, win):
        r, x, y, w, h, bw, d = c_ulong(), c_int(), c_int(), c_uint(), c_uint(), c_uint(), c_uint()
        ok = self.x.XGetGeometry(self.dpy, win, byref(r), byref(x), byref(y), byref(w), byref(h),
                                 byref(bw), byref(d))
        if not ok or self.sync():
            return None
        ax, ay, child = c_int(), c_int(), c_ulong()
        if not self.x.XTranslateCoordinates(self.dpy, win, self.root, 0, 0, byref(ax), byref(ay), byref(child)):
            return None
        return (ax.value, ay.value, w.value, h.value)

    def windows(self):
        ids = self.prop(self.root, "_NET_CLIENT_LIST") or self.children(self.root, 3)
        out = []
        for w in ids:
            rect = self.geometry(w)
            if rect:
                out.append((w, self.title(w), self.wm_class(w), rect))
        return out

    def grab(self, drawable, x, y, w, h):
        img = self.x.XGetImage(self.dpy, drawable, x, y, w, h, ALL_PLANES, ZPIXMAP)
        err = self.sync()
        if not img or err:
            if img:
                self.x.XDestroyImage(img)
            return None
        try:
            im = img.contents
            if im.bits_per_pixel != 32:
                raise OSError(f"{im.bits_per_pixel}-bit screens aren't supported (need 24/32-bit colour)")
            raw = ctypes.string_at(im.data, im.bytes_per_line * im.height)
            a = np.frombuffer(raw, np.uint8).reshape(im.height, im.bytes_per_line)
            a = a[:, : im.width * 4].reshape(im.height, im.width, 4)
            rgb = a[:, :, 2::-1] if im.red_mask == 0xFF0000 else a[:, :, :3]
            return np.ascontiguousarray(rgb)
        finally:
            self.x.XDestroyImage(img)

    def pointer(self):
        r, c = c_ulong(), c_ulong()
        rx, ry, wx, wy, m = c_int(), c_int(), c_int(), c_int(), c_uint()
        ok = self.x.XQueryPointer(self.dpy, self.root, byref(r), byref(c), byref(rx), byref(ry),
                                  byref(wx), byref(wy), byref(m))
        return (rx.value, ry.value) if ok else None

    def keymap(self):
        buf = (c_char * 32)()
        self.x.XQueryKeymap(self.dpy, buf)
        return bytes(buf)

    def keycode(self, keysym_name):
        ks = self.x.XStringToKeysym(keysym_name.encode())
        if not ks:
            return None, False
        kc = self.x.XKeysymToKeycode(self.dpy, ks)
        if not kc:
            return None, False
        shifted = self.x.XKeycodeToKeysym(self.dpy, kc, 0) != ks
        return kc, shifted

    def activate(self, win):
        ev = XEvent()
        ev.xclient.type = CLIENT_MESSAGE
        ev.xclient.send_event = 1
        ev.xclient.window = win
        ev.xclient.message_type = self.atom("_NET_ACTIVE_WINDOW")
        ev.xclient.format = 32
        ev.xclient.l[0] = 2  # "from a pager": window managers honour it
        self.x.XSendEvent(self.dpy, self.root, 0, SUBSTRUCTURE_MASK, byref(ev))
        self.sync()

    # XTest
    def motion(self, x, y):
        self.xt.XTestFakeMotionEvent(self.dpy, -1, int(x), int(y), 0)
        self.x.XFlush(self.dpy)

    def fake_button(self, number, down):
        self.xt.XTestFakeButtonEvent(self.dpy, number, int(bool(down)), 0)
        self.x.XFlush(self.dpy)

    def fake_key(self, keycode, down):
        self.xt.XTestFakeKeyEvent(self.dpy, keycode, int(bool(down)), 0)
        self.x.XFlush(self.dpy)

    def close(self):
        if self.dpy:
            self.x.XCloseDisplay(self.dpy)
            self.dpy = None


# --------------------------------------------------------------------------------------------
# uinput: a virtual tablet-style mouse (absolute position) and a keyboard, made by the kernel.
# --------------------------------------------------------------------------------------------

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
REL_WHEEL, ABS_X, ABS_Y = 8, 0, 1
BTN = {"left": 0x110, "right": 0x111, "middle": 0x112}
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045566, 0x40045567
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
ABS_RANGE = 32767
USER_DEV = "<80sHHHHi64i64i64i64i"   # struct uinput_user_dev (1116 bytes)
EVENT = "@llHHi"                    # struct input_event (24 bytes on 64-bit)

LINUX_KEYS = {"escape": 1, "minus": 12, "equal": 13, "backspace": 14, "tab": 15, "enter": 28,
              "ctrl": 29, "semicolon": 39, "shift": 42, "comma": 51, "period": 52, "slash": 53,
              "alt": 56, "space": 57, "home": 102, "up": 103, "pageup": 104, "left": 105,
              "right": 106, "end": 107, "down": 108, "pagedown": 109, "insert": 110, "delete": 111,
              "pause": 119}
LINUX_KEYS.update({str(d): 2 + (d - 1) % 10 for d in range(10)})  # 1..9 -> 2..10, 0 -> 11
LINUX_KEYS["0"] = 11
for _row, _start in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    LINUX_KEYS.update({c: _start + i for i, c in enumerate(_row)})
LINUX_KEYS.update({f"f{n}": 58 + n for n in range(1, 11)})
LINUX_KEYS.update({"f11": 87, "f12": 88})
CHAR_KEYS = {" ": ("space", False), ".": ("period", False), ",": ("comma", False),
             "-": ("minus", False), "_": ("minus", True), ":": ("semicolon", True),
             ";": ("semicolon", False), "/": ("slash", False), "=": ("equal", False),
             "+": ("equal", True)}


def user_dev_struct(name, abs_axes=()):
    absmax = [0] * 64
    for a in abs_axes:
        absmax[a] = ABS_RANGE
    zeros = [0] * 64
    return struct.pack(USER_DEV, name.encode()[:79], 0x03, 0x4545, 0x0001, 1, 0,
                       *absmax, *zeros, *zeros, *zeros)


def event(etype, code, value):
    t = time.time()
    return struct.pack(EVENT, int(t), int((t % 1) * 1e6), etype, code, value)


class UInput:
    def __init__(self, screen_w, screen_h):
        self.w, self.h = max(screen_w, 2), max(screen_h, 2)
        self.mouse = self._device("eotu-bot mouse", keys=BTN.values(), rel=[REL_WHEEL], abs_axes=[ABS_X, ABS_Y])
        self.kbd = self._device("eotu-bot keyboard", keys=range(1, 249))
        time.sleep(1.0)  # give the desktop a moment to notice the new devices

    @staticmethod
    def _device(name, keys, rel=(), abs_axes=()):
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        for k in keys:
            fcntl.ioctl(fd, UI_SET_KEYBIT, k)
        if rel:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
            for r in rel:
                fcntl.ioctl(fd, UI_SET_RELBIT, r)
        if abs_axes:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            for a in abs_axes:
                fcntl.ioctl(fd, UI_SET_ABSBIT, a)
        os.write(fd, user_dev_struct(name, abs_axes))
        fcntl.ioctl(fd, UI_DEV_CREATE)
        return fd

    def _emit(self, fd, *events):
        os.write(fd, b"".join(event(*e) for e in events) + event(EV_SYN, 0, 0))

    def move(self, x, y):
        ax = int(round(x * ABS_RANGE / (self.w - 1)))
        ay = int(round(y * ABS_RANGE / (self.h - 1)))
        self._emit(self.mouse, (EV_ABS, ABS_X, ax), (EV_ABS, ABS_Y, ay))

    def button(self, which, down):
        self._emit(self.mouse, (EV_KEY, BTN[which], int(bool(down))))

    def scroll(self, notches):
        step = 1 if notches > 0 else -1
        for _ in range(abs(int(notches))):
            self._emit(self.mouse, (EV_REL, REL_WHEEL, step))
            time.sleep(0.01)

    def key(self, name, down):
        self._emit(self.kbd, (EV_KEY, LINUX_KEYS[name], int(bool(down))))

    def type_text(self, text):
        for ch in text:
            if ch.isalnum() and ch.isascii():
                name, shift = ch.lower(), ch.isupper()
            elif ch in CHAR_KEYS:
                name, shift = CHAR_KEYS[ch]
            else:
                raise ValueError(f"can't type {ch!r} with the uinput keyboard")
            if shift:
                self.key("shift", True)
            self.key(name, True)
            self.key(name, False)
            if shift:
                self.key("shift", False)
            time.sleep(0.02)

    def close(self):
        for fd in (self.mouse, self.kbd):
            try:
                fcntl.ioctl(fd, UI_DEV_DESTROY)
                os.close(fd)
            except OSError:
                pass


# --------------------------------------------------------------------------------------------


def process_running(pattern):
    rx = re.compile(pattern, re.I)
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if rx.search(cmd) and "eotubot" not in cmd:
            return True
    return False


class LinuxPlatform(BasePlatform):
    name = "linux"

    def __init__(self, cfg):
        self.cfg = cfg
        self.session = os.environ.get("XDG_SESSION_TYPE", "") or ("x11" if os.environ.get("DISPLAY") else "")
        self.x, self.x_error = None, ""
        try:
            self.x = X11()
        except OSError as e:
            self.x_error = str(e)
        backend = cfg["input"].get("backend", "auto")
        self.ui = None
        if backend == "uinput" or (backend == "auto" and (self.x is None or self.x.xt is None)):
            w, h = self.screen_rect()[2:]
            try:
                self.ui = UInput(w, h)
            except OSError as e:
                raise OSError(f"no way to send input: X11/XTest isn't available ({self.x_error or 'no XTest'}) "
                              f"and /dev/uinput can't be opened ({e}). Run the bot in Desktop Mode.") from e
        self.win = None
        self._mss = None
        self.notes = []

    def describe(self):
        cap = "X11 window capture" if self.x else "screen capture via spectacle"
        inp = "uinput virtual mouse/keyboard" if self.ui else "XTest"
        return f"Linux ({self.session or 'unknown session'}): {cap}, input by {inp}"

    # -- the game window -------------------------------------------------------------------
    def find_game(self):
        if self.x:
            found = pick_window(self.x.windows(), self.cfg["game"])
            if found:
                self.win, rect = found
                return rect
            self.win = None
            return None
        # No X at all: assume the game fills the screen while its process runs.
        return self.screen_rect() if process_running(self.cfg["game"].get("process", "Undergrowth")) else None

    def game_alive(self):
        if self.find_game():
            return True
        return process_running(self.cfg["game"].get("process", "Undergrowth"))

    def screen_rect(self):
        if self.x:
            return (0, 0, *self.x.size())
        w, h = self.cfg["input"].get("screen_size", [1280, 800])
        return (0, 0, int(w), int(h))

    def focus_game(self):
        if self.x and self.win:
            self.x.activate(self.win)

    def launch_game(self, url):
        cmd = ["steam", url] if shutil.which("steam") else ["xdg-open", url]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # -- screenshots -------------------------------------------------------------------------
    def capture(self, rect):
        x, y, w, h = rect
        img = None
        if self.x:
            if self.win:
                wr = self.x.geometry(self.win)
                if wr:
                    img = self.x.grab(self.win, x - wr[0], y - wr[1], w, h)
            if img is None or not img.any():
                img = self.x.grab(self.x.root, x, y, w, h)
        if img is None or not img.any():
            img = self._capture_mss(rect)
        if img is None or not img.any():
            img = self._capture_spectacle(rect)
        if img is None:
            raise OSError("couldn't take a screenshot (no X11 access and no spectacle)")
        return img

    def _capture_mss(self, rect):
        try:
            if self._mss is None:
                import mss
                self._mss = mss.mss()
            x, y, w, h = rect
            shot = self._mss.grab({"left": x, "top": y, "width": w, "height": h})
            bgra = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
            return np.ascontiguousarray(bgra[:, :, 2::-1])
        except Exception:  # noqa: BLE001 – mss raises its own error types; any failure = try next
            return None

    def _capture_spectacle(self, rect):
        if not shutil.which("spectacle"):
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "shot.png")
            subprocess.run(["spectacle", "-b", "-n", "-f", "-o", out], timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if not os.path.exists(out):
                return None
            full = np.asarray(Image.open(out).convert("RGB"))
        x, y, w, h = rect
        return np.ascontiguousarray(full[y:y + h, x:x + w])

    # -- input -------------------------------------------------------------------------------
    def move(self, x, y):
        if self.ui:
            self.ui.move(x, y)
        else:
            self.x.motion(x, y)

    def button(self, which, down):
        if self.ui:
            self.ui.button(which, down)
        else:
            self.x.fake_button(BUTTONS[which], down)

    def scroll(self, notches):
        if self.ui:
            self.ui.scroll(notches)
            return
        b = 4 if notches > 0 else 5
        for _ in range(abs(int(notches))):
            self.x.fake_button(b, True)
            self.x.fake_button(b, False)
            time.sleep(0.01)

    def key(self, name, down):
        if self.ui:
            self.ui.key(name, down)
            return
        kc, _ = self.x.keycode(KEYSYMS.get(name, name))
        if kc is None:
            raise ValueError(f"no key for {name!r} on this keyboard layout")
        self.x.fake_key(kc, down)

    def type_text(self, text):
        if self.ui:
            self.ui.type_text(text)
            return
        shift_kc, _ = self.x.keycode("Shift_L")
        for ch in text:
            kc, shifted = self.x.keycode(CHAR_KEYSYMS.get(ch, ch))
            if kc is None:
                raise ValueError(f"can't type {ch!r} on this keyboard layout")
            if shifted:
                self.x.fake_key(shift_kc, True)
            self.x.fake_key(kc, True)
            self.x.fake_key(kc, False)
            if shifted:
                self.x.fake_key(shift_kc, False)
            time.sleep(0.02)

    def cursor(self):
        return self.x.pointer() if self.x else None

    def key_is_down(self, name):
        if not self.x:
            return None
        kc, _ = self.x.keycode(KEYSYMS.get(name, name))
        if kc is None:
            return None
        return bool(self.x.keymap()[kc // 8] & (1 << (kc % 8)))

    def close(self):
        if self.ui:
            self.ui.close()
        if self._mss is not None:
            try:
                self._mss.close()
            except Exception:  # noqa: BLE001
                pass
        if self.x:
            self.x.close()

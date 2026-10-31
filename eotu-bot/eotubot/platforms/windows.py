"""Windows: SendInput for mouse and keyboard (scan codes, which Unreal games accept), mss for
screenshots, and the window list to find the game.

The structures use fixed-size types so they can be checked on any OS (tests/test_platforms.py).
"""
import ctypes
import os
import sys

import numpy as np

from .base import BasePlatform, pick_window

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int32), ("top", ctypes.c_int32),
                ("right", ctypes.c_int32), ("bottom", ctypes.c_int32)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
BUTTON_FLAGS = {("left", True): 0x0002, ("left", False): 0x0004,
                ("right", True): 0x0008, ("right", False): 0x0010,
                ("middle", True): 0x0020, ("middle", False): 0x0040}
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SW_RESTORE = 9

VK = {"escape": 0x1B, "enter": 0x0D, "space": 0x20, "tab": 0x09, "backspace": 0x08,
      "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
      "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
      "shift": 0xA0, "ctrl": 0xA2, "alt": 0xA4, "minus": 0xBD, "equal": 0xBB,
      "period": 0xBE, "comma": 0xBC, "slash": 0xBF, "semicolon": 0xBA, "pause": 0x13}
VK.update({chr(c): ord(chr(c).upper()) for c in range(ord("a"), ord("z") + 1)})
VK.update({str(d): ord(str(d)) for d in range(10)})
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})
# Keys that need the "extended" flag when sent as scan codes.
EXTENDED = {"delete", "insert", "home", "end", "pageup", "pagedown", "left", "up", "right", "down"}


def mouse_input(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def key_input(scan, flags, vk=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


class WindowsPlatform(BasePlatform):
    name = "windows"

    def __init__(self, cfg):
        if sys.platform != "win32":
            raise OSError("the Windows platform only runs on Windows")
        from ctypes import wintypes
        self.cfg = cfg
        # Physical pixels everywhere, so clicks and screenshots agree on scaled (125%, 150%) screens.
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            try:
                ctypes.WinDLL("user32").SetProcessDPIAware()
            except (OSError, AttributeError):
                pass
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        u.SendInput.restype = wintypes.UINT
        u.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
        u.MapVirtualKeyW.restype = wintypes.UINT
        u.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
        u.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        u.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetSystemMetrics.argtypes = (ctypes.c_int,)
        u.GetSystemMetrics.restype = ctypes.c_int
        u.EnumWindows.argtypes = (self.WNDENUMPROC, wintypes.LPARAM)
        u.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        u.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        u.IsWindowVisible.argtypes = (wintypes.HWND,)
        u.IsIconic.argtypes = (wintypes.HWND,)
        u.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
        u.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(POINT))
        u.SetForegroundWindow.argtypes = (wintypes.HWND,)
        u.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        u.GetForegroundWindow.restype = wintypes.HWND
        self.hwnd = None
        self._mss = None

    # -- the game window -------------------------------------------------------------------
    def _windows(self):
        u, out = self.user32, []

        def each(hwnd, _):
            if u.IsWindowVisible(hwnd):
                n = u.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, title, n + 1)
                cls = ctypes.create_unicode_buffer(256)
                u.GetClassNameW(hwnd, cls, 256)
                out.append((hwnd, title.value, cls.value, self._client_rect(hwnd)))
            return True

        u.EnumWindows(self.WNDENUMPROC(each), 0)
        return out

    def _client_rect(self, hwnd):
        r, p = RECT(), POINT(0, 0)
        if self.user32.IsIconic(hwnd) or not self.user32.GetClientRect(hwnd, ctypes.byref(r)):
            return None
        if not self.user32.ClientToScreen(hwnd, ctypes.byref(p)):
            return None
        return (p.x, p.y, r.right - r.left, r.bottom - r.top)

    def find_game(self):
        found = pick_window(self._windows(), self.cfg["game"])
        if not found:
            # A minimised game has no size; remember it anyway so focus_game can restore it.
            self.hwnd = None
            return None
        self.hwnd, rect = found
        return rect

    def screen_rect(self):
        g = self.user32.GetSystemMetrics
        return (0, 0, g(SM_CXSCREEN), g(SM_CYSCREEN))

    def focus_game(self):
        if not self.hwnd:
            self.find_game()
        if not self.hwnd:
            return
        u = self.user32
        if u.IsIconic(self.hwnd):
            u.ShowWindow(self.hwnd, SW_RESTORE)
        if u.GetForegroundWindow() != self.hwnd:
            # Windows only lets the app that had the last input change the foreground window;
            # a tap of Alt counts as that input.
            alt = self.user32.MapVirtualKeyW(VK["alt"], 0)
            self._send(key_input(alt, KEYEVENTF_SCANCODE), key_input(alt, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP))
            u.SetForegroundWindow(self.hwnd)

    def launch_game(self, url):
        os.startfile(url)  # noqa: S606 – a steam:// link, opened by Steam

    # -- screenshots -------------------------------------------------------------------------
    def capture(self, rect):
        if self._mss is None:
            import mss
            self._mss = mss.mss()
        x, y, w, h = rect
        shot = self._mss.grab({"left": x, "top": y, "width": w, "height": h})
        bgra = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(bgra[:, :, 2::-1])

    # -- input -------------------------------------------------------------------------------
    def _send(self, *inputs):
        arr = (INPUT * len(inputs))(*inputs)
        sent = self.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise OSError(f"SendInput sent {sent} of {len(inputs)} (error {ctypes.get_last_error()}); "
                          "is the game running as administrator?")

    def move(self, x, y):
        g = self.user32.GetSystemMetrics
        vx, vy = g(SM_XVIRTUALSCREEN), g(SM_YVIRTUALSCREEN)
        vw, vh = max(g(SM_CXVIRTUALSCREEN), 2), max(g(SM_CYVIRTUALSCREEN), 2)
        nx = int(round((x - vx) * 65535 / (vw - 1)))
        ny = int(round((y - vy) * 65535 / (vh - 1)))
        self.user32.SetCursorPos(int(x), int(y))
        self._send(mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))

    def button(self, which, down):
        self._send(mouse_input(BUTTON_FLAGS[(which, bool(down))]))

    def scroll(self, notches):
        self._send(mouse_input(MOUSEEVENTF_WHEEL, data=int(notches) * 120))

    def key(self, name, down):
        scan = self.user32.MapVirtualKeyW(VK[name], 0)
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0)
        if not down:
            flags |= KEYEVENTF_KEYUP
        self._send(key_input(scan, flags))

    def type_text(self, text):
        for ch in text:
            code = ord(ch)
            self._send(key_input(code, KEYEVENTF_UNICODE), key_input(code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

    def cursor(self):
        p = POINT()
        return (p.x, p.y) if self.user32.GetCursorPos(ctypes.byref(p)) else None

    def key_is_down(self, name):
        return bool(self.user32.GetAsyncKeyState(VK[name]) & 0x8000)

    def describe(self):
        return "Windows: SendInput (scan codes) + mss screenshots"

    def close(self):
        if self._mss is not None:
            self._mss.close()
            self._mss = None

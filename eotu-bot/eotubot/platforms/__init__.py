import sys


def get_platform(cfg):
    """The screen/mouse/keyboard layer for this machine."""
    if sys.platform == "win32":
        from .windows import WindowsPlatform
        return WindowsPlatform(cfg)
    from .linux import LinuxPlatform
    return LinuxPlatform(cfg)

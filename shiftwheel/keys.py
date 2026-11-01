"""Keys that can open or switch a wheel while you drag, per platform.

Windows reads any virtual key with GetAsyncKeyState, so besides the list below a key can be
recorded ("vk:NN"). Fn isn't one of them: on almost every PC keyboard Fn is handled inside the
keyboard and never reaches Windows. macOS reports Fn (the Globe key) as a modifier, so it is
offered there. Linux (X11) only reports the modifier keys and mouse buttons."""
from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

# id → (label, Windows virtual-key code)
_WIN = [
    ("none", "—  (not set)", 0),
    ("shift", "Shift", 0x10), ("ctrl", "Ctrl", 0x11), ("alt", "Alt", 0x12),
    ("lshift", "Left Shift", 0xA0), ("rshift", "Right Shift", 0xA1),
    ("lctrl", "Left Ctrl", 0xA2), ("rctrl", "Right Ctrl", 0xA3),
    ("lalt", "Left Alt", 0xA4), ("ralt", "Right Alt (AltGr)", 0xA5),
    ("win", "Windows key", 0x5B), ("apps", "Menu key", 0x5D),
    ("space", "Space", 0x20), ("tab", "Tab", 0x09), ("capslock", "Caps Lock", 0x14),
    ("backquote", "` (backtick)", 0xC0), ("insert", "Insert", 0x2D), ("pause", "Pause", 0x13),
    ("scrolllock", "Scroll Lock", 0x91),
    *[(f"f{i}", f"F{i}", 0x6F + i) for i in range(1, 25)],
    ("mbutton", "Middle mouse button", 0x04),
    ("xbutton1", "Mouse back button", 0x05), ("xbutton2", "Mouse forward button", 0x06),
]

# id → (label, NSEvent modifier flag or -keycode, or mouse button bit as ("mouse", n))
_MAC_FLAGS = {"capslock": 1 << 16, "shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19, "cmd": 1 << 20,
              "fn": 1 << 23}
_MAC_KEYCODES = {"space": 49, "tab": 48, "backquote": 50,
                 **{f"f{i}": c for i, c in enumerate((122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111), 1)}}
_MAC_MOUSE = {"mbutton": 2, "xbutton1": 3, "xbutton2": 4}
_MAC = [
    ("none", "—  (not set)"),
    ("shift", "Shift"), ("ctrl", "Control"), ("alt", "Option"), ("cmd", "Command"), ("fn", "Fn (Globe)"),
    ("capslock", "Caps Lock"), ("space", "Space"), ("tab", "Tab"), ("backquote", "` (backtick)"),
    *[(f"f{i}", f"F{i}") for i in range(1, 13)],
    ("mbutton", "Middle mouse button"), ("xbutton1", "Mouse button 4"), ("xbutton2", "Mouse button 5"),
]

_LINUX = [("none", "—  (not set)"), ("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt"), ("win", "Super")]

WIN_VK = {k: vk for k, _, vk in _WIN}

# keys that also do something on their own when tapped: shown as a note under the choice
NOTES = {
    "alt": "Tapping Alt alone also highlights menu bars in some apps.",
    "lalt": "Tapping Alt alone also highlights menu bars in some apps.",
    "win": "Tapping the Windows key alone also opens Start.",
    "capslock": "Caps Lock also switches capitals on and off.",
    "space": "Space also types a space if a text box has focus.",
    "tab": "Tab also moves focus in the app under the cursor.",
    "fn": "Fn may also trigger the emoji or dictation shortcut set in System Settings → Keyboard.",
}


def choices() -> list[tuple[str, str]]:
    """(id, label) for this platform, in display order."""
    if IS_MAC:
        return list(_MAC)
    if IS_WIN:
        return [(k, label) for k, label, _ in _WIN]
    return list(_LINUX)


def vk_name(vk: int) -> str:
    """A key's name as Windows' own keyboard layout spells it ('Num 5', 'Home', 'Ä')."""
    for k, label, code in _WIN:
        if code == vk:
            return label
    if IS_WIN:
        import ctypes
        user32 = ctypes.windll.user32
        scan = user32.MapVirtualKeyW(vk, 0)
        extended = vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0x90)
        buf = ctypes.create_unicode_buffer(64)
        if scan and user32.GetKeyNameTextW((scan << 16) | (int(extended) << 24), buf, 64):
            return buf.value.title() if len(buf.value) > 1 else buf.value.upper()
    return f"Key {vk}"


def label(key: str) -> str:
    """Short name for a key id (also recorded 'vk:NN' keys)."""
    if key.startswith("vk:"):
        try:
            return vk_name(int(key[3:]))
        except ValueError:
            return key
    for k, text in choices():
        if k == key:
            return text.split("  ")[0]
    return key


def vk(key: str) -> int:
    """Windows virtual-key code for a key id, 0 if none."""
    if key.startswith("vk:"):
        try:
            v = int(key[3:])
            return v if 0 < v < 256 else 0
        except ValueError:
            return 0
    return WIN_VK.get(key, 0)


def valid(key) -> bool:
    key = str(key)
    if IS_WIN and key.startswith("vk:"):
        return vk(key) not in (0, 0x01, 0x02, 0x1B)     # not the left/right button or Esc
    return any(k == key for k, _ in choices())


class Valid:
    """Settings.CHOICES entry: `value in Valid()` checks a key id for this platform."""

    def __contains__(self, key) -> bool:
        return valid(key)


# ---------------------------------------------------------------- macOS key state
def mac_down(key: str, flags: int, keycode_down, mouse_buttons: int) -> bool:
    """Is `key` down, given NSEvent.modifierFlags(), a keycode → bool function and
    NSEvent.pressedMouseButtons()."""
    if key in _MAC_FLAGS:
        return bool(flags & _MAC_FLAGS[key])
    if key in _MAC_KEYCODES:
        return bool(keycode_down(_MAC_KEYCODES[key]))
    if key in _MAC_MOUSE:
        return bool(mouse_buttons & (1 << _MAC_MOUSE[key]))
    return False


def defaults() -> dict[str, str]:
    """The default layout: Shift converts, Command (Ctrl on PC) tools, Control (Alt) actions."""
    if IS_MAC:
        return {"key_convert": "shift", "key_tools": "cmd", "key_print": "none", "key_actions": "ctrl"}
    return {"key_convert": "shift", "key_tools": "ctrl", "key_print": "none", "key_actions": "alt"}

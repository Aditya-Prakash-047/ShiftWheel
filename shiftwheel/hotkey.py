"""'Select a file, press a shortcut': a global hotkey (Windows RegisterHotKey) that opens the
wheel for whatever is selected in the active File Explorer window or on the desktop."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
HOTKEY_ID = 0x5357          # 'SW'
EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass"}
DESKTOP_CLASSES = {"Progman", "WorkerW", "SysListView32", "SHELLDLL_DefView"}

_SPECIAL = {Qt.Key_Space: 0x20, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D, Qt.Key_Tab: 0x09, Qt.Key_Insert: 0x2D,
            Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24, Qt.Key_End: 0x23, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
            Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28, Qt.Key_QuoteLeft: 0xC0,
            Qt.Key_Minus: 0xBD, Qt.Key_Equal: 0xBB, Qt.Key_Comma: 0xBC, Qt.Key_Period: 0xBE, Qt.Key_Slash: 0xBF,
            Qt.Key_Semicolon: 0xBA, Qt.Key_Apostrophe: 0xDE, Qt.Key_BracketLeft: 0xDB, Qt.Key_BracketRight: 0xDD,
            Qt.Key_Backslash: 0xDC}


def parse(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+Space' → (modifiers, virtual key), or None if it can't be a global hotkey."""
    if not text:
        return None
    seq = QKeySequence(text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key, mods = combo.key(), combo.keyboardModifiers()
    m = MOD_NOREPEAT
    if mods & Qt.ControlModifier:
        m |= MOD_CONTROL
    if mods & Qt.AltModifier:
        m |= MOD_ALT
    if mods & Qt.ShiftModifier:
        m |= MOD_SHIFT
    if mods & Qt.MetaModifier:
        m |= MOD_WIN
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        vk = int(key)
    elif Qt.Key_F1 <= key <= Qt.Key_F24:
        vk = 0x70 + int(key) - int(Qt.Key_F1)
    else:
        vk = _SPECIAL.get(key)
    if vk is None or m == MOD_NOREPEAT and not (Qt.Key_F1 <= key <= Qt.Key_F24):
        return None             # a bare letter would steal typing: needs a modifier (F-keys are fine)
    return m, vk


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def selected_paths() -> list[str]:
    """Paths selected in the foreground File Explorer window, or on the desktop."""
    if sys.platform != "win32":
        return []
    try:
        import pythoncom
        import win32com.client
        from win32com.client import VARIANT
        pythoncom.CoInitialize()
        fg = ctypes.windll.user32.GetForegroundWindow()
        cls = _class_name(fg)
        shell = win32com.client.Dispatch("Shell.Application")
        windows = shell.Windows()
        if cls in EXPLORER_CLASSES:
            for w in windows:
                try:
                    if int(w.HWND) == fg:
                        paths = [it.Path for it in w.Document.SelectedItems()]
                        if paths:              # Windows 11 tabs share one HWND: the active tab has the selection
                            return paths
                except Exception:
                    continue
            return []
        if cls in DESKTOP_CLASSES:
            empty = VARIANT(pythoncom.VT_EMPTY, None)
            desk = windows.FindWindowSW(empty, empty, 8, VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0), 1)
            return [it.Path for it in desk.Document.SelectedItems()]
    except Exception:
        return []
    return []


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG", "windows_generic_MSG"):
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.owner.pressed.emit()
                    return True, 0
            except Exception:
                pass
        return False, 0


class GlobalHotkey(QObject):
    pressed = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.active = False
        self.filter = _Filter(self)
        app.installNativeEventFilter(self.filter)

    def set(self, text: str) -> bool:
        """Register `text` (e.g. 'Ctrl+Alt+Space'); '' turns it off. False if Windows refused
        (another app already uses that shortcut)."""
        self.clear()
        parsed = parse(text) if sys.platform == "win32" else None
        if parsed is None:
            return not text
        mods, vk = parsed
        self.active = bool(ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, mods, vk))
        return self.active

    def clear(self):
        if self.active and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        self.active = False

"""Watches for "left button held + mouse moved + Shift pressed" anywhere on screen, which
is what a Shift+drag of a file looks like. Polling global input state is simple, needs no
admin rights and can't stall the system the way a broken hook can.
Windows: GetAsyncKeyState. macOS: NSEvent.pressedMouseButtons / modifierFlags (no
Accessibility or Input Monitoring permission required)."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor

VK_LBUTTON, VK_SHIFT, VK_ESCAPE = 0x01, 0x10, 0x1B
DRAG_THRESHOLD = 10   # px the mouse must travel with the button held
NO_DRAG_TIMEOUT = 50  # ticks (≈ 0.75 s) to wait for a file drag to enter before hiding
TAP_GRACE = 30        # ticks (≈ 0.45 s) a ring-switch tap waits for the drag to reach the menu


def foreground_exe() -> str:
    """Program name of the active window ('photoshop.exe'), lower-case; '' if unknown."""
    if sys.platform != "win32":
        return ""
    try:
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


class ShiftWheelWatcher(QObject):
    """Each wheel can have its own key (Settings → Keys): pressing it while dragging opens the
    wheel on that ring; pressing another bound key switches ring; the same key again cycles."""
    show_menu = Signal(QPoint, str)     # where, which ring
    switch_ring = Signal(str)           # a bound key was pressed while the menu is open
    hide_menu = Signal()

    def __init__(self, menu_visible, menu_got_drag, parent=None):
        super().__init__(parent)
        self.menu_visible = menu_visible
        self.menu_got_drag = menu_got_drag
        self.enabled = True
        self.excluded: set[str] = set()     # program names where the wheel never opens
        self.bindings: dict[str, tuple[str, int]] = {"Convert": ("shift", VK_SHIFT)}
        self._down_at: QPoint | None = None
        self._was: dict[str, bool] = {}
        self._fired = False
        self._idle_ticks = 0
        self._pending_tap = 0
        self._pending_ring = ""
        self._shown_at = QPoint()
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self._mac = None
        if sys.platform == "darwin":
            from . import platform_mac
            self._mac = platform_mac if platform_mac.OK else None
        elif sys.platform.startswith("linux"):
            from . import platform_linux
            # same interface as platform_mac: left_button_down / key_down / escape_down
            self._mac = platform_linux if platform_linux.available() else None
        self.timer = QTimer(self, interval=15, timeout=self._tick)

    def set_bindings(self, ring_keys: dict[str, str], vks: dict[str, int] | None = None):
        """{ring: key id} (see keys.py); Windows codes come from keys.vk unless `vks` is given."""
        from . import keys
        code = (lambda k: vks.get(k, 0)) if vks is not None else keys.vk
        self.bindings = {ring: (key, code(key) or (1 if self._mac is not None else 0))
                         for ring, key in ring_keys.items() if key != "none"}
        self.bindings = {r: kv for r, kv in self.bindings.items() if kv[1]}

    def set_key(self, name: str):
        """One key for the first wheel (older API)."""
        self.bindings = {"Convert": (name, {"shift": VK_SHIFT, "ctrl": 0x11, "alt": 0x12}.get(name, VK_SHIFT))}

    def start(self):
        if self._user32 is not None or self._mac is not None:
            self.timer.start()

    def _down(self, vk: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)

    def _state(self) -> tuple[bool, bool, dict[str, tuple[bool, bool]]]:
        """(left button, escape, {ring: (key down, key tapped since the last poll)}).
        'Tapped' catches a quick tap that started and ended while the UI thread was busy
        (e.g. the moment the menu opens), which sampling the key alone would miss."""
        if self._mac is not None:
            m = self._mac
            keys = {ring: (bool(m.key_down(name)), False) for ring, (name, _) in self.bindings.items()}
            return m.left_button_down(), m.escape_down(), keys
        keys = {}
        for ring, (_, vk) in self.bindings.items():
            k = self._user32.GetAsyncKeyState(vk)
            keys[ring] = (bool(k & 0x8000), bool(k & 0x0001))
        return self._down(VK_LBUTTON), self._down(VK_ESCAPE), keys

    def _tick(self):
        lbtn, esc, keys = self._state()
        pos = QCursor.pos()
        # a new press: seen going down, or a whole tap between two polls (held-key
        # auto-repeat also sets the tapped bit, but then the key is still down)
        pressed = [r for r, (down, tap) in keys.items() if (down and not self._was.get(r)) or (tap and not down)]
        held = [r for r, (down, _) in keys.items() if down]

        if self.menu_visible():
            if not lbtn or esc:
                # drop happened (or was cancelled) – give the drop event a moment to land
                QTimer.singleShot(120, self.hide_menu.emit)
            elif pressed or self._pending_tap:
                # Right after the menu opens the drag may not have reached it yet: keep the
                # key press until it does.
                if pressed:
                    self._pending_ring = pressed[0]
                if self.menu_got_drag():
                    self._pending_tap = 0
                    self.switch_ring.emit(self._pending_ring)
                elif pressed:
                    self._pending_tap = TAP_GRACE
                else:
                    self._pending_tap -= 1
            elif not self.menu_got_drag() and (pos - self._shown_at).manhattanLength() > 6:
                # the cursor is moving over us but no file drag arrived: it's a window
                # move or text selection, so get out of the way
                self._idle_ticks += 1
                if self._idle_ticks > NO_DRAG_TIMEOUT:
                    self.hide_menu.emit()
        else:
            if lbtn:
                if self._down_at is None:
                    self._down_at = pos
                    self._fired = False
                moved = (pos - self._down_at).manhattanLength() >= DRAG_THRESHOLD
                ring = (pressed or held or [None])[0]
                if self.enabled and moved and ring and not self._fired:
                    self._fired = True
                    # in excluded apps Shift+drag belongs to the app (Settings → Behaviour)
                    if not (self.excluded and foreground_exe() in self.excluded):
                        self._idle_ticks = 0
                        self._pending_tap = 0
                        self._shown_at = pos
                        self.show_menu.emit(pos, ring)
            else:
                self._down_at = None
                self._fired = False
        self._was = {r: down for r, (down, _) in keys.items()}

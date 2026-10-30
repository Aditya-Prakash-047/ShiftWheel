"""Opens the wheel for "a file is being dragged, then a key is pressed". All of these must hold:

* the key goes down *after* the mouse button (Shift then drag is range-select, not ShiftWheel);
* the app in front is a file manager (Settings → Behaviour), so Chrome, games, editors never see it;
* a real file drag is under way: Explorer's drag image exists (not a rubber-band selection
  or a window being moved).

Polling global input state is simple, needs no admin rights and can't stall the system the way
a broken hook can. It is also cheap: with the button up it reads one key state 25 times a
second, and with a game or fullscreen app in front only twice a second.
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
ACTIVE_MS, IDLE_MS, BUSY_MS = 15, 40, 500     # poll: during a drag, button up, game in front
BUSY_EVERY = 50       # idle ticks (≈ 2 s) between checks for a game or fullscreen app

# Where files are dragged from. Everything else needs Settings → Behaviour.
FILE_MANAGERS = {"explorer.exe", "totalcmd.exe", "totalcmd64.exe", "dopus.exe", "dopusrt.exe", "files.exe",
                 "onecommander.exe", "xyplorer.exe", "freecommander.exe", "q-dir.exe", "q-dir_x64.exe",
                 "everything.exe", "everything64.exe", "doublecmd.exe", "fman.exe", "tablacus.exe", "te64.exe",
                 "finder", "path finder", "forklift", "commander one"}


_FG_CACHE: tuple[int, str] = (0, "")


def foreground_exe() -> str:
    """Program name of the active window ('photoshop.exe', 'finder'), lower-case; '' if unknown.
    Asks the system only when the active window changes."""
    global _FG_CACHE
    if sys.platform == "darwin":
        try:
            import AppKit
            return str(AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()).lower()
        except Exception:
            return ""
    if sys.platform != "win32":
        return ""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd and hwnd == _FG_CACHE[0]:
        return _FG_CACHE[1]
    name = _exe_of_foreground()
    _FG_CACHE = (hwnd, name)
    return name


def _exe_of_foreground() -> str:
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


def game_or_fullscreen() -> bool:
    """A fullscreen app, game (Direct3D) or presentation has the screen (Windows' own answer,
    the one it uses to hold back notifications)."""
    if sys.platform != "win32":
        return False
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value in (2, 3, 4)     # BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE
    except Exception:
        return False


def drag_image_visible() -> bool:
    """Explorer shows this window for the whole of a file drag, and only then."""
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        h = user32.FindWindowW("SysDragImage", None)
        return bool(h and user32.IsWindowVisible(h))
    except Exception:
        return True


class ShiftWheelWatcher(QObject):
    """Each wheel can have its own key (Settings → Keys): pressing it while dragging opens the
    wheel on that ring; pressing another bound key switches ring; the same key again cycles.
    See the module docstring for when it opens."""
    show_menu = Signal(QPoint, str)     # where, which ring
    switch_ring = Signal(str)           # a bound key was pressed while the menu is open
    hide_menu = Signal()

    def __init__(self, menu_visible, menu_got_drag, parent=None):
        super().__init__(parent)
        self.menu_visible = menu_visible
        self.menu_got_drag = menu_got_drag
        self.enabled = True
        self.excluded: set[str] = set()     # "everywhere" mode: program names where it never opens
        self.only_in: set[str] | None = set(FILE_MANAGERS)    # file-managers mode; None = every app
        self._armed = ""                    # ring whose key went down during this drag
        self._busy = False                  # a game or fullscreen app has the screen
        self._idle_count = 0
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
        self.timer = QTimer(self, interval=IDLE_MS, timeout=self._poll)

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

    def app_allowed(self) -> bool:
        if self._mac is not None and sys.platform != "darwin":
            return True                     # Linux: no active-app query on X11 here
        exe = foreground_exe()
        if self.only_in is not None:
            return exe in self.only_in
        return exe not in self.excluded

    def can_open(self) -> bool:
        """Checked at the moment the wheel would open."""
        if not self.enabled or not self.app_allowed():
            return False
        return drag_image_visible() if foreground_exe() == "explorer.exe" else True

    def is_busy(self) -> bool:
        return game_or_fullscreen() and foreground_exe() not in FILE_MANAGERS

    def _left_down(self) -> bool:
        if self._mac is not None:
            return bool(self._mac.left_button_down())
        return self._down(VK_LBUTTON)

    def _reset(self):
        self._down_at = None
        self._fired = False
        self._armed = ""
        self._was = {}

    def _poll(self):
        """Almost all the time the button is up: read that one state and do nothing else."""
        visible = self.menu_visible()
        if not visible and not self._left_down():
            if self._down_at is not None:
                self._reset()
            self._idle_count += 1
            if self._idle_count >= (4 if self._busy else BUSY_EVERY):      # both ≈ every 2 s
                self._idle_count = 0
                self._busy = self.is_busy()
            want = BUSY_MS if self._busy else IDLE_MS
            if self.timer.interval() != want:
                self.timer.setInterval(want)
            return
        if not visible and (self._busy or not self.enabled or not self.app_allowed()):
            # someone else's drag (a game firing, text in Chrome): stay slow and don't read keys.
            # The file manager may only just be getting focus from this click, so a press
            # counts from the moment it does.
            self._reset()
            return
        if self.timer.interval() != ACTIVE_MS:
            self.timer.setInterval(ACTIVE_MS)
        self._tick()

    def _tick(self):
        lbtn, esc, keys = self._state()
        pos = QCursor.pos()
        # a new press: seen going down, or a whole tap between two polls (held-key
        # auto-repeat also sets the tapped bit, but then the key is still down)
        pressed = [r for r, (down, tap) in keys.items() if (down and not self._was.get(r)) or (tap and not down)]

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
                    # a new press: keys already down (Shift then drag) don't count, nor does a
                    # tap from before now that's still in the key-state bit
                    self._down_at = pos
                    self._fired = False
                    self._armed = ""
                    pressed = []
                if pressed:
                    self._armed = pressed[0]
                moved = (pos - self._down_at).manhattanLength() >= DRAG_THRESHOLD
                # the drag image can appear just after the key: stay armed until the button is up
                if moved and self._armed and not self._fired and self.can_open():
                    self._fired = True
                    self._idle_ticks = 0
                    self._pending_tap = 0
                    self._shown_at = pos
                    self.show_menu.emit(pos, self._armed)
            else:
                self._reset()
        self._was = {r: down for r, (down, _) in keys.items()}

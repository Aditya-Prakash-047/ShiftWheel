"""The update flow in the running app: background checks, the 'update available' card,
download with progress, and the hand-over to the installer (see updater.py)."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from . import __version__, updater
from .util import UserError, keep, release


class _Sig(QObject):
    done = Signal(object)          # Release | None, or an Exception
    progress = Signal(float)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.sig = fn, _Sig()

    def run(self):
        try:
            result = self.fn(lambda f: self.sig.progress.emit(f))
        except Exception as e:  # noqa: BLE001
            result = e
        try:
            self.sig.done.emit(result)
        except RuntimeError:
            pass


class UpdateController(QObject):
    """Owned by the app. `status` is a short line for Settings → Behaviour → Updates."""
    status_changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.app, self.s = app, app.settings
        self.available: updater.Release | None = None
        self.busy = False
        self.status = self._idle_status()
        self.timer = QTimer(self, interval=30 * 60 * 1000, timeout=self.auto_check)

    # ------------------------------------------------------------ start-up
    def start(self):
        last = self.s.get("last_version")
        if last and updater.is_newer(__version__, last):
            QTimer.singleShot(1500, lambda: self.app.toasts.prompt(
                f"Updated to ShiftWheel {__version__}", f"You had {last}.",
                [("What's new", lambda: self.app.open_about(1))], ms=12000))
        if last != __version__:
            self.s.set("last_version", __version__)
        self._after_update()
        QTimer.singleShot(25_000, self.auto_check)          # well after start-up
        self.timer.start()

    def _after_update(self):
        """Did the update asked for last time really install? Say so if it didn't."""
        attempt = self.s.get("update_attempt")
        if attempt:
            self.s.set("update_attempt", "")
            if updater.is_newer(attempt, __version__):
                updater.log(f"the update to {attempt} didn't install; still on {__version__}")
                QTimer.singleShot(2000, lambda: self.app.toasts.prompt(
                    f"The update to {attempt} didn't install", f"You're still on {__version__}.",
                    [("Try again", lambda: self.check(quiet=False)), ("Download page", self.open_page)], ms=60000))
                return
        if not attempt or not updater.is_newer(attempt, __version__):
            updater.cleanup_downloads()

    def auto_check(self):
        if self.available is not None:
            self._maybe_offer(self.available)       # it was held back by a game or a fullscreen app
        elif self.s.get("update_auto") and updater.due(self.s.get("update_last")):
            self.check(quiet=True)

    def _maybe_offer(self, rel: updater.Release):
        """Automatic checks ask once per version; afterwards it waits quietly in the tray menu,
        Settings and About. Never over a game or a fullscreen app."""
        if self.s.get("update_offered") == rel.version:
            return
        watcher = getattr(self.app, "watcher", None)
        if watcher is not None and watcher.is_busy():
            return
        self.s.set("update_offered", rel.version)
        self.offer(rel)

    # ------------------------------------------------------------ check
    def _idle_status(self) -> str:
        last = self.s.get("update_last")
        when = time.strftime("%d %b %Y, %H:%M", time.localtime(last)) if last else "never"
        return f"Version {__version__} · last checked {when}"

    def _set_status(self, text: str):
        self.status = text
        self.status_changed.emit(text)

    def check(self, quiet: bool = False):
        """quiet: the automatic check (no card unless there's an update; skipped versions stay
        skipped). Not quiet: 'Check now' always answers."""
        if self.busy:
            return
        self.busy = True
        self._set_status("Checking for updates…")
        skip = self.s.get("update_skip") if quiet else ""
        job = keep(_Job(lambda _p: updater.check(skip=skip)))
        job.sig.done.connect(lambda r: self._checked(job, r, quiet))
        QThreadPool.globalInstance().start(job)

    def _checked(self, job, result, quiet: bool):
        release(job)
        self.busy = False
        if isinstance(result, Exception):
            updater.log(f"check failed: {result!r}")
            self._set_status(self._idle_status())
            if not quiet:
                msg = str(result) if isinstance(result, UserError) else "Couldn't check for updates."
                self.app.toasts.error("Couldn't check for updates", msg)
            return
        self.s.set("update_last", int(time.time()))
        self.available = result
        updater.log(f"checked: {'version ' + result.version + ' available' if result else 'up to date'}")
        if result is None:
            self._set_status(self._idle_status() + " · up to date")
            if not quiet:
                self.app.toasts.info("You're up to date", f"ShiftWheel {__version__} is the latest version.")
            return
        self._set_status(f"ShiftWheel {result.version} is available (you have {__version__})")
        if quiet:
            self._maybe_offer(result)
        else:
            self.s.set("update_offered", result.version)
            self.offer(result)

    def offer(self, rel: updater.Release):
        first = next((ln.strip("-*# ").strip() for ln in rel.notes.splitlines() if ln.strip("-*# ").strip()), "")
        detail = (first[:90] + "…") if len(first) > 90 else (first or f"You have {__version__}.")
        actions = [("Update now", lambda: self.install(rel)), ("What's new", lambda: self.app.open_about(1))]
        if updater.install_kind() != "source":
            actions.append(("Skip", lambda: self.skip(rel)))
        self.app.toasts.prompt(f"ShiftWheel {rel.version} is available", detail, actions, ms=60000)

    def skip(self, rel: updater.Release):
        self.s.set("update_skip", rel.version)
        self._set_status(f"Skipped {rel.version} · {self._idle_status()}")

    def open_page(self, rel: updater.Release | None = None):
        QDesktopServices.openUrl(QUrl((rel or self.available).page if (rel or self.available)
                                      else updater.RELEASES_PAGE))

    # ------------------------------------------------------------ install
    def install(self, rel: updater.Release | None = None):
        rel = rel or self.available
        if rel is None or self.busy:
            return
        kind = updater.install_kind()
        asset = rel.asset(updater.asset_name(kind) or "")
        if asset is None:                   # running from source, or no build for this system
            self.open_page(rel)
            return
        self.busy = True
        card = self.app.toasts.new()
        card.working(f"Downloading ShiftWheel {rel.version}", "0%")
        self._set_status(f"Downloading {rel.version}…")
        folder = updater.update_folder(rel.version)
        job = keep(_Job(lambda p: updater.download(asset, folder, p)))
        job.sig.progress.connect(lambda f: card.working(f"Downloading ShiftWheel {rel.version}",
                                                        f"{int(f * 100)}%  ·  {asset.size / 1048576:.0f} MB"))
        job.sig.done.connect(lambda r: self._downloaded(job, r, card, rel, kind))
        QThreadPool.globalInstance().start(job)

    def _downloaded(self, job, result, card, rel, kind):
        release(job)
        if isinstance(result, Exception):
            self.busy = False
            updater.log(f"download failed: {result!r} (cause {result.__cause__!r})")
            msg = str(result) if isinstance(result, UserError) else "The update couldn't be downloaded."
            card.error("Update failed", msg)
            self._set_status(self._idle_status())
            return
        card.info(f"Installing ShiftWheel {rel.version}", "ShiftWheel restarts in a moment…", ms=60000)
        self._set_status(f"Installing {rel.version}…")
        self._install_when_idle(result, kind, waited=0)

    def _install_when_idle(self, path, kind, waited: int):
        """Let running jobs finish first (never cut a conversion off halfway)."""
        if QThreadPool.globalInstance().activeThreadCount() > 0 and waited < 600:
            QTimer.singleShot(1000, lambda: self._install_when_idle(path, kind, waited + 1))
            return
        try:
            self.s.set("update_attempt", self.available.version if self.available else "")
            self.s.q.sync()
            updater.launch_install(path, kind)
        except Exception as e:  # noqa: BLE001
            self.busy = False
            updater.log(f"couldn't start the installer: {e!r}")
            self.app.toasts.error("Update failed", str(e))
            return
        QTimer.singleShot(600, self.app.qapp.quit)

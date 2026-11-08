# Contributing

## Set up

Python 3.11 or newer:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt       # macOS
python -m shiftwheel
```

## Before committing

```bash
python -m ruff check shiftwheel tests
python -m pytest -q
```

Windows PowerShell: set `$env:QT_QPA_PLATFORM="offscreen"` first. macOS: `QT_QPA_PLATFORM=offscreen python -m pytest -q`.

## Guidelines

- Keep originals untouched: write results to a temporary name, then rename (`atomic_save`).
- Keep heavy libraries out of start-up: use `LazyModule` or import inside the function.
- A new module loaded by name must be added to `hiddenimports` in `ShiftWheel.spec`.
- User-facing changes get an entry in `CHANGELOG.md`.
- After a visual change, run `python docs/screenshots.py` (on Windows or macOS) to update the images in `docs/`.
- Windows-only and macOS-only code stays behind a platform check.

## CI

Workflows run for release tags or by hand (Actions → Run workflow). Run the tests locally before opening a pull request.

Releases: see [docs/RELEASING.md](docs/RELEASING.md).

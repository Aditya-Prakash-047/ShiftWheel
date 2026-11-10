# Changelog

All notable changes to ShiftWheel. The format follows [Keep a Changelog](https://keepachangelog.com), and versions follow [Semantic Versioning](https://semver.org).

## [1.5.1] - 2026-11-10

### Fixed
- An update stopped by a dropped connection now retries by itself (three tries) instead of failing.
- Every update step (check, download, install) is written to the log, so a failure says why.
- The Windows log no longer fills with thousands of false "fatal exception" lines.

## [1.5.0] - 2026-11-09

### Added
- Opacity for every theme (Settings → Appearance → Customise). Liquid glass starts frosted like macOS: colours behind it show through, text behind it can't be read.
- About → Credits names the creator.

### Fixed
- About → Credits still described the code as MIT-licensed.

## [1.4.0] - 2026-11-07

### Added
- ShiftWheel is open source under the GNU AGPL-3.0-or-later, with code, releases and issues in one public repository.
- Liquid glass works with every wheel shape (squircle, rounded square, hexagon, octagon).
- `docs/screenshots.py` regenerates the documentation images from the current code.

### Fixed
- Switching themes with Settings open left input fields and dropdowns in the previous theme's colours.
- Number boxes showed light arrow buttons in dark themes.

### Changed
- Updates come from the ShiftWheel repository. Each release includes the FFmpeg source.

## [1.3.1] - 2026-11-01

### Added
- Installer and app details: publisher, copyright, support and update links, licence page.
- Third-party notices in the app (About → Licence).
- macOS disk image includes an Applications shortcut.

### Changed
- Library versions are pinned, so builds are repeatable. Intel Macs use the last PyMuPDF and ONNX Runtime versions that support them.
- Updates are only downloaded from ShiftWheel's own release page.
- CI runs only for release tags or when started by hand.
- The default theme and sound pack are now called Santra. Saved settings and themes carry over.

### Fixed
- A funding link inherited from another project was removed.
- The macOS build's self-test read the wrong log location.
- If an update can't find the app afterwards, Windows no longer shows an error box.

## [1.3.0] - 2026-10-31

### Added
- Confirmation before a job creates many files, with a limit in Settings → Saving.
- PDF split can make one file every N pages; many pieces get their own folder.
- About: privacy, system details with Copy details, licence, prefilled problem reports.
- Settings → Behaviour: choose where the wheel opens.

### Changed
- The wheel opens only for "drag first, then tap the key", only during a real file drag, and by default only in file managers.
- Polling slows down during games and fullscreen apps; conversions run at low priority.
- Tools load on first use and memory is released when idle (about 7 MB of active memory once idle on Windows).
- Each update is offered once per version, and never over a game.

### Fixed
- **Update now did nothing on Windows**: the update script exited immediately, so no update installed. Versions 1.1.0 to 1.2.0 need one manual install to get this fix.

## [1.2.0] - 2026-10-24

### Added
- About window: creator, links, what's new and credits, inside the app.

## [1.1.1] - 2026-10-24

### Changed
- Updates and downloads come from the public ShiftWheel-releases page.

## [1.1.0] - 2026-10-24

### Added
- Built-in updater; Share through the Windows share sheet; any-key bindings with Record; compression levels with size estimates; batch "apply to all"; Save / Cancel in Settings; macOS builds in CI.

### Changed
- Lazy loading and a one-thread OpenBLAS cut idle memory substantially.

## [1.0.0] - 2026-10-23

### Added
- First release for Windows, built on [DragShift](https://github.com/llamaboi55/DragShift).
- Drag a file, tap a key and drop it on the wheel: Convert, Tools, Print and Actions.
- Seven themes in light and dark, theme files, customisation and interface sounds.
- Configurable keys, and a notification after each job with Open, Show in folder and Undo.

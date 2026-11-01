# Changelog

All notable changes to ShiftWheel. The format follows [Keep a Changelog](https://keepachangelog.com), and versions follow [Semantic Versioning](https://semver.org).

## [1.3.1] - Unreleased

### Added
- Installer and app details: publisher, copyright, support and update links, licence page.
- Third-party notices in the app (About → Licence).
- macOS disk image includes an Applications shortcut.

### Changed
- Library versions are pinned, so builds are repeatable.
- Updates are only downloaded from ShiftWheel's own release page.
- CI runs only for release tags or when started by hand.
- The default theme and sound pack are now called Santra. Saved settings and themes carry over.

### Fixed
- A funding link inherited from another project was removed.
- The macOS build's self-test read the wrong log location.

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
- A new default design, theme files, sounds, customisation, and many new tools and formats.

### Changed
- Lazy loading and a one-thread OpenBLAS cut idle memory substantially.

## [1.0.0] - 2026-10-22

- First release, built on [DragShift](https://github.com/llamaboi55/DragShift).

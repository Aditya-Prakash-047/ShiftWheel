# Releasing

## Before a public release

- [ ] **Licences**: FFmpeg (GPL) and PyMuPDF (AGPL-3.0) are bundled. Confirm the distribution meets their terms; see the licensing note below.
- [ ] Tests pass locally, and the packaged app passes `--selftest`.
- [ ] `CHANGELOG.md` and `RELEASE_NOTES.md` are updated. The first bullet of the notes is what the update card shows.
- [ ] The version matches in `shiftwheel/__init__.py`, `installer/ShiftWheel.iss`, `installer/version_info.txt` and `ShiftWheel.spec` (a test checks this).
- [ ] New modules loaded by name are in `hiddenimports`.
- [ ] On macOS builds, try the wheel, Share, a conversion and an update on a real Mac.

## Publish

Pushing a tag starts all three workflows, including two macOS builds that use minutes at ten times the normal rate. Check you have minutes first.

```bash
git tag v1.2.3
git push origin v1.2.3
```

CI tests, builds and self-tests, then attaches the files to the release here and on the public [ShiftWheel-releases](https://github.com/Aditya-Prakash-047/ShiftWheel-releases) page. Publishing there needs the `RELEASES_TOKEN` secret: a fine-grained token limited to ShiftWheel-releases, with **Contents: Read and write**. Without it, that step is skipped with a warning.

Attach `install-mac.sh` to the public release as well, because the install command downloads it from the latest release.

## Build Windows locally

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
pyinstaller ShiftWheel.spec --noconfirm
$env:ONEFILE="1"; pyinstaller ShiftWheel.spec --noconfirm; Remove-Item Env:ONEFILE
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\ShiftWheel.iss
dist\ShiftWheel\ShiftWheel.exe --selftest
```

A Mac build needs a Mac (or the macOS workflow).

## Licensing note

ShiftWheel's own code is MIT, but the bundled parts carry conditions when binaries are distributed:

- **PyMuPDF** is AGPL-3.0 unless a commercial licence from Artifex is bought. The AGPL expects the source of the combined program to be available to recipients.
- **FFmpeg** builds used here are GPL. Recipients must be able to get the corresponding FFmpeg source.
- **Qt (PySide6)** and **py7zr** are LGPL, which a PyInstaller folder build generally satisfies. The single-file build makes replacing those libraries harder.

Publishing the source, buying the PyMuPDF licence, or replacing PyMuPDF are the usual ways to meet this. Get legal advice for anything commercial.

## Code signing (not set up)

- **Windows**: without a certificate, SmartScreen warns. Options: Azure Trusted Signing, or a code-signing certificate.
- **macOS**: without an Apple Developer ID ($99 a year) and notarization, Gatekeeper blocks the first launch. `installer/entitlements.plist` is ready for notarized builds.

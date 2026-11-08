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

CI tests, builds and self-tests, then publishes the release here with the installer, the portable app, both Mac disk images, `install-mac.sh` and the FFmpeg source.

Copies on 1.3.1 or older look for updates under the old repository name: they are offered 1.4.0, and **Update now** opens its download page so they can install it once by hand.

## Build Windows locally

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
pyinstaller ShiftWheel.spec --noconfirm
$env:ONEFILE="1"; pyinstaller ShiftWheel.spec --noconfirm; Remove-Item Env:ONEFILE
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\ShiftWheel.iss
dist\ShiftWheel\ShiftWheel.exe --selftest
```

A Mac build needs a Mac (or the macOS workflow).

## Licensing

ShiftWheel is AGPL-3.0-or-later, which PyMuPDF's licence requires, and its source is public. FFmpeg is GPL: its source is attached to each release. Qt (PySide6) and py7zr are LGPL; the folder build keeps their libraries replaceable.

## Code signing (not set up)

- **Windows**: without a certificate, SmartScreen warns. Options: Azure Trusted Signing, or a code-signing certificate.
- **macOS**: without an Apple Developer ID ($99 a year) and notarization, Gatekeeper blocks the first launch. `installer/entitlements.plist` is ready for notarized builds.

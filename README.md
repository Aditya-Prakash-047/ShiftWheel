# ShiftWheel

Start dragging any file in File Explorer, tap a key, and drop it on a slice of the wheel. Convert it, edit it, print it or act on it, right where you are. Everything happens on your PC; nothing is uploaded.

![Seven wheel themes, each in light and dark](docs/themes.png)

## How to use

1. Start dragging a file (or several, or a folder) in File Explorer or on the desktop.
2. Tap a key — like Santra: **Shift** converts, **Ctrl** opens tools, **Alt** opens file actions. The wheel opens under the cursor; release the key and keep dragging.
3. Drop the file on a slice. The result is saved **next to the original**; the original is never changed.
4. Tap another key to switch wheels, or the same key again to go round them: **Convert → Tools → Print → Actions**.

No dragging needed: select a file and press **Ctrl + Alt + W** — the wheel opens at the mouse. In the wheel, **arrow keys** choose, **Enter** applies, **1–9** pick a slice, **Tab** switches wheel, **Esc** cancels. Also: right-click any file → **ShiftWheel…**, **Send to → ShiftWheel**, or double-click the tray icon.

Every action ends with a notification showing what changed, with **Open**, **Show in folder** and **Undo**, and a soft tick plays as slices light up (Santra's sound, recreated).

## Themes

Pick one in **Settings → Appearance**. Each theme styles the wheel **and** every window, notification and menu (design tokens), and has a light and a dark version.

| Theme | Look | Inspired by |
|---|---|---|
| **Santra** (default) | Frosted glossy tiles with constant gaps and rounded corners, black labels, a solid `#FF5200` slice, a small frosted capsule in the middle. Geometry, colours and label sizes measured from the reference design | Santra |
| **Ember** | Matte charcoal or porcelain disc, hairline dividers, one coral slice and a coral marker on the rim | ShiftWheel's own design |
| **Liquid glass** | Clear glass that refracts whatever is behind it | DragShift (the original look) |
| **Frost** | Milky frosted glass with a large quiet hub | Apple's “Release to Select” menu |
| **Graphite** | Near-black disc, hairlines, faint blue halo | Radial for macOS |
| **Blossom** | Soft tiles split by bold dividers, pink highlight | FileFlow concept |
| **Neon Night** | Synthwave: glowing cyan lines, magenta highlight (dark only) | OG Converter |

**Customise any theme** (Settings → Appearance → *Customise …*): light / dark / **match Windows** (switches live) · highlight colour: the theme's, your **Windows accent colour**, presets or any colour · slice, backing and label colours · **shape**: circle, squircle, rounded square, hexagon, octagon · corner roundness, gap between slices, ring thickness, lift on hover · wheel size. Then **Save as new theme**, **Export** it, or **Reset this theme**.

### Theme files

**Import theme…** takes a `.swtheme` package (a zip with `theme.json` and optional `sounds/*.wav`) or a plain `.json` file; **Export…** writes a `.swtheme` with your colours, shape and custom sounds. Everything not given is inherited from `base`; unknown keys and bad values are ignored with a note, never a crash.

```json
{
  "format": "shiftwheel-theme", "version": 1,
  "name": "Square Mint", "author": "you", "base": "ember",
  "shape": { "outline": "square", "corner": 14, "gap": 4, "innerRatio": 0.42, "iconSet": "fluent" },
  "light": { "wheel": { "hoverOuter": "#10B981", "sliceInner": "#FFFFFF", "sliceOuter": "#ECFDF5" },
             "ui":    { "accent": "#10B981", "window": "#F6FBF8" } },
  "dark":  { "wheel": { "hoverOuter": "#34D399" }, "ui": { "accent": "#34D399" } },
  "sounds": { "pack": "pop", "files": { "highlight": "sounds/highlight.wav" } }
}
```

Colours are `#RGB`, `#RRGGBB`, `#RRGGBBAA` or `rgba(r,g,b,a)`. Wheel keys: `disc, discEdge, sliceInner, sliceMiddle, sliceOuter, sliceEdge, divider, hub, hubEdge, pill, pillEdge, hubText, text, textDim, hoverInner, hoverOuter, hoverEdge, hoverText, arc, glow, shadow` plus `frost, tileGradient, innerRing, neon` (true/false). UI keys: `window, surface, hover, border, input, text, textDim, accent, onAccent, good, warn, bad, radius, controlRadius`. Shape keys: `outline, innerRatio, gap, corner, rim, lift, labelRadius, labelSize, toolLabelSize, iconSize, iconSet, hubLabel, font`.

## Sounds

Settings → Sounds: on/off, volume, a **pack** (Santra · Soft · Glass · Pop · Arcade, or *match the theme*), and each event — slice lights up, wheel opens, ring changes, file dropped, job finished, something went wrong — can be switched off, previewed, or replaced with **your own sound** (any audio file; converted and kept with ShiftWheel, and included when you export a theme). Santra's tick is synthesised to match the one on the reference design (60 ms, bright transient around 8–9 kHz) rather than copied.

## Settings

![Settings → Appearance](docs/settings.png)

| Page | What you can change |
|---|---|
| **Appearance** | Theme gallery with live previews, per-theme customisation (above), import / export / save as new theme, wheel size |
| **Keys** | A key for each wheel: Shift, Ctrl, Alt, left/right versions of each, the Windows key, Menu, Space, Tab, Caps Lock, F1–F24, the middle or side mouse buttons, or **Record…** any other key (duplicates are prevented, keys with side effects are flagged) · tap the same key to go round · the select-and-press shortcut. On a Mac also Command, Option and **Fn (Globe)**. Fn can't be used on Windows: PC keyboards handle it in hardware, so Windows never sees it |
| **Sounds** | Above |
| **Saving** | Next to the original, a “ShiftWheel” subfolder, or a folder you choose · **ask for a file name before saving** · when the name is taken: keep both or replace the older result (never the original) · after saving: notify, open, or show in folder · JPG/WebP quality · PDF → image resolution |
| **Behaviour** | Apps where the wheel never opens (Photoshop, Figma… where Shift-drag already means something) · notifications for every result or only problems · start with Windows · right-click menu entry |

Changes preview live; **Save** (Ctrl+S) keeps them, **Cancel**, Esc or closing the window puts everything back as it was, including start-with-Windows and the right-click entry. Settings are checked when they're read: anything unknown or out of range falls back to the default, older settings are migrated, and **Reset all settings** puts everything back.

### Compression levels

Compress (PDF, audio, video) and Zip / 7Z show each level with the size it will make **before** anything is written:

| | Levels | How the size is worked out |
|---|---|---|
| **PDF** | Light (lossless) · Balanced (150 dpi) · Strong (110 dpi) · Smallest (72 dpi); unused objects and font glyphs are always dropped | compressed in memory (exact), or from 12 sample pages for big files |
| **Images** | High · Medium · Low · Smallest, any quality, *under N KB/MB*, or *N % smaller*, optional resize and WebP | the preview is encoded and scaled |
| **Audio** | High 192k · Balanced 128k · Small 96k · Voice 48k mono (MP3) | bitrate × length |
| **Video** | Smallest · Balanced · High quality · a target size (WhatsApp 16 MB, Email 25 MB, Discord 10 MB) | three 2-second samples encoded with the same settings |
| **ZIP / 7Z** | Store · Fast · Normal · Maximum; already-compressed files (photos, videos, PDFs) are detected and Fast is suggested | a sample of every file is compressed |

### Several files at once

Drop several files on a slice and the tool works on all of them: conversions, Compress, Resize, Merge, Share, Copy, Move, SHA-256 and Duplicate do every file; Edit, Crop (same area and ratio on each), Add BG, Metadata, Password-protect, video Crop, Speed, Channels and Visualizer preview the first file and apply the same settings to all (**Apply to all N files**, on by default).

## What it does

| Files | Convert | Tools | Print |
|---|---|---|---|
| **Images** (JPG, PNG, WEBP, HEIC, AVIF, TIFF, BMP, GIF, ICO, **SVG** in) | Any of those, or PDF (several images → one PDF) | Compress (quality, *under N KB/MB*, or **N % smaller**), Metadata (view, remove, **edit**), Edit, Annotate, Add BG, Crop, Redact, Resize, **Text (OCR)**, **QR code**, **Collage** (several) | **ID Card**, **Passport**, **Scan**, **Print** |
| **PDF** | DOCX, **PPTX**, **XLSX** (tables), JPG, PNG, **EPUB**, TXT, **MD** | Compress, Split, Rotate, **Organize pages**, Merge, Protect, Extract images, Metadata, **OCR → searchable** | **Print**, **ID Card**, **Scan** |
| **Video** (MP4, MOV, MKV, WEBM, AVI, WMV…) | MP4, MOV, MKV, WEBM, AVI, GIF, MP3, WAV | Compress (presets or *under N MB*), Trim, **Crop**, **Split**, Snapshot, Speed, Mute, **Redact**, Rotate, **Metadata**, Merge | |
| **Audio** (MP3, WAV, M4A, OGG, FLAC, OPUS, AIFF, WMA…) | MP3, M4A, WAV, OGG, FLAC, OPUS | Trim, Compress, Normalize, Speed, **Channels**, **Bleep**, **Visualizer → MP4**, **Trim silence**, **Metadata**, Merge | |
| **Excel / CSV** (XLSX, XLS, ODS, CSV) | PDF, XLSX, CSV, JSON, HTML | Zip | |
| **PowerPoint** (PPTX, PPT, ODP) | PDF, PNG/JPG per slide | Zip | |
| **Word** (DOCX, DOC, RTF, ODT) · **Text** | PDF, DOCX, TXT, **MD**, **HTML**, **EPUB** | | |
| **Markdown / web pages** (MD, HTML) | PDF, DOCX, HTML / TXT / MD, **EPUB** — rendered, not the source code | | |
| **E-books** (EPUB) | PDF, DOCX, TXT, MD, HTML | | |
| **Subtitles** (SRT, VTT) | SRT ⇄ VTT, TXT | | |
| **Archives** (ZIP, 7Z, TAR, GZ, **RAR** in) | ZIP, 7Z, **TAR**, **GZIP** | Extract | |
| **Folders / anything else** | | Zip, 7Z | |

Every wheel ends with the **Actions** wheel (Santra's, plus extras): **Share** (the Windows share sheet: Nearby Sharing, WhatsApp, Mail, Teams…, for every dropped file), **Float** (a floating shelf you drag files out of), **Copy** (files to the clipboard), **Move**, **Copy path**, **Terminal**, **Show** in folder, **SHA-256**, **Duplicate**.

### The Print ring

![ID card photocopy](docs/id-card.png)

- **ID Card** — photocopy-shop layout. Drop a phone photo of the front and back of an ID (Aadhaar, PAN, driving licence, voter ID, bank card, college ID). ShiftWheel finds the card, straightens it, and puts front above back at the **real card size (85.6 × 54 mm)** at the top of one A4 sheet. Drag the corners if the photo is tricky. Colour, grayscale or photocopy B&W; 1–5 copies per sheet; cut lines; other card sizes. **Save PDF** or **Print**.
- **Passport** — 35 × 45 mm (or US 2×2 in, stamp size, visa sizes), 8 copies by default, A4 or 4×6 photo paper, cut lines. Save PDF, JPG for a photo lab, or print.
- **Scan** — straighten a photo of a document into a clean A4 PDF (auto colour clean-up or black & white), with an invisible text layer so you can search and copy the text.
- **Print** — fit, fill or **actual size**, 1/2/4/6/9 per sheet, any paper.

Printing always goes out at **100 % scale**, so a card prints as a card, not blown up to fill the page.

### Video trim

![Trim](docs/trim.png)

Drag the two handles over the filmstrip (or the waveform, for audio); the preview shows the exact frame. *Precise cut* re-encodes at the exact frame; *Fast* is instant and lossless (cuts at keyframes).

## Install

### Windows 10/11

From the [latest release](https://github.com/Aditya-Prakash-047/ShiftWheel-releases/releases/latest) (or **Actions → Build Windows app → ShiftWheel-windows**):

- **ShiftWheel-Setup.exe** (recommended) — installs for your user only (no admin), adds the Start menu entry, start-with-Windows, the right-click **ShiftWheel…** entry for files and folders, and **Send to**.
- **ShiftWheel.exe** — portable. Turn on **Settings → Show “ShiftWheel…” when you right-click a file** to get the right-click entry without installing (per-user, no admin).

The app isn't code-signed, so SmartScreen may warn on first launch: **More info → Run anyway**.

### Updates

ShiftWheel updates itself like other desktop apps: once a day (or **Check for updates…** in the tray menu, or **Settings → Behaviour → Updates → Check now**) it looks at the latest GitHub release. A card offers **Update now**, **What's new** or **Skip**. Update now downloads the right file for this copy (installer, portable .exe or Mac .dmg), checks its size and the SHA-256 GitHub publishes, waits for running jobs to finish, then installs in the background and restarts. Settings, themes and sounds are kept. Automatic checks can be turned off.

### macOS 11+

**ShiftWheel-mac-apple-silicon.dmg** or **ShiftWheel-mac-intel.dmg** from the release (built and self-tested by **Actions → Build macOS app**): open it and drag ShiftWheel to Applications, or run `install-mac.sh`. It lives in the menu bar. Allow **Screen Recording** in System Settings for the Liquid glass theme to show what's behind it.

Office: Excel/PowerPoint/old Word files are exported with Microsoft Office if it's installed (perfect fidelity), otherwise LibreOffice if installed. Spreadsheets and CSV also work with neither.

## Run from source

```bash
pip install -r requirements.txt
python -m shiftwheel
```

## Tests

```bash
python -m pytest -q            # 80+ tests: every engine, every window, every slice of every wheel
python run.py --selftest       # what CI runs inside the built .exe
```

- `tests/test_printing.py` measures the printed card (54 mm) on the generated PDF **and** on Qt's print output.
- `tests/test_wheel_matrix.py` builds the real wheel for a photo, PDF, video, audio, spreadsheet, Word file, archive, folder and a mixed selection, triggers **every slice**, and checks each one produced a file or opened its window.
- **CI (Windows):** unit tests → portable exe + installer → `--selftest` inside both builds (FFmpeg, OCR models, OpenCV, printing, every window) → silent install / run / uninstall.
- **End-to-end (Windows):** `demo/e2e_windows.py` moves the real mouse (on your own PC run it with `--local`: test files go to `%TEMP%` and your Desktop, wallpaper and resolution are left alone): drags files in File Explorer and on the desktop, presses Shift, switches rings, drops on slices, drives the tool windows and checks every output (e.g. it measures the ID card on the saved PDF). Results and a screen recording go to the `e2e-output` branch.

Logs: `%LOCALAPPDATA%\ShiftWheel\log.txt`.

## How the Shift + drag works

A tray app polls the mouse button and Shift key (`GetAsyncKeyState`, no hooks, no admin). When the left button is held, the mouse has moved and Shift goes down, a borderless always-on-top window (the wheel) appears under the cursor and accepts the file drop like any drop target. It always accepts as *copy*, so the original is never moved even though Shift normally means "move" in Explorer.

## Credits & licences

- Built on [DragShift](https://github.com/llamaboi55/DragShift) (MIT) — the wheel, glass rendering, image/PDF tools and test harness. ShiftWheel adds the Print ring (ID card, passport, scan, exact-size printing), video & audio, Excel/PowerPoint/CSV, archives and OCR.
- Inspired by [Santra](https://the reference design) (macOS) and Open-Santra. No code from either.
- Bundled: FFmpeg via imageio-ffmpeg (GPL build), PyMuPDF (AGPL), RapidOCR / PP-OCR models (Apache-2.0), OpenCV (Apache-2.0), Qt for Python (LGPL). If you ever distribute builds publicly, those licences apply to the distributed app (practically: keep the source public).

ShiftWheel's own code: MIT (see LICENSE).

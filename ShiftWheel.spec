# PyInstaller spec. ONEFILE=1 -> portable single exe; otherwise a folder for the installer.
import os
from PyInstaller.utils.hooks import collect_all

onefile = os.environ.get("ONEFILE") == "1"
# packages that carry data files / native libraries PyInstaller won't find on its own
datas, bins, hidden = [], [], []
for pkg in ("pillow_heif", "imageio_ffmpeg", "rapidocr", "onnxruntime", "omegaconf", "pyclipper", "shapely",
            "py7zr", "pyppmd", "pybcj", "inflate64", "multivolumefile", "brotli", "Cryptodome", "openpyxl",
            "markdown", "pptx"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    bins += b
    hidden += h

a = Analysis(
    ["run.py"],
    datas=[("shiftwheel/assets", "shiftwheel/assets"), ("RELEASE_NOTES.md", "."), ("NOTICE", "."), ("LICENSE", "."), ("LICENSES", "LICENSES"), ("THIRD-PARTY-NOTICES.md", ".")] + datas,
    binaries=bins,
    hiddenimports=["win32com.client", "pythoncom", "PySide6.QtNetwork", "PySide6.QtPrintSupport",
                   "PySide6.QtMultimedia", "cv2", "pymupdf", "AppKit",
                   # imported by name on first use (see LazyModule)
                   "shiftwheel.archive", "shiftwheel.compresswin", "shiftwheel.convert", "shiftwheel.extras",
                   "shiftwheel.imaging", "shiftwheel.media", "shiftwheel.mediawin", "shiftwheel.ocr",
                   "shiftwheel.ocrwin", "shiftwheel.office", "shiftwheel.printwin", "shiftwheel.report",
                   "shiftwheel.saveas", "shiftwheel.tools", "shiftwheel.tools2", "shiftwheel.aboutwin",
                   "shiftwheel.confirmwin", "shiftwheel.updatectl", "shiftwheel.updater", "shiftwheel.winshare",
                   "Quartz", "objc"] + hidden,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "pandas", "PySide6.QtSql", "PySide6.QtTest",
              "PySide6.QtOpenGL", "PySide6.QtSvgWidgets", "PySide6.QtDesigner", "matplotlib", "scipy",
              # pymupdf auto-imports its optional ONNX layout analyser when onnxruntime is present;
              # we don't use it (49 MB of models, and it crashes if they're left out)
              "pymupdf.layout", "Cryptodome.SelfTest", "torch", "paddle", "openvino",
              "rapidocr.inference_engine.pytorch", "rapidocr.inference_engine.paddle",
              "rapidocr.inference_engine.openvino", "rapidocr.inference_engine.mnn",
              "rapidocr.inference_engine.tensorrt"],
)

# sounds use QtMultimedia with the native Windows backend only: its FFmpeg plugin is ~40 MB
DROP = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6WebEngine", "Qt63D", "Qt6MultimediaQuick", "Qt6Charts",
        "ffmpegmediaplugin", "avcodec-", "avformat-", "avutil-", "swresample-", "swscale-",
        "Qt6VirtualKeyboard", "Qt6Designer", "Qt6ShaderTools", "Qt6Sql", "Qt6Test", "opengl32sw",
        "Qt6OpenGL", "Qt6DataVisualization", "Qt6Positioning", "Qt6Sensors", "Qt6SerialPort",
        "Qt6Bluetooth", "Qt6Nfc", "Qt6RemoteObjects", "Qt6Scxml", "Qt6SpatialAudio", "Qt6TextToSpeech",
        "Qt6WebChannel", "Qt6WebSockets", "Qt6Svg", "qtquick", "qml",
        "libgtk-3", "libgdk-3", "libqgtk3", "libatk-")
a.binaries = [b for b in a.binaries if not any(d.lower() in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/")
           and "pymupdf/layout" not in d[0].replace("\\", "/") and "Cryptodome/SelfTest" not in d[0].replace("\\", "/")]

pyz = PYZ(a.pure)
import sys
IS_MAC = sys.platform == "darwin"
common = dict(name="ShiftWheel", console=False, upx=False)
IS_LINUX = sys.platform.startswith("linux")
if IS_MAC:
    common.update(icon="shiftwheel/assets/shiftwheel.icns")
elif IS_LINUX:
    common.update(name="shiftwheel")       # icon comes from the .desktop file / hicolor theme
else:
    common.update(icon="shiftwheel/assets/shiftwheel.ico", version="installer/version_info.txt")

if IS_MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, argv_emulation=False, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="ShiftWheel", upx=False)
    app = BUNDLE(
        coll,
        name="ShiftWheel.app",
        icon="shiftwheel/assets/shiftwheel.icns",
        bundle_identifier="com.shiftwheel.app",
        info_plist={
            "CFBundleName": "ShiftWheel",
            "CFBundleDisplayName": "ShiftWheel",
            "CFBundleShortVersionString": "1.5.0",
            "CFBundleVersion": "1.5.0",
            "NSHumanReadableCopyright": "Copyright (c) 2026 Aditya Prakash",
            "LSUIElement": True,                 # menu-bar app, no Dock icon
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # show up in Finder's "Open With" for any file, and accept drops on the app icon
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Any file",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.item", "public.content", "public.data"],
            }],
        },
    )
elif IS_LINUX:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="shiftwheel", upx=False)  # no strip: breaks OpenBLAS with Debian 12 binutils
elif onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="ShiftWheel", upx=False)

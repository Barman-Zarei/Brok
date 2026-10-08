# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for brok — produces a one-file executable on Windows
# (brok.exe) and a one-file .app bundle on macOS (brok.app).
#
# Build locally with:   pyinstaller --noconfirm brok.spec
# Build artifacts:      dist/brok[.exe|.app]
#
# Data files are collected DEFENSIVELY: each is included only if it exists
# at spec-evaluation time. That keeps the spec valid across branches —
# main has only the core skins + PROMPT.j2, while feature branches (shop,
# reminder) drop additional resources into the same tree.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# Make the in-tree `brok` package importable while the spec is evaluated, so
# collect_submodules() below can enumerate it even when the package is not
# pip-installed in the build environment.
sys.path.insert(0, str(Path.cwd()))

# Ship the package metadata so importlib.metadata.version("brok") resolves in
# the frozen exe (used for the startup version log + update check).
datas = copy_metadata("brok")

# Bundled cat chars (cat.zip, classic.zip, ...). The folder was renamed
# images/ -> chars/; support both so older tags keep building and the runtime
# char_catalog (which now looks in brok/chars) finds them.
for skin_dirname in ("chars", "images"):
    skin_dir = Path("brok") / skin_dirname
    if skin_dir.is_dir():
        for p in sorted(skin_dir.iterdir()):
            if p.is_file():
                datas.append((str(p), f"brok/{skin_dirname}"))

# LLM prompt template — handle both the current spelling (PROMPT.j2) and the
# legacy mis-spelling (PROMT.j2) so older tags also build.
for name in ("PROMPT.j2", "PROMT.j2"):
    p = Path("brok") / name
    if p.is_file():
        datas.append((str(p), "brok"))

# Plane sprites for the reminder flyby. plane.png is the legacy single sprite;
# planes/plane1..plane4.png are the four selectable variants. All are tracked in
# git and shipped in the pip wheel (see [tool.setuptools.package-data]), so bundle
# them into the frozen build too — otherwise the plane picker is empty in the
# exe/.app and every reminder falls back to the single default plane.
assets_dir = Path("brok") / "assets"
if assets_dir.is_dir():
    for p in sorted(assets_dir.iterdir()):
        if p.is_file():  # plane.png/.json, icon.png, icon-w/icon-b.png, ...
            datas.append((str(p), "brok/assets"))
    planes_dir = assets_dir / "planes"
    if planes_dir.is_dir():
        for sprite in sorted(planes_dir.glob("*.png")):
            datas.append((str(sprite), "brok/assets/planes"))
    # Bundled emoji fallback font (used only where the system has no emoji font).
    fonts_dir = assets_dir / "fonts"
    if fonts_dir.is_dir():
        for font in sorted(fonts_dir.iterdir()):
            if font.is_file():
                datas.append((str(font), "brok/assets/fonts"))

# UI translation files (i18n scans brok/locale/*.json at startup).
locale_dir = Path("brok") / "locale"
if locale_dir.is_dir():
    for locale_file in sorted(locale_dir.glob("*.json")):
        datas.append((str(locale_file), "brok/locale"))


a = Analysis(
    ['brok/main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    # Collect the whole `brok` package explicitly. In the frozen exe the
    # entry runs as `__main__` (empty `__package__`), so main.py imports its
    # submodules dynamically via `importlib.import_module("brok.llm")` — a
    # string import PyInstaller's static analysis cannot follow. Without this
    # the exe dies at startup with `ModuleNotFoundError: No module named
    # 'brok.llm'`.
    hiddenimports=collect_submodules('brok'),
    hookspath=[],
    runtime_hooks=[],
    # Brok only imports QtCore/QtGui/QtWidgets/QtNetwork. Leave the rest of the (essentials) Qt modules out so the
    # frozen app stays small. Measure the size of dist/ before and after if you change this list.
    excludes=[
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
        'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtUiTools', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtXml', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtConcurrent', 'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtPrintSupport',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

# Build the platform app icon from brok/assets/icon.png so the frozen .exe / .app
# carry a real icon (the PNG stays the single source of truth). Pillow is in the
# build env (a brok dependency); never fail the build over the icon.
app_icon = None
icon_png = Path("brok") / "assets" / "icon.png"
if icon_png.is_file():
    try:
        from PIL import Image

        Path("build").mkdir(exist_ok=True)
        if sys.platform == "win32":
            app_icon = str(Path("build") / "brok.ico")
            Image.open(icon_png).save(
                app_icon,
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
        elif sys.platform == "darwin":
            app_icon = str(Path("build") / "brok.icns")
            Image.open(icon_png).convert("RGBA").resize((1024, 1024)).save(app_icon)
    except Exception as icon_error:  # noqa: BLE001
        print(f"brok.spec: could not build the app icon ({icon_error})")
        app_icon = None

if sys.platform == 'darwin':
    # macOS: onedir -> .app. A onefile .app re-extracts its whole ~50 MB archive
    # to a temp dir on EVERY launch (and Gatekeeper rescans the extracted dylibs),
    # which made startup take ~30 s. A onedir bundle keeps the files in Contents/
    # and starts near-instantly.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='brok',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='brok',
    )
    app = BUNDLE(
        coll,
        name='brok.app',
        icon=app_icon,
        bundle_identifier='app.brok',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '0.0.0',  # overwritten by CI at build time
            'NSHumanReadableCopyright': '© Brok contributors; based on myCat © 2025 @yumicabrera',
        },
    )
else:
    # Windows / Linux: onefile -> a single self-contained executable (the .exe,
    # and the binary the .deb / AppImage wrap).
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='brok',
        icon=app_icon if sys.platform == 'win32' else None,  # .ico
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,                # no console window — pure GUI
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

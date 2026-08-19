# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec für BoRT (all-in-one Bundle).

Bündelt die GUI + CLI + alle Python-Abhängigkeiten (customtkinter etc.).
Die Backends bleiben externe Subprocess-Aufrufe:
  - whisper-cli Binary (whisper.cpp-Backend)
  - ~/projects/whisper-tagger/ (whisperX-Backend)
"""

from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path

bort_datas = collect_data_files("bort", includes=["web/*"])

# CPU-Backend mit seinen lokalen Shared Libraries bündeln. Modelle bleiben
# absichtlich externe Dateien und können in der GUI gewählt werden.
WHISPER_BIN_DIR = Path("vendor/whisper.cpp/build/bin")
whisper_binaries = []
if WHISPER_BIN_DIR.exists():
    whisper_binaries = [
        (str(path), "vendor/whisper.cpp/build/bin")
        for path in WHISPER_BIN_DIR.iterdir()
        if path.name == "whisper-cli" or path.name.startswith(("libwhisper.so", "libggml"))
    ]

# App-Icon und Assets einbinden
ASSETS_DIR = Path("assets")
asset_datas = [
    (str(ASSETS_DIR / "icon.png"), "assets"),
    (str(ASSETS_DIR / "icon-256.png"), "assets"),
    (str(ASSETS_DIR / "icon-48.png"), "assets"),
] if ASSETS_DIR.exists() else []

block_cipher = None

a = Analysis(
    ["src/bort/__main__.py"],
    pathex=[],
    binaries=whisper_binaries,
    datas=bort_datas + asset_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Reduziere Bundle-Größe: ungenutzte Heavy-Pakete ausschließen
        "pytest",
        "ruff",
        "tkinter.test",
        "unittest",
        "pydoc",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# GTK-Hooks sammeln auf Desktop-Systemen sonst sämtliche installierten Icon-
# und Theme-Pakete ein (hier > 330.000 Dateien). BoRT nutzt eigene Web-Assets;
# GTK darf Themes, Icons und Übersetzungen vom Zielsystem laden.
a.datas = [
    entry
    for entry in a.datas
    if not entry[0].startswith(("share/icons/", "share/themes/", "share/locale/"))
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bort",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI-Modus: kein Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon-256.png",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="bort",
)

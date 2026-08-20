# -*- mode: python ; coding: utf-8 -*-
"""Einzeldatei-Testbuild für BoRT unter Linux x86_64."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

bort_datas = collect_data_files("bort", includes=["web/*"])

ASSETS_DIR = Path("assets")
asset_datas = [
    (str(ASSETS_DIR / "icon.png"), "assets"),
    (str(ASSETS_DIR / "icon-256.png"), "assets"),
    (str(ASSETS_DIR / "icon-48.png"), "assets"),
] if ASSETS_DIR.exists() else []

WHISPER_BIN_DIR = Path("vendor/whisper.cpp/build/bin")
whisper_binaries = []
if WHISPER_BIN_DIR.exists():
    whisper_binaries = [
        (str(path), "vendor/whisper.cpp/build/bin")
        for path in WHISPER_BIN_DIR.iterdir()
        if path.name == "whisper-cli" or path.name.startswith(("libwhisper.so", "libggml"))
    ]

a = Analysis(
    ["src/bort/__main__.py"],
    pathex=[],
    binaries=whisper_binaries,
    datas=bort_datas + asset_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)

# Systemweite GTK-Icon-, Theme- und Übersetzungspakete gehören nicht in den
# portablen Build. Sie würden auf diesem Host mehr als 680 MiB Rohdaten belegen.
a.datas = [
    entry
    for entry in a.datas
    if not entry[0].startswith(("share/icons/", "share/themes/", "share/locale/"))
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BoRT-voice-catalog-linux-x86_64",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon-256.png",
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec für transcribe-app (all-in-one Bundle).

Bündelt die GUI + CLI + alle Python-Abhängigkeiten (customtkinter etc.).
Die Backends bleiben externe Subprocess-Aufrufe:
  - whisper-cli Binary (whisper.cpp-Backend)
  - ~/projects/whisper-tagger/ (whisperX-Backend)
"""

from PyInstaller.utils.hooks import collect_all
from pathlib import Path

# customtkinter: Daten + Hiddenimports einsammeln
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

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
    binaries=ctk_binaries,
    datas=ctk_datas + asset_datas,
    hiddenimports=ctk_hiddenimports,
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

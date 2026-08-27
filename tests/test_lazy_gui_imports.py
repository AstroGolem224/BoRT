"""Lazy GUI-Imports: bort.app muss ohne GTK/pywebview importierbar sein.

Der GUI-Stack (gi, webview) wird erst beim ersten Gebrauch geladen; CLI und
Tests dürfen ihn nie anfassen. Der Test läuft im Subprocess mit Import-Blocker,
weil der pytest-Prozess selbst bereits gi/webview importieren darf.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import bort

# Der Subprocess muss dieselbe Src-Kopie testen wie pytest selbst, nicht die
# evtl. anderweitig installierte (Editable-Install) Variante.
_SRC_DIR = str(Path(bort.__file__).resolve().parent.parent)

_BLOCKER_SCRIPT = """
import sys


class _GuiBlocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gi" or fullname == "webview" or fullname.startswith(("gi.", "webview.")):
            raise ImportError(f"für Test blockiert: {fullname}")
        return None


sys.meta_path.insert(0, _GuiBlocker())

import bort.app

assert callable(bort.app.main), "bort-gui-Einstiegspunkt fehlt"
assert "gi" not in sys.modules, "gi wurde trotz lazy-Import geladen"
assert "webview" not in sys.modules, "webview wurde trotz lazy-Import geladen"
print("ok")
"""

_CLI_SCRIPT = """
import sys

import bort.cli

assert "gi" not in sys.modules, "CLI-Start lädt gi"
assert "webview" not in sys.modules, "CLI-Start lädt webview"
print("ok")
"""


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": _SRC_DIR},
    )


def test_import_bort_app_without_gi_and_webview() -> None:
    completed = _run(_BLOCKER_SCRIPT)
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_cli_import_loads_no_gui_stacks() -> None:
    completed = _run(_CLI_SCRIPT)
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout

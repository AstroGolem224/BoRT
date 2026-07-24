"""Bindet die Node-Tests der reinen Waveform-Logik in pytest ein."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js fehlt")
def test_wave_math_node_suite() -> None:
    """Führt dieselbe Suite aus, die auch separat als Proof läuft."""
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["node", "--test", "tests/wave_math.test.mjs"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout

"""Tests für den ASR-Messstand (scripts/asr_bench.py).

Geprüft wird nur die reine Logik: Markup-Entfernung, Normalisierung und
Distanzberechnung. Die Backends brauchen GPU und Fremdprojekte und werden
hier nicht angefasst.
"""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "asr_bench", Path(__file__).resolve().parents[1] / "scripts" / "asr_bench.py"
)
asr_bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(asr_bench)


def _levenshtein_full(a, b):
    """Referenzimplementierung: volle Matrix, langsam, unstrittig."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def test_strip_transcript_markup_entfernt_zeitstempel_und_sprecher():
    text = "[00:00:01] sprecher001: Hallo Welt\n[00:01:02] Delia: Guten Tag"
    assert asr_bench.strip_transcript_markup(text) == "Hallo Welt\nGuten Tag"


def test_normalize_faltet_gross_klein_und_satzzeichen():
    assert asr_bench.normalize("Hallo, Welt!  Ähm...") == ["hallo", "welt", "ähm"]


def test_edit_distance_ist_null_bei_gleichheit():
    words = "eins zwei drei vier".split()
    assert asr_bench.edit_distance(words, list(words)) == 0


@pytest.mark.parametrize("seed", range(30))
def test_edit_distance_trifft_die_volle_matrix(seed):
    """Der Blockweg muss auf zufälligen Paaren die exakte Distanz liefern."""
    rng = random.Random(seed)
    alphabet = "abcde"
    a = [rng.choice(alphabet) for _ in range(rng.randint(0, 25))]
    b = [rng.choice(alphabet) for _ in range(rng.randint(0, 25))]
    assert asr_bench.edit_distance(a, b) == _levenshtein_full(a, b)


@pytest.mark.parametrize("seed", range(30))
def test_edit_distance_exakt_bei_wiederholten_laeufen(seed):
    """Wiederholte identische Läufe: der Fall, an dem zwei Abkürzungen scheiterten."""
    rng = random.Random(1000 + seed)
    run = [f"w{i}" for i in range(11)]
    noise = lambda: [rng.choice("abcde") for _ in range(rng.randint(0, 8))]  # noqa: E731
    a = noise() + run + noise() + run + noise()
    b = noise() + run + noise() + run + noise()
    assert asr_bench.edit_distance(a, b) == _levenshtein_full(a, b)


def test_error_rates_rechnet_wer():
    rates = asr_bench.error_rates("eins zwei drei vier", "eins zwo drei vier")
    assert rates["ref_words"] == 4
    assert rates["hyp_words"] == 4
    assert rates["wer"] == 0.25
    assert "cer" not in rates


def test_error_rates_cer_nur_auf_wunsch():
    rates = asr_bench.error_rates("eins zwei drei vier", "eins zwo drei vier", cer=True)
    assert 0.0 < rates["cer"] < 0.25


def test_error_rates_lehnt_leere_referenz_ab():
    with pytest.raises(ValueError):
        asr_bench.error_rates("   ", "irgendwas")


def test_tabelle_beschriftet_abweichung_nicht_als_wer():
    row = {
        "audio": "a.m4a", "audio_seconds": 60.0, "backend": "parakeet",
        "wall_seconds": 2.0, "rtfx": 30.0, "phases": {"transcribe_seconds": 1.0},
        "peak_gpu_mib": 100, "peak_rss_mib": 200,
        "similarity_vs_current": {"similarity_wer_vs_current": 0.3},
    }
    out = asr_bench.table([row])
    assert "0.3" in out
    assert "WER" not in out

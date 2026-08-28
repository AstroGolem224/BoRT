#!/usr/bin/env python3
"""ASR-Messstand für BoRT: Laufzeit, Speicher und Textabweichung je Backend.

Zweck: eine gemeinsame Messgrundlage, um die heutige Transkriptionsstrecke
(whisperX über ``~/projects/whisper-tagger``) gegen alternative ASR-Modelle zu
stellen — ohne BoRT selbst umzubauen.

Aufruf (System-Python genügt, keine Abhängigkeiten außer ffmpeg/ffprobe):

    scripts/asr_bench.py --backend whisperx-asr AUDIO... --out lauf.json
    scripts/asr_bench.py --backend parakeet AUDIO... \\
        --worker-python /pfad/zu/venv/bin/python --out lauf.json

Backends:
    whisperx        heutige volle Strecke: ASR + Alignment + Diarisierung
    whisperx-asr    dieselbe Strecke mit --no-diarize (isoliert die ASR)
    parakeet        nvidia/parakeet-tdt-0.6b-v3 über onnx-asr (nur ASR)

Bewertung gegen Text:
    --ref-suffix .ref.txt    echte, von Hand geprüfte Referenz -> WER/CER
    --compare-suffix .txt    Ausgabe des heutigen Backends -> NUR Ähnlichkeit

    Der zweite Weg ergibt KEIN WER. Er misst die Übereinstimmung mit dem
    aktuellen Modell. Jedes andere Modell sieht darin schlechter aus, egal wie
    gut es ist. Die Ausgabe beschriftet das entsprechend und nennt es
    ``similarity_wer_vs_current`` statt ``wer``.

ponytail: Editierdistanz als volle O(n*m)-Matrix in reinem Python. Zwei
schnellere Entwürfe (difflib-Blöcke zählen; an langen Gleichläufen zerlegen)
hat ``tests/test_asr_bench.py`` als ungenau widerlegt — difflib ordnet
wiederholte Läufe über Kreuz zu. Gemessen: 7000x7000 Wörter in 4,0 s auf
Python 3.14, also reicht das. CER liegt hinter ``--cer``, weil dieselbe Matrix
auf Zeichenebene bei einem 60-Minuten-Transkript rund 2,5 Minuten braucht und
die Entscheidung an WER hängt. Ausbaupfad: ``rapidfuzz.distance.Levenshtein``,
wenn CER routinemäßig gebraucht wird.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

WHISPER_TAGGER_DIR = Path.home() / "projects" / "whisper-tagger"
WHISPER_TAGGER_RUN = WHISPER_TAGGER_DIR / "run.sh"
WHISPER_TAGGER_SCRIPT = WHISPER_TAGGER_DIR / "whisperx_transcribe.py"

BACKENDS = ("whisperx", "whisperx-asr", "parakeet")


# --------------------------------------------------------------------------
# Textnormalisierung und Distanz
# --------------------------------------------------------------------------

# Zeilen der Form "[00:01:02] sprecher001: Text" oder "sprecher001: Text".
_SPEAKER_LINE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?[A-Za-zÄÖÜäöü_][\w .-]{0,40}:\s")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def strip_transcript_markup(text: str) -> str:
    """Entfernt Sprecherpräfixe und Zeitstempel aus einem BoRT-Transkript."""
    out = []
    for line in text.splitlines():
        out.append(_SPEAKER_LINE.sub("", line))
    return "\n".join(out)


def normalize(text: str) -> list[str]:
    """Normalisiert für den Textvergleich: klein, ohne Satzzeichen, NFC."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip().split()


def edit_distance(a: list[str], b: list[str]) -> int:
    """Exakte Editierdistanz, Zwei-Zeilen-DP. Siehe ponytail-Hinweis oben."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i]
        for j, token_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (token_a != token_b),
                )
            )
        previous = current
    return previous[-1]


def error_rates(reference: str, hypothesis: str, *, cer: bool = False) -> dict:
    ref_words = normalize(strip_transcript_markup(reference))
    hyp_words = normalize(strip_transcript_markup(hypothesis))
    if not ref_words:
        raise ValueError("Referenztext ist nach Normalisierung leer.")
    rates: dict = {
        "ref_words": len(ref_words),
        "hyp_words": len(hyp_words),
        "wer": round(edit_distance(ref_words, hyp_words) / len(ref_words), 4),
    }
    if cer:
        ref_chars = list(" ".join(ref_words))
        hyp_chars = list(" ".join(hyp_words))
        rates["cer"] = round(
            edit_distance(ref_chars, hyp_chars) / max(len(ref_chars), 1), 4
        )
    return rates


# --------------------------------------------------------------------------
# Ressourcen-Abtastung
# --------------------------------------------------------------------------


def _descendants(root_pid: int) -> set[int]:
    """PIDs des Prozessbaums unter ``root_pid`` (einschließlich)."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path("/proc", entry, "stat").read_text()
        except OSError:
            continue
        # comm kann Leerzeichen und Klammern enthalten; hinter ')' weiterlesen.
        tail = stat.rpartition(")")[2].split()
        if len(tail) < 2:
            continue
        children.setdefault(int(tail[1]), []).append(int(entry))
    seen = {root_pid}
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _rss_kb(pids: set[int]) -> int:
    total = 0
    for pid in pids:
        try:
            for line in Path("/proc", str(pid), "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except (OSError, ValueError):
            continue
    return total


def _gpu_mib(pids: set[int]) -> int:
    if not shutil.which("nvidia-smi"):
        return 0
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    total = 0
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) in pids:
            try:
                total += int(parts[1])
            except ValueError:
                pass
    return total


class ResourceSampler(threading.Thread):
    """Tastet RSS und GPU-Speicher des Prozessbaums ab, bis ``stop()`` kommt."""

    def __init__(self, root_pid: int, interval: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.root_pid = root_pid
        self.interval = interval
        self.peak_rss_mib = 0
        self.peak_gpu_mib = 0
        self.samples = 0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            pids = _descendants(self.root_pid)
            self.peak_rss_mib = max(self.peak_rss_mib, _rss_kb(pids) // 1024)
            self.peak_gpu_mib = max(self.peak_gpu_mib, _gpu_mib(pids))
            self.samples += 1
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=5)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------


def audio_seconds(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def to_wav16k(src: Path, dest: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(dest)],
        check=True,
    )
    return dest


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


def _run_measured(
    cmd: list[str], **popen_kwargs
) -> tuple[subprocess.Popen, str, str, float, ResourceSampler]:
    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **popen_kwargs
    )
    sampler = ResourceSampler(proc.pid)
    sampler.start()
    stdout, stderr = proc.communicate()
    elapsed = time.perf_counter() - started
    sampler.stop()
    return proc, stdout, stderr, elapsed, sampler


def run_whisperx(audio: Path, *, diarize: bool, model: str, language: str | None,
                 profile: str) -> dict:
    """Heutige BoRT-Strecke. Ruft dasselbe Skript mit denselben Schaltern."""
    if not WHISPER_TAGGER_RUN.exists():
        raise SystemExit(f"whisper-tagger nicht gefunden: {WHISPER_TAGGER_RUN}")
    # Entspricht whisperx_backend.PERFORMANCE_PROFILES.
    profiles = {"fast": (1, 32), "balanced": (3, 24), "quality": (5, 16)}
    beam, batch = profiles[profile]
    cmd = [
        "bash", str(WHISPER_TAGGER_RUN), "python", str(WHISPER_TAGGER_SCRIPT),
        str(audio), "--model", model, "--out", "-",
        "--beam-size", str(beam), "--batch-size", str(batch),
    ]
    if language:
        cmd += ["--language", language]
    if not diarize:
        cmd.append("--no-diarize")

    proc, stdout, stderr, elapsed, sampler = _run_measured(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"whisperX fehlgeschlagen ({proc.returncode}):\n{stderr[-4000:]}")
    data = json.loads(stdout)
    segments = data.get("segments", [])
    return {
        "text": " ".join(s.get("text", "").strip() for s in segments),
        "segment_count": len(segments),
        "speaker_count": len(data.get("speakers", data.get("speaker_map", {})) or {}),
        "language": data.get("language"),
        "phases": data.get("runtime_metrics", {}),
        "embedding_model": data.get("embedding_model"),
        "wall_seconds": round(elapsed, 3),
        "peak_rss_mib": sampler.peak_rss_mib,
        "peak_gpu_mib": sampler.peak_gpu_mib,
        "cmd": cmd,
    }


def run_parakeet(audio: Path, *, worker_python: str, language: str | None,
                 model_id: str) -> dict:
    """Startet diese Datei als Worker unter einem anderen Interpreter."""
    with tempfile.TemporaryDirectory(prefix="asr_bench_") as tmp:
        wav = to_wav16k(audio, Path(tmp, "in.wav"))
        result_path = Path(tmp, "result.json")
        cmd = [
            worker_python, str(Path(__file__).resolve()), "--worker-parakeet",
            str(wav), str(result_path), model_id, language or "",
        ]
        proc, stdout, stderr, elapsed, sampler = _run_measured(cmd)
        if proc.returncode != 0 or not result_path.exists():
            raise RuntimeError(
                f"parakeet-Worker fehlgeschlagen ({proc.returncode}):\n{stderr[-4000:]}"
            )
        data = json.loads(result_path.read_text())
    return {
        "text": data["text"],
        "segment_count": data["segment_count"],
        "speaker_count": 0,
        "language": language,
        "phases": data["phases"],
        "embedding_model": None,
        "wall_seconds": round(elapsed, 3),
        "peak_rss_mib": sampler.peak_rss_mib,
        "peak_gpu_mib": sampler.peak_gpu_mib,
        "cmd": cmd,
    }


def worker_parakeet(wav: str, out: str, model_id: str, language: str) -> int:
    """Läuft im Fremd-venv: onnx-asr + Silero-VAD. Schreibt das Ergebnis als JSON.

    VAD statt fester Fenster, weil Parakeet keine eigene Langaudio-Segmentierung
    mitbringt und harte Schnitte mitten im Wort die Fehlerrate künstlich heben.
    """
    import onnx_asr  # noqa: PLC0415  (nur im Worker verfügbar)

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    t0 = time.perf_counter()
    model = onnx_asr.load_model(model_id, providers=providers)
    vad = onnx_asr.load_vad("silero", providers=["CPUExecutionProvider"])
    pipeline = model.with_vad(vad, batch_size=8)
    load_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    kwargs = {"language": language} if language else {}
    segments = [
        {"start": round(float(s.start), 3), "end": round(float(s.end), 3),
         "text": s.text.strip()}
        for s in pipeline.recognize(wav, **kwargs)
    ]
    transcribe_seconds = time.perf_counter() - t1

    Path(out).write_text(json.dumps({
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
        "segment_count": len(segments),
        "phases": {
            "load_seconds": round(load_seconds, 3),
            "transcribe_seconds": round(transcribe_seconds, 3),
        },
    }, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------
# Lauf
# --------------------------------------------------------------------------


def hardware() -> dict:
    info = {"host": os.uname().nodename, "python": sys.version.split()[0]}
    if shutil.which("nvidia-smi"):
        try:
            info["gpu"] = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def measure(audio: Path, args) -> dict:
    duration = audio_seconds(audio)
    if args.backend == "parakeet":
        result = run_parakeet(audio, worker_python=args.worker_python,
                              language=args.language, model_id=args.model)
    else:
        result = run_whisperx(audio, diarize=args.backend == "whisperx",
                              model=args.model, language=args.language,
                              profile=args.profile)

    record = {
        "audio": audio.name,
        "audio_seconds": round(duration, 1),
        "backend": args.backend,
        "model": args.model,
        "rtfx": round(duration / result["wall_seconds"], 2) if result["wall_seconds"] else None,
        **{k: v for k, v in result.items() if k != "text"},
        "text_chars": len(result["text"]),
    }

    ref = audio.with_name(audio.stem + args.ref_suffix)
    if args.ref_suffix and ref.exists():
        record["reference"] = {
            "file": ref.name,
            "kind": "hand-geprüfte Referenz — echtes WER",
            **error_rates(ref.read_text(), result["text"], cer=args.cer),
        }
    cmp_path = audio.with_name(audio.stem + args.compare_suffix)
    if args.compare_suffix and cmp_path.exists() and cmp_path != ref:
        rates = error_rates(cmp_path.read_text(), result["text"], cer=args.cer)
        record["similarity_vs_current"] = {
            "file": cmp_path.name,
            "kind": "KEIN WER — Ausgabe des heutigen Backends, nur Abweichungsmaß",
            "similarity_wer_vs_current": rates.pop("wer"),
            **({"similarity_cer_vs_current": rates.pop("cer")} if "cer" in rates else {}),
            **rates,
        }
    if args.keep_text:
        (args.keep_text / f"{audio.stem}.{args.backend}.txt").write_text(result["text"])
    return record


def table(records: list[dict]) -> str:
    head = ("| Audio | min | Backend | Wall s | RTFx | ASR s | Align s | Diar s | "
            "VRAM MiB | RAM MiB | Abw. z. heute |")
    rows = [head, "|" + "---|" * 11]
    for r in records:
        p = r.get("phases") or {}
        sim = r.get("similarity_vs_current") or {}
        rows.append(
            f"| {r['audio'][:34]} | {r['audio_seconds'] / 60:.1f} | {r['backend']} | "
            f"{r['wall_seconds']:.1f} | {r['rtfx']} | "
            f"{p.get('transcribe_seconds', '-')} | {p.get('align_seconds', '-')} | "
            f"{p.get('diarize_seconds', '-')} | {r['peak_gpu_mib']} | "
            f"{r['peak_rss_mib']} | "
            f"{sim.get('similarity_wer_vs_current', '-')} |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker-parakeet":
        wav, out, model_id, language = argv[1:5]
        return worker_parakeet(wav, out, model_id, language)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", nargs="+", type=Path)
    ap.add_argument("--backend", choices=BACKENDS, default="whisperx-asr")
    ap.add_argument("--model", default=None,
                    help="Whisper-Modellname bzw. onnx-asr-Modell-ID")
    ap.add_argument("--language", default="de")
    ap.add_argument("--profile", choices=("fast", "balanced", "quality"),
                    default="balanced", help="nur whisperX: beam/batch wie in BoRT")
    ap.add_argument("--worker-python", default=sys.executable,
                    help="Interpreter mit onnx-asr (Backend parakeet)")
    ap.add_argument("--ref-suffix", default=".ref.txt",
                    help="Suffix der echten Referenz -> WER/CER")
    ap.add_argument("--compare-suffix", default="",
                    help="Suffix der Ausgabe des heutigen Backends -> nur Ähnlichkeit")
    ap.add_argument("--cer", action="store_true",
                    help="CER mitrechnen (langsam, siehe ponytail-Hinweis im Kopf)")
    ap.add_argument("--keep-text", type=Path, default=None,
                    help="Verzeichnis für die erzeugten Transkripte")
    ap.add_argument("--out", type=Path, default=None, help="JSON-Ergebnisdatei")
    ap.add_argument("--label", default="", help="Freitext für den Laufkopf")
    args = ap.parse_args(argv)

    if args.model is None:
        args.model = ("nemo-parakeet-tdt-0.6b-v3" if args.backend == "parakeet"
                      else "large-v3-turbo")
    if args.language in ("", "auto"):
        args.language = None
    if args.keep_text:
        args.keep_text.mkdir(parents=True, exist_ok=True)

    run = {
        "label": args.label,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "backend": args.backend,
        "model": args.model,
        "language": args.language,
        "profile": args.profile,
        "hardware": hardware(),
        "runs": [],
    }
    for path in args.audio:
        # run.sh wechselt ins whisper-tagger-Verzeichnis; relative Pfade brechen dort.
        path = path.resolve()
        if not path.exists():
            print(f"übersprungen (fehlt): {path}", file=sys.stderr)
            continue
        print(f"-> {path.name} [{args.backend}]", file=sys.stderr, flush=True)
        try:
            run["runs"].append(measure(path, args))
        except Exception as exc:  # noqa: BLE001 — ein Ausfall darf den Lauf nicht kippen
            print(f"   FEHLER: {exc}", file=sys.stderr)
            run["runs"].append({"audio": path.name, "backend": args.backend,
                                "error": str(exc)})

    ok = [r for r in run["runs"] if "error" not in r]
    if ok:
        print()
        print(table(ok))
    if args.out:
        args.out.write_text(json.dumps(run, ensure_ascii=False, indent=2))
        print(f"\nJSON: {args.out}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

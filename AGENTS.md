# AGENTS.md – BoRT (BoR Transcriber)

## Projektüberblick

Dies ist eine lokale Transkriptions-App mit **zwei Backends**: whisper.cpp (CPU, schlank) und whisperX (GPU, mit automatischer Sprecher-Diarisierung). Sie nimmt Audio-Dateien und optionale JSON-Marker-Dateien entgegen und erzeugt Transkripte mit Zeitstempeln und Sprecherzuordnung.

## Wichtige Entscheidungen

- **whisper.cpp-Integration**: Nicht über Python-Bindings, sondern per Subprocess-Aufruf des `whisper-cli` Binaries. Grund: Python-Bindings (`whisper-cpp-python`) bauen unter Python 3.14 nicht wegen CMake-Kompatibilitätsproblemen.
- **whisperX-Integration**: Ebenfalls per Subprocess, aber gegen das externe `whisper-tagger`-Projekt unter `~/projects/whisper-tagger`. Das kapselt PyTorch/CUDA-Abhängigkeiten (Blackwell-RTX 5090, Python 3.12, cu128-Wheels) von der schlanken BoRT (System-Python 3.14). Siehe `whisperx_backend.py`.
- **Audioverarbeitung**: ffmpeg per Subprocess, Audio (mp3, m4a, aac, wav, flac, ogg, opus, wma) → 16 kHz mono WAV (whisper.cpp-Pfad). whisperX akzeptiert dieselben Formate direkt (via ffmpeg/librosa).
- **Sprecher**: whisperX erzeugt automatisch `sprecherNNN`-Labels via Diarization. Manuelles Editieren der Marker-JSON-Datei möglich. Fallback sind generische Labels.
- **Ausgabe**: Parallel Text, Markdown, CSV, TSV.

## Projektstruktur

- `src/bort/`: Anwendungscode
  - `cli.py`: Kommandozeilen-Interface (mit `--backend`-Option)
  - `gui.py`: CustomTkinter-GUI (mit Backend-Auswahl)
  - `whisperx_backend.py`: Subprocess-Wrapper für whisperX + Marker-Erzeugung
  - `transcription.py`: whisper.cpp-Subprocess-Wrapper
  - `speakers.py`: `Segment`, `SpeakerMarker`, `SpeakerResolver`-Implementierungen
  - `markers.py`: Marker-Datei laden/speichern
  - `audio.py`: ffmpeg-basierte Audio-Konvertierung
  - `writers.py`: Ausgabeformate (txt, md, csv, tsv)
  - `config.py`: GUI-Persistenz (`~/.config/bort/settings.json`)
- `tests/`: Unit-Tests
- `vendor/whisper.cpp/`: Optionaler Checkout des whisper.cpp Repos (nicht im Git-Index)
- `models/`: ggml-Modell-Dateien (nicht im Git-Index)
- Extern: `~/projects/whisper-tagger/` – whisperX-Pipeline (uv-Projekt, Python 3.12)

## Build / Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

whisper.cpp muss separat gebaut werden:

```bash
git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git vendor/whisper.cpp
cd vendor/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

## Starten

- CLI (whisper.cpp): `./run-cli.sh audio.m4a --model models/ggml-base.bin`
- CLI (whisperX): `./run-cli.sh audio.m4a --backend whisperx --language de --max-speakers 2`
- GUI: `./run-gui.sh` (Backend in der GUI umschaltbar)

Alternativ nach `source .venv/bin/activate`: `bort` bzw. `bort-gui`.

## GUI-Persistenz

Die GUI speichert zuletzt verwendete Pfade in `~/.config/bort/settings.json`. `src/bort/config.py` kapselt Laden/Speichern.

## GUI-Framework

Die GUI basiert auf **CustomTkinter** (`src/bort/gui.py`).
- Light/Dark/System-Umschalter oben rechts (wird in Config gespeichert)
- Dark-Theme als Default (`ctk.set_default_color_theme("dark-blue")`)
- Moderne Widgets mit abgerundeten Ecken
- Datei-Dialoge bleiben native Tkinter-Dialoge

## GUI-Dateimanager-Integration

Im GUI-Fenster gibt es einen "Ordner öffnen"-Button, der das Ausgabeverzeichnis per `xdg-open` (Linux), `open` (macOS) oder `explorer` (Windows) im Dateimanager öffnet.

## Wichtige CLI/GUI-Optionen

- `--backend whispercpp` (Default): CPU-basiert, benötigt `--model` (ggml-Pfad).
- `--backend whisperx`: GPU-basiert, nutzt whisperX + pyannote-Diarization. `--model` ist optional (Default: `large-v3`). Optionen: `--min-speakers`, `--max-speakers`, `--no-diarize`, `--auto-markers`.
- `--task transcribe` (Default): Transkription in der Originalsprache.
- `--task translate`: Übersetzung nach Englisch (whisper.cpp `--translate`).
- `--language auto` (Default in GUI): Automatische Spracherkennung.

## whisperX-Backend (Details)

- Das Backend ruft `~/projects/whisper-tagger/run.sh python whisperx_transcribe.py ...` als Subprocess auf.
- Der `run.sh`-Wrapper setzt `LD_LIBRARY_PATH` für die NVIDIA-libs (Blackwell/cu128) und lädt `.env` (HF_TOKEN).
- Ausgabe ist ein JSON-Dokument mit `segments` (start, end, text, speaker) auf stdout; Logs gehen nach stderr.
- Die `speaker_map` wird aus der Reihenfolge des ersten Auftretens der Sprecher-IDs gebildet: `SPEAKER_00 → sprecher001`, `SPEAKER_01 → sprecher002`, ...
- Mit `--auto-markers` wird eine `<audio>.markers.json` gespeichert, die in der GUI nachträglich editiert werden kann (Speaker-Rename).
- Benachbarte Segmente desselben Sprechers werden zu einem Marker-Intervall zusammengeführt.

## Tests

```bash
pytest -v
```

## Coding-Style

- Python 3.10+ Type Hints (PEP 604 Unions mit `|`)
- `pathlib` für Dateipfade
- Subprocess-Aufrufe explizit mit `subprocess.run`
- Fehler als eigene Exception-Klassen (`AudioError`, `MarkerError`, `TranscriptionError`)
- Logging über `logging`, nicht `print`

## JSON-Marker-Format

```json
{
  "speakers": {"SP1": "Anzeigename"},
  "markers": [
    {"start": 0.0, "end": 10.0, "speaker": "SP1"}
  ]
}
```

- `speakers` ist optional.
- `markers` sind nach `start` sortierte, nicht notwendigerweise lückenlose Intervalle.
- Überlappende Marker werden akzeptiert und geloggt; es gewinnt der Marker mit der größten Überlappung zum Segment.

## Ausgabeverhalten

- `writers.py` legt automatisch einen Unterordner `<output_dir>/<YYYY-MM-DD>/` an.
- Bestehende Dateien werden nicht überschrieben; stattdessen wird eine fortlaufende Nummer an den Basisnamen angehängt.

## Extension-Points

- Neue `SpeakerResolver`-Implementierungen können in `speakers.py` hinzugefügt werden.
- Neue Ausgabeformate können in `writers.py` über das `FORMATS`-Dictionary registriert werden.
- Weitere Backends können in `cli.py`/`gui.py` über die `--backend`-Option ergänzt werden.

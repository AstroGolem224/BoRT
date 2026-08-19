# BoR Transcriber (BoRT)

BoRT ist die **Partner-App zur BookofRecords Android-App**: ein Desktop-Tool zur Transkription von Audio-Dateien auf Basis von [whisper.cpp](https://github.com/ggerganov/whisper.cpp) und [whisperX](https://github.com/m-bain/whisperX). Unterstützte Formate: MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA.

Features:
- Audio (MP3, M4A, AAC, ...) → Text mit Zeitstempeln
- Sprecherzuordnung über optionale JSON-Marker-Datei
- Ausgabe in **Text**, **Markdown** und **Tabelle** (CSV/TSV)
- whisper.cpp als Backend (lokal, ohne Cloud)
- whisperX (GPU + Diarization) als Backend
- `large-v3-turbo` als schneller GPU-Default für neue Installationen
- Lokaler Namenskatalog und optionale, bestätigungspflichtige Stimmprofile

## Lokaler Sprecherkatalog

In der Sprecher-Ansicht können bestätigte Namen mit **Namen lokal merken** in
`~/.local/share/bort/voice_profiles.json` gespeichert und später über die
Namensauswahl wiederverwendet werden.

Die Option **Stimmprofile lokal erfassen** ist standardmäßig ausgeschaltet. Wenn
sie vor einer whisperX-Transkription eingeschaltet wird, speichert die private
Review-Datei die von pyannote erzeugten Sprecher-Embeddings. Erst nach manueller
Benennung übernimmt BoRT sie in den lokalen Katalog. Spätere Treffer erscheinen
nur als Vorschlag mit Ähnlichkeitswert und werden nie automatisch angewendet.
Es werden keine Audioausschnitte in den Katalog kopiert.

## Schnellstart

Alles ist bereits installiert und einsatzbereit unter `/home/itiger013/Dokumente/Github/BoRT`.

### GUI starten (empfohlen)

```bash
cd /home/itiger013/Dokumente/Github/BoRT
./run-gui.sh
```

Im Fenster kannst du Audio-Datei (MP3, M4A, AAC, ...), optional JSON-Marker, Modell, Backend und Formate auswählen.

### CLI verwenden

```bash
cd /home/itiger013/Dokumente/Github/BoRT
./run-cli.sh audio.mp3 --model models/ggml-base.bin --language de
```

## Setup von Grund auf

Falls du das Projekt woanders neu aufsetzen willst:

```bash
cd BoRT
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git vendor/whisper.cpp
cd vendor/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
cd ../..

mkdir -p models
curl -L -o models/ggml-base.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
```

Weitere Modelle: [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)

## Transkribieren (CLI)

```bash
./run-cli.sh audio.mp3 --model models/ggml-base.bin --language de
```

Ausgabe: `audio.txt`, `audio.md`, `audio.csv`, `audio.tsv` im aktuellen Verzeichnis.

### Transkribieren (GUI)

```bash
./run-gui.sh
```

Das GUI nutzt **CustomTkinter** mit einem modernen Look, der gut zu CachyOS/KDE passt.

Im Fenster findest du:
- **Theme**: Umschalter zwischen Light, Dark und System (wird gespeichert).
- **Aufgabe**: Wähle *Originalsprache beibehalten* – das ist der Default.
- **Speicherort für Ergebnisse**: Ein eigenes Feld mit "Ordner wählen …"- und "Ordner öffnen"-Button.

Öffnet ein Fenster, in dem du Audio-Datei (MP3, M4A, AAC, ...), optional JSON-Marker, Modell, Sprache, Backend und Ausgabeformate bequem auswählen kannst. Die Transkription läuft in einem Hintergrundthread, damit die Oberfläche nicht einfriert.

## Einstellungen merken

Die GUI speichert in `~/.config/bort/settings.json`:

- Letzte Audio-Datei und deren Ordner
- Letzte Marker-JSON-Datei und deren Ordner
- Letztes Modell und Modell-Ordner
- Letztes Ausgabeverzeichnis
- Zuletzt gewählte Sprache und Aufgabe

Beim nächsten Start werden diese Werte wieder eingetragen; Datei-Dialoge öffnen sich im jeweils letzten verwendeten Ordner.

## JSON-Marker-Datei

Erstelle eine Datei, um Sprecher zu benennen und Zeitbereichen zuzuordnen:

```json
{
  "speakers": {
    "SP1": "Alice",
    "SP2": "Bob"
  },
  "markers": [
    {"start": 0.0, "end": 45.5, "speaker": "SP1"},
    {"start": 45.5, "end": 120.0, "speaker": "SP2"}
  ]
}
```

Nutzung:

```bash
bort audio.mp3 --markers markers.json --model models/ggml-base.bin
```

Falls keine Marker-Datei angegeben wird, werden Platzhalter wie `SP1`, `SP2`, … verwendet (bei nur einem Segment `Unbekannt`).

## CLI-Optionen

```
bort audio.mp3 \
  --markers markers.json \
  --model models/ggml-base.bin \
  --language de \
  --output-dir ./out \
  --formats txt,md,csv \
  --keep-wav \
  --verbose
```

| Option | Beschreibung |
|--------|--------------|
| `audio` | Pfad zur Audiodatei (mp3, m4a, aac, wav, flac, ogg, opus, wma) |
| `--markers` | Pfad zur JSON-Marker-Datei |
| `--model` | Pfad zum ggml-Modell (erforderlich) |
| `--language` | Sprache, z.B. `de`, `en` |
| `--task` | `transcribe` (Default, Originalsprache) oder `translate` (nach Englisch) |
| `--output-dir` | Ausgabeverzeichnis (Default: `.`) |
| `--formats` | Kommaseparierte Formate: `txt,md,csv,tsv` |
| `--whisper-cli` | Pfad zu einem alternativen whisper-cli Binary |
| `--keep-wav` | Temporäre WAV-Datei behalten |
| `--verbose` | Detaillierte Logs |

## Ausgabeformate

### Ausgabeordner

Alle Ergebnisse landen automatisch in einem Unterordner mit dem aktuellen Datum:

```
<gewähltes Ausgabeverzeichnis>/
└── 2026-07-07/
    ├── audio.txt
    ├── audio.md
    ├── audio.csv
    └── audio.tsv
```

Falls Dateien bereits existieren, wird dem Namen eine fortlaufende Zahl angehängt (`audio_1.txt`, `audio_2.txt`, …) – nichts wird überschrieben.

### Text (.txt)
```
[00:00:00] Alice: Hallo zusammen.
[00:00:03] Bob: Schön, dass ihr da seid.
```

### Markdown (.md)
```markdown
# Transkript

## Alice

**00:00:00 – 00:00:03** Hallo zusammen.

## Bob

**00:00:03 – 00:00:06** Schön, dass ihr da seid.
```

### Tabelle (.csv / .tsv)
```csv
start,end,speaker,text
0.000,3.000,Alice,Hallo zusammen.
3.000,6.000,Bob,Schön dass ihr da seid.
```

## Entwicklung

Tests ausführen:

```bash
pytest -v
```

Linting:

```bash
ruff check .
```

## Architektur

```
src/bort/
├── audio.py            # Audio (mp3/m4a/aac/...) → WAV (ffmpeg)
├── markers.py          # JSON-Marker laden
├── speakers.py         # Sprecherzuordnung
├── transcription.py    # whisper.cpp CLI-Wrapper
├── whisperx_backend.py # whisperX-Backend (GPU + Diarization)
├── streaming.py        # Robuster Subprocess-Streamer mit Live-Fortschritt
├── writers.py          # txt/md/csv/tsv Ausgabe
├── gui.py              # CustomTkinter-GUI
└── cli.py              # Kommandozeilen-Interface
```

## Lizenz

MIT

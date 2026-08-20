# BoR Transcriber (BoRT)

BoRT ist die **Partner-App zur BookofRecords Android-App**: ein Desktop-Tool zur Transkription von Audio-Dateien auf Basis von [whisper.cpp](https://github.com/ggerganov/whisper.cpp) und [whisperX](https://github.com/m-bain/whisperX). Unterstützte Formate: MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA.

Features:
- Audio (MP3, M4A, AAC, ...) → Text mit Zeitstempeln
- **whisper.cpp** als lokaler CPU-Pfad und **whisperX** als GPU-Pfad mit
  Sprecher-Diarisierung
- `large-v3-turbo` als schneller GPU-Default sowie drei reproduzierbare
  Leistungsprofile
- Einzeltranskription, Batch, Bibliothek, Sprecher-Review und globale Optionen
  in einer pywebview-Oberfläche
- Direkte Sprecherbearbeitung im Transkript, lokale Namensauswahl und optionale,
  bestätigungspflichtige Stimmprofile
- Ausgabe in **Text**, **Markdown** und **Tabelle** (CSV/TSV) mit atomarem
  Schreiben

Ausführliche Dokumentation:

- [Performance, globale Optionen und Sprecher-Workflow](docs/features/performance-speaker-workflow.md)
- [Testbuild und manuelle Testmatrix](docs/testing/voice-catalog-test-build.md)
- [Umsetzungs- und Ausbauplan](docs/plans/03-performance-voice-catalog.md)
- [Changelog](CHANGELOG.md)

## Lokaler Sprecherkatalog

In der Sprecheransicht können bestätigte Namen mit **Namen lokal merken** in
`~/.local/share/bort/voice_profiles.json` gespeichert und später über die
Namensauswahl wiederverwendet werden. Ein Sprechername lässt sich direkt im
Transkript anklicken, eintippen oder aus dem gespeicherten Katalog wählen. Alle
Vorkommen, der Sprecher-Picker und die Waveform werden gemeinsam aktualisiert.
Erst **Änderungen anwenden** schreibt die Review und Ausgabeformate neu; ein
schwebender Anwenden-Knopf bleibt auch am Ende langer Transkripte sichtbar.

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

Die aktiven Transkriptionswerte werden zentral im Reiter **Optionen** gepflegt und
gelten für Einzel- und Batchverarbeitung. Unter **Transkribieren** werden nur noch
Audio- und optionale Markerdatei gewählt.

### Einzelne ausführbare Testdatei bauen

```bash
./scripts/build-test-executable.sh
./dist/test-build/BoRT-voice-catalog-linux-x86_64
```

Der etwa 56 MB große Linux-x86_64-Build enthält GUI, Web-Ressourcen und
`whisper-cli` samt Shared Libraries. Die GGML-Modelle und das CUDA-basierte
whisper-tagger bleiben wegen ihrer Größe extern. Eine genaue Testabfolge steht in
[docs/testing/voice-catalog-test-build.md](docs/testing/voice-catalog-test-build.md).

### CLI verwenden

```bash
cd /home/itiger013/Dokumente/Github/BoRT
./run-cli.sh audio.mp3 --model models/ggml-base.bin --language de

# GPU, Diarisierung und ausgewogenes Decode-Profil
./run-cli.sh audio.m4a --backend whisperx --model large-v3-turbo \
  --language de --performance-profile balanced --max-speakers 4 --auto-markers
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

Die CLI legt Ergebnisse standardmäßig in einem Datums-Unterordner an und
überschreibt keine bestehenden Dateien.

### Transkribieren (GUI)

```bash
./run-gui.sh
```

Die aktive GUI nutzt **pywebview** mit einem lokalen HTML-/CSS-/JavaScript-
Frontend. Transkriptionsjobs laufen außerhalb des UI-Threads.

Die Hauptreiter sind:

- **Transkribieren**: Audio- und optionale Markerdatei für einen Einzellauf.
- **Batch**: mehrere neue Dateien aus einem Sync-Ordner verarbeiten.
- **Bibliothek**: Aufnahmen, Transkripte, Wiedergabe und Export verwalten.
- **Sprecher**: fertige Reviews abhören und Namen bearbeiten.
- **Optionen**: zentrale Werte für Einzel- und Batchverarbeitung.

Das Mimic-inspirierte Design kombiniert Glassmorphism und Neumorphism mit der
bestehenden Cyan-/Violett-Farbwelt. Light- und Dark-Theme werden unterstützt.

## Einstellungen merken

Die GUI speichert in `~/.config/bort/settings.json` unter anderem:

- letzte Audio-, Marker-, Modell-, Review-, Batch-, Bibliotheks- und
  Ausgabepfade,
- Backend, Sprache, Aufgabe und whisperX-Modell,
- Leistungsprofil sowie minimale/maximale Sprecherzahl,
- Ausgabeformate und Ablagemodus,
- Diarisierung, automatische Marker und das Opt-in für Stimmprofile,
- WAV-Aufbewahrung, Protokollierung, Theme und Fenstergröße.

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
  --backend whispercpp \
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
| `--backend` | `whispercpp` (Default) oder `whisperx` |
| `--model` | GGML-Pfad für whisper.cpp; Modellname für whisperX (Default `large-v3-turbo`) |
| `--language` | Sprache wie `de`/`en`; ohne Wert automatische Erkennung |
| `--task` | `transcribe` (Default, Originalsprache) oder `translate` (nach Englisch) |
| `--output-dir` | Ausgabeverzeichnis (Default: `.`) |
| `--formats` | Kommaseparierte Formate: `txt,md,csv,tsv` |
| `--whisper-cli` | Pfad zu einem alternativen whisper-cli Binary |
| `--min-speakers` | Mindestanzahl Sprecher für whisperX |
| `--max-speakers` | Maximalanzahl Sprecher für whisperX |
| `--no-diarize` | whisperX ohne Sprechertrennung ausführen |
| `--performance-profile` | `fast`, `balanced` (Default) oder `quality` |
| `--auto-markers` | Automatisch erzeugte whisperX-Marker speichern |
| `--keep-wav` | Temporäre WAV-Datei behalten |
| `--verbose` | Detaillierte Logs |

## Ausgabeformate

### Ausgabeordner

Im CLI-Modus und bei einem zentralen GUI-Ausgabeordner landen Ergebnisse in einem
Unterordner mit dem aktuellen Datum:

```
<gewähltes Ausgabeverzeichnis>/
└── 2026-07-07/
    ├── audio.txt
    ├── audio.md
    ├── audio.csv
    └── audio.tsv
```

Falls Dateien bereits existieren, wird dem Namen eine fortlaufende Zahl angehängt
(`audio_1.txt`, `audio_2.txt`, …). Mit der globalen GUI-Option **Neben der
Audio-Datei speichern** liegen die Ausgaben direkt neben der Aufnahme und werden
beim erneuten Anwenden einer Sprecheränderung als zusammengehöriger Dateisatz
atomar aktualisiert.

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
.venv/bin/python -m pytest -q
node --test tests/*.test.mjs
```

Linting:

```bash
ruff check .
```

## Architektur

```
src/bort/
├── app.py                 # pywebview-Bridge und App-Dienste
├── web/                   # HTML, CSS, JavaScript und Waveform-Logik
├── controller/            # Jobs, Batch, Wiedergabe und Sprecherbearbeitung
├── audio.py               # Audio → 16-kHz-Mono-WAV mit ffmpeg
├── transcription.py       # whisper.cpp-Subprozess
├── whisperx_backend.py    # externer whisperX-/whisper-tagger-Subprozess
├── speaker_review.py      # Review-Schemas v1-v3 laden und validieren
├── voice_profiles.py      # lokaler Namen- und Stimmprofilkatalog
├── writers.py             # transaktionale TXT/MD/CSV/TSV-Ausgabe
├── streaming.py           # Live-Fortschritt aus Subprozessen
└── cli.py                 # Kommandozeilen-Interface
```

## Lizenz

MIT

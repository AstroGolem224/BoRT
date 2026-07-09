# Plan: Transkriptions-App auf Basis von whisper.cpp

## Ziel
Eine kommandzeilenbasierte Python-App bauen, die:
- MP3-Dateien entgegennimmt,
- mit whisper.cpp transkribiert,
- optionale JSON-Marker-Dateien für Sprecherzuordnung nutzt,
- Transkripte mit Zeitstempel und Sprecher in drei Formaten ausgibt: Text, Markdown, Tabelle (CSV/TSV).

## Getroffene Entscheidungen (vom Nutzer bestätigt)
- **Sprecher**: Primär aus JSON-Marker-Datei; automatische Diarisierung später nachrüstbar; Fallback ist Placeholder (`SP1`, `SP2`, … bzw. `Unbekannt`).
- **Ausgabeformate**: Alle drei parallel erzeugen.
- **whisper.cpp-Integration**: Python-Bindings (`whisper-cpp-python`) über pip, um Build-Aufwand zu vermeiden.

## Architektur

```
BoRT/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── src/
│   └── bort/
│       ├── __init__.py
│       ├── cli.py                 # Argumentparser, Orchestrierung
│       ├── audio.py               # MP3 → WAV (16 kHz, mono) via ffmpeg
│       ├── markers.py             # Laden & Validieren der JSON-Marker
│       ├── speakers.py            # Sprecherauflösung (Marker → Segment)
│       ├── transcription.py       # whisper.cpp Aufruf / Segment-Struktur
│       └── writers.py             # txt / md / csv / tsv Ausgabe
└── tests/
    ├── test_markers.py
    ├── test_speakers.py
    └── test_writers.py
```

## Kernkomponenten

### 1. Audio-Vorverarbeitung (`audio.py`)
- ffmpeg per Subprocess aufrufen: `mp3` → `wav` (s16, 16 kHz, mono).
- Ausgabe in temporäres Verzeichnis (`tempfile.TemporaryDirectory`), optional aufbewahren via Flag.
- Prüfung, ob ffmpeg verfügbar ist.

### 2. Transkription (`transcription.py`)
- `whisper-cpp-python` nutzen, um Audiodatei zu transkribieren.
- Ergebnis in eigene `Segment`-Datenstruktur überführen:
  - `start: float`
  - `end: float`
  - `text: str`
- Modell-Pfad konfigurierbar; bei fehlendem Modell Hinweis auf Download (ggf. mit kleinem Helper-Skript).

### 3. JSON-Marker-Format (`markers.py`)
Unterstütztes Schema:
```json
{
  "speakers": {
    "SP1": "Alice",
    "SP2": "Bob"
  },
  "markers": [
    {"start": 0.0, "end": 12.5, "speaker": "SP1"},
    {"start": 12.5, "end": 30.0, "speaker": "SP2"}
  ]
}
```
- `markers` ist eine Liste von Zeitintervallen mit Sprecher-ID.
- `speakers` ist optional und mappt IDs auf Anzeigenamen.
- Validierung: überlappende Marker werden akzeptiert, aber geloggt.

### 4. Sprecherzuordnung (`speakers.py`)
- Abstrakte Basis `SpeakerResolver`.
- `MarkerSpeakerResolver`: Ordnet jedem Transkriptionssegment den Sprecher des überlappenden Markers zu (meiste Überlappung gewinnt).
- `PlaceholderSpeakerResolver`: Fallback, taggt Segmente nacheinander mit `SP1`, `SP2`, … oder einer einzigen `Unbekannt`-Kennung.
- Extension-Point für spätere `DiarizationSpeakerResolver`.

### 5. Ausgabeformate (`writers.py`)
- **Text (.txt)**: `[HH:MM:SS] Alice: gesprochener Text`
- **Markdown (.md)**: Überschriften pro Sprecher oder zeitlich sortierte Abschnitte mit Inline-Zeitstempel.
- **Tabelle (.csv / .tsv)**: Spalten `start`, `end`, `speaker`, `text`.

### 6. CLI (`cli.py`)
Argumente:
- `audio`: Pfad zur MP3-Datei
- `--markers`: Pfad zur JSON-Marker-Datei
- `--model`: Pfad zum ggml-Modell
- `--language`: Sprache (z.B. `de`, `en`)
- `--output-dir`: Zielverzeichnis
- `--formats`: Auswahl `txt,md,csv,tsv` (Default: alle)
- `--keep-wav`: temporäre WAV-Datei behalten

## Implementierungsschritte
1. Projektordner `BoRT` anlegen.
2. `pyproject.toml` mit Dependencies (`whisper-cpp-python`, ggf. `ffmpeg-python` oder reines subprocess) erstellen.
3. Modulstruktur unter `src/bort/` anlegen.
4. `audio.py`, `markers.py`, `speakers.py`, `transcription.py`, `writers.py`, `cli.py` implementieren.
5. README.md mit Installations-, Modell-Download- und Nutzungsanleitung schreiben.
6. Unit-Tests für Marker-Parsing, Sprecherzuordnung und Writer-Ausgabe schreiben.
7. Optionalen End-to-End-Test mit kurzem Beispiel-MP3 vorsehen.

## Abhängigkeiten
- Python ≥3.10
- `whisper-cpp-python`
- `ffmpeg` (Systempaket, bereits installiert)
- ggml-Modell-Datei für whisper.cpp (z.B. `ggml-base.bin`)

## Offene Punkte / Zukünftige Erweiterungen
- Automatische Sprecherdiarisierung via `pyannote.audio` als weiterer `SpeakerResolver`.
- Fortschrittsanzeige bei längeren Audiodateien.
- Konfigurationsdatei für wiederkehrende Einstellungen.

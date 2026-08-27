# Handover – BoRT (BoR Transcriber) + Whisper-Tagger

**Datum:** 2026-07-08
**Stand:** App voll funktionsfähig, modernes BoR-Design, Speaker-Manager, Android-Integration

---

## 1. Überblick

Zwei-Projekt-Setup für Audio-Transkription mit automatischer Sprecher-Erkennung:

| Projekt | Pfad | Zweck | Python |
|---|---|---|---|
| **BoRT** | `/home/itiger013/Dokumente/Github/BoRT` | GUI + CLI (customtkinter) | 3.14 |
| **whisper-tagger** | `/home/itiger013/projects/whisper-tagger` | whisperX-Pipeline (PyTorch/CUDA) | 3.12 |

**Hardware:** RTX 5090 (Blackwell, 32GB VRAM), ffmpeg systemweit

---

## 2. Was funktioniert (Stand jetzt)

- ✅ **whisperX-Backend**: VAD → Transkription → Alignment → Diarization (GPU)
- ✅ **whisper.cpp-Backend**: CPU-Pfad (ffmpeg → WAV → whisper-cli)
- ✅ **Sprecher-Diarization**: pyannote, Majority-Vote-Assignment, Segment-Merging
- ✅ **Speaker-Manager**: Nach Transkription öffnet Fenster mit ▶-Audio-Playback + Rename
- ✅ **Android-Integration**: .m4a + Marker-JSON (timeMs-Bookmarks) als 🔖-Marker im Transkript
- ✅ **Audio-Formate**: mp3, m4a, aac, wav, flac, ogg, opus, wma
- ✅ **Export**: TXT, MD, CSV, TSV (mit Bookmarks zeitlich einsortiert)
- ✅ **Modernes Design**: BoR-Card-Stil (schwarz/korallenrot), native Datei-Dialoge
- ✅ **Bundle**: PyInstaller, Desktop-Link mit eigenem Icon
- ✅ **Tests**: 19/19 grün, Lint clean

---

## 3. Wichtige Setup-Pitfalls

### whisper-tagger (GPU-Projekt)
- **Immer `./run.sh python ...` nutzen**, nie `uv run` direkt – Wrapper setzt `LD_LIBRARY_PATH` für nvidia-libs und lädt `.env` (HF_TOKEN)
- PyTorch muss `+cu128` sein (Blackwell). `pyproject.toml` erzwingt das über `[tool.uv.sources]`
- `torchaudio_shim.py` MUSS vor whisperx importiert werden – patcht `torch.load` (weights_only=False), `torchaudio.AudioMetaData` + `list_audio_backends`
- HF-Token in `.env`, Lizenzen für `pyannote/speaker-diarization-3.1` UND `pyannote/segmentation-3.0` akzeptiert (HF-User: astrogolem224)

### BoRT
- Python 3.14 via uv, customtkinter für GUI
- `__main__.py` ist Einstiegspunkt für PyInstaller (GUI default, CLI bei Argumenten)
- Backend-Auswahl: whisperX ist Default, `_on_backend_change()` steuert Modell-Widget-Sichtbarkeit
- Worker läuft im Thread, kommuniziert via `log_queue` (done_data enthält Ergebnis für Speaker-Manager)

---

## 4. Architektur

```
[Audio m4a/mp3/...] → BoRT CLI/GUI
  ├─ --backend whispercpp: ffmpeg→WAV → whisper-cli → Marker-resolver → Export
  └─ --backend whisperx (default): subprocess→whisper-tagger/run.sh
       → whisperX (VAD+transcribe+align+diarize) → JSON on stdout
       → whisperx_backend.py → SpeakerMarker + speaker_map (sprecher001...)
       → MarkerSpeakerResolver → Speaker-Segmente
       → [optional: Android-Marker-JSON → load_bookmarks() → 🔖-Marker]
       → write_outputs (txt/md/csv/tsv)
       → [auto: Speaker-Manager öffnet → Rename → neu schreiben]
```

### Android-Marker-Format
```json
{"version":1, "markers":[{"timeMs":15000, "type":"note", "label":"", "color":""}]}
```
- `load_markers()`: erkennt Android-Format, wandelt Punkt-Marker in Intervalle um
- `load_bookmarks()`: behält sie als Punkt-Marker für 🔖-Anzeige im Transkript
- Bookmarks werden NICHT als Sprecher verwendet

---

## 5. Build & Deployment

```bash
# Bundle neu bauen (dist/ + build/ löschen für sauberen Build)
cd /home/itiger013/Dokumente/Github/BoRT
rm -rf dist/ build/
uv run pyinstaller bort.spec --clean --noconfirm
```

- Ausgabe: `dist/bort/bort` (~58MB)
- Desktop-Links: `~/Schreibtisch/bort.desktop` + `~/Desktop/bort.desktop`
- Icon: `assets/icon-256.png` (BoR-Stil, Generator: `scripts/generate_icon.py`)

### Tests & Lint
```bash
cd /home/itiger013/Dokumente/Github/BoRT
uv run pytest -q          # 19 Tests
uv run ruff check src/    # Lint
```

---

## 6. Module-Übersicht (BoRT)

| Datei | Zweck |
|---|---|
| `gui.py` | Haupt-GUI, BoR-Card-Design, 4 Cards, Backend-Dropdown, Status-Indikator |
| `speaker_manager.py` | Toplevel-Fenster: Sprecher-Rename + ffplay-Audio-Playback |
| `whisperx_backend.py` | Subprocess-Wrapper für whisper-tagger, erzeugt SpeakerMarker |
| `markers.py` | `load_markers()` (Auto-Format-Erkennung), `load_bookmarks()`, `Bookmark`, `save_markers()` |
| `writers.py` | TXT/MD/CSV/TSV mit optionalen Bookmarks |
| `dialogs.py` | Moderne Info/Error-Dialoge im BoR-Stil |
| `filedialogs.py` | Native GTK-Datei-/Ordner-Dialoge |
| `theme.py` | COLORS-Dict (coral, card_bg, input_bg, border, text, muted, success, error) |
| `audio.py` | ffmpeg-basiert, SUPPORTED_AUDIO_EXTS |
| `cli.py` | CLI mit `--backend`, `--min/max-speakers`, `--no-diarize`, `--auto-markers` |
| `config.py` | GUI-Persistenz (`~/.config/bort/settings.json`) |

### whisper-tagger Module
| Datei | Zweck |
|---|---|
| `whisperx_transcribe.py` | CLI: VAD+transcribe+align+diarize → JSON auf stdout (Mindeststand: Commit `6981fce`, Segment-Clamp vor dem Alignment gegen CUDA-OOM) |
| `torchaudio_shim.py` | Patch für torch.load + torchaudio 2.11 slim |
| `run.sh` | Wrapper: LD_LIBRARY_PATH + .env laden |
| `.env` | HF_TOKEN (chmod 600) |
| `gen_test_audio.py` | Synthetisches 2-Sprecher-Testaudio via edge-tts |

---

## 7. Bekannte Limitierungen / TODOs

- Speaker-Manager zeigt nur erstes Segment pro Sprecher als Beispiel (könnte mehrere Samples zeigen)
- Kein Undo im Speaker-Manager
- VAD-Threshold nur über CLI einstellbar, nicht über GUI
- Bundle enthält keine Backends (whisper-cli + whisper-tagger bleiben extern)
- Theme-Umschalter (Light/Dark) wurde entfernt – nur Dark-Mode
- `_change_appearance()` in gui.py ist tote Methode (könnte entfernt werden)

---

## 8. Test-Dateien

- `/home/itiger013/Documents/unbenannt.mp3` – 3.58s, 1 Sprecher (Kurztest)
- `/tmp/multispeaker-test/conversation.m4a` – 38s, 2 Sprecher (synthetisch, edge-tts)
- `/home/itiger013/Downloads/drive-download-20260708T050433Z-3-001/` – echte Android-Demodatei (.m4a + .json)

---

## 9. Schnell-Start für neue Session

```bash
# GUI starten
/home/itiger013/Dokumente/Github/BoRT/dist/bort/bort

# CLI testen
cd /home/itiger013/Dokumente/Github/BoRT
uv run bort /home/itiger013/Documents/unbenannt.mp3 \
  --backend whisperx --language de --max-speakers 2 --auto-markers \
  --output-dir /tmp/test -v

# whisperX direkt testen
cd /home/itiger013/projects/whisper-tagger
./run.sh python whisperx_transcribe.py /path/to/audio.m4a --language de --max-speakers 2
```

## Sync-Ordner-Setup (Tailscale+SMB)

Statt manuellem Google-Drive-Download legt BoR (Android) Aufnahmen direkt auf einer per Tailscale erreichbaren SMB-Freigabe des PCs ab.

1. **PC:** Samba-Freigabe für den in BoRT unter „📦 Batch verarbeiten…“ gewählten Sync-Ordner einrichten: dedizierter Samba-Benutzer, kein Gastzugriff (`guest ok = no`), Zugriff ausschließlich für diesen Benutzer. Port 445 nur ans Tailscale-Interface binden bzw. per Firewall auf das Tailnet-Subnetz beschränken.
2. **Tailscale:** Auf PC und Handy im selben Tailnet installieren; ACLs so setzen, dass nur das Handy auf SMB des PCs zugreifen darf.
3. **Handy (BoR):** Als SAF-Zielordner `\\<pc-tailscale-ip>\<freigabename>` wählen. Androids Dateien-App unterstützt SMB ab Android 10; falls nötig CX File Explorer verwenden.
4. Der bestehende BoR-`Mover` kopiert fertige Paare dorthin; es ist keine BoR-Code-Änderung nötig.

**Bekanntes Risiko:** Bei einem SMB/VPN-Verbindungsabbruch während des Schreibens kann eine Teilkopie entstehen. BoRT prüft Größe und mtime jeder Kandidatendatei zweimal im Abstand von zwei Sekunden, bevor sie verarbeitet wird. Das verringert, eliminiert das Risiko unter echter Netzwerklast aber nicht vollständig.

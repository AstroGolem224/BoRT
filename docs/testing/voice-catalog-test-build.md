# BoRT-Testbuild: Performance und Stimmenkatalog

## Start

Nach dem Build liegt die einzelne ausführbare Linux-Datei hier:

```text
dist/test-build/BoRT-voice-catalog-linux-x86_64
```

Sie kann im Dateimanager doppelt angeklickt oder im Terminal gestartet werden:

```bash
./dist/test-build/BoRT-voice-catalog-linux-x86_64
```

Die Wayland-/NVIDIA-sicheren WebKit-Einstellungen sind in dieser Datei enthalten;
`launch.sh` ist für den Testbuild nicht erforderlich.

## Empfohlener Funktionstest

1. Backend `whisperX` wählen.
2. Modell `large-v3-turbo` und Profil `Ausgewogen` wählen.
3. Für einen ersten schnellen Lauf `Keine Sprechertrennung` aktivieren.
4. Danach einen Lauf mit Sprechertrennung und bekannter maximaler Sprecherzahl
   durchführen.
5. Für den Stimmenkatalog `Stimmprofile lokal erfassen` vor dem Lauf aktivieren.
6. Die erzeugte Review in der Sprecher-Ansicht öffnen, Namen prüfen und mit
   `Anwenden` in die Ausgaben schreiben.
7. Mit `Namen lokal merken` die bestätigten Namen und optionalen Stimmprofile in
   den lokalen Katalog übernehmen.
8. Dieselben Personen in einer zweiten Aufnahme testen. Vorschläge müssen
   anklickbar sein, dürfen aber nie automatisch angewendet werden.

## Voraussetzungen und Grenzen

- whisperX bleibt absichtlich im externen Projekt
  `~/projects/whisper-tagger` mit dessen CUDA-/PyTorch-Umgebung.
- Für Diarisierung muss dort der Hugging-Face-Token eingerichtet sein.
- `whisper-cli` und seine Shared Libraries sind im Testbuild enthalten.
- GGML-Sprachmodelle sind wegen ihrer Größe nicht eingebettet. Für den CPU-Pfad
  kann beispielsweise `models/ggml-base.bin` in der GUI gewählt werden.
- Der Katalog liegt unter `~/.local/share/bort/voice_profiles.json`.
- Katalog und biometrische Review-Dateien werden mit restriktiven Rechten
  geschrieben. Profile können einzeln in der Sprecher-Ansicht gelöscht werden.

## CLI-Smoke-Test

```bash
./dist/test-build/BoRT-voice-catalog-linux-x86_64 audio.m4a \
  --backend whispercpp \
  --model models/ggml-base.bin \
  --language de \
  --output-dir /tmp/bort-test \
  --formats txt
```

## Neu bauen

```bash
./scripts/build-test-executable.sh
```

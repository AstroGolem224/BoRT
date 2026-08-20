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

1. Im Reiter **Optionen** Backend `whisperX`, Modell `large-v3-turbo` und Profil
   `Ausgewogen` wählen.
2. Zu **Transkribieren** wechseln. Die Zusammenfassung muss dieselben globalen
   Werte zeigen.
3. Für einen ersten schnellen Lauf `Keine Sprechertrennung` aktivieren.
4. Danach einen Lauf mit Sprechertrennung und bekannter maximaler Sprecherzahl
   durchführen.
5. Für den Stimmenkatalog `Stimmprofile lokal erfassen` vor dem Lauf aktivieren.
6. Die erzeugte Review in **Sprecher** öffnen. Die angezeigte Segmentzahl mit
   der Review vergleichen und bei einem langen Transkript bis zum Ende scrollen.
7. Einen Sprechernamen direkt im Transkript anklicken. Manuell tippen und danach
   einen gespeicherten Namen wählen. Alle Vorkommen, Picker und Waveform müssen
   gemeinsam aktualisiert werden.
8. **Hörprobe** auslösen. Die Scrollposition darf nicht springen. Die getrennte
   Aktion **Im Transkript zeigen** muss zum ersten Segment navigieren.
9. Am Ende des Transkripts den schwebenden **Änderungen anwenden**-Knopf drücken.
   Er muss `Speichert …` und danach `Gespeichert` oder einen sichtbaren Fehler
   anzeigen. Review und Ausgabeformate müssen aktualisiert sein.
10. Einen weiteren Namen ändern und `Strg+S` drücken. Der Browser-Speicherdialog
    darf nicht erscheinen; stattdessen muss derselbe Speichervorgang laufen und
    kurz `<dateiname>.review.json saved` eingeblendet werden.
11. Mit `Namen lokal merken` die bestätigten Namen und optionalen Stimmprofile in
    den lokalen Katalog übernehmen.
12. Dieselben Personen in einer zweiten Aufnahme testen. Vorschläge müssen
    anklickbar sein, dürfen aber nie automatisch angewendet werden.

## Automatische Prüfungen

```bash
.venv/bin/python -m pytest -q
node --test tests/*.test.mjs
node --check src/bort/web/app.js
ruff check .
git diff --check
```

Die CSS-Datei kann zusätzlich mit `tinycss2.parse_stylesheet` auf Syntaxfehler
geprüft werden. Ein erfolgreicher Starttest hält die GUI acht Sekunden geöffnet:

```bash
timeout 8s ./dist/test-build/BoRT-voice-catalog-linux-x86_64
```

Exitcode `124` bedeutet bei diesem Test, dass die Anwendung bis zum Timeout
stabil lief. Meldungen zu optionalen GTK-Modulen wie `canberra-gtk-module` sind
Umgebungswarnungen und kein Startfehler.

## Voraussetzungen und Grenzen

- whisperX bleibt absichtlich im externen Projekt
  `~/projects/whisper-tagger` mit dessen CUDA-/PyTorch-Umgebung.
- Der getestete Begleitstand für Decode-Profile, Embeddings und Laufmetrik ist
  whisper-tagger-Commit `0ec2af0`.
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

Prüfsumme erzeugen und kontrollieren:

```bash
cd dist/test-build
sha256sum BoRT-voice-catalog-linux-x86_64 \
  > BoRT-voice-catalog-linux-x86_64.sha256
sha256sum -c BoRT-voice-catalog-linux-x86_64.sha256
```

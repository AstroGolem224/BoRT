# Changelog

Alle wesentlichen Änderungen an BoRT werden in dieser Datei dokumentiert.

## Unreleased – Performance, Stimmenkatalog und Sprecher-Workflow

### Transkription und Performance

- `large-v3-turbo` ist der whisperX-Default für neue Installationen. Bereits
  gespeicherte Modellwahlen werden nicht überschrieben.
- Drei reproduzierbare whisperX-Profile steuern Beam- und Batchgröße:
  `fast` (1/32), `balanced` (3/24) und `quality` (5/16).
- whisper.cpp wählt automatisch eine konservative Threadzahl und ergänzt den
  Bibliothekspfad des vendorten Binaries pro Prozess.
- whisperX kann bei deaktivierter Diarisierung unnötiges Alignment überspringen.
- Review-Dateien können Laufmetrik, Laufparameter, Embedding-Modell und lokale
  Sprecher-Embeddings im abwärtskompatiblen Schema v3 enthalten.

### Lokaler Namen- und Stimmenkatalog

- Bestätigte Namen können lokal und XDG-konform in
  `~/.local/share/bort/voice_profiles.json` gespeichert werden.
- Optionale Stimmprofile verwenden normalisierte Embedding-Zentroiden,
  Modell-/Dimensionsschutz und konservatives Kosinus-Matching.
- Stimmprofile sind standardmäßig deaktiviert, bleiben lokal und werden niemals
  automatisch auf eine Review angewendet.
- Der Katalog wird atomar geschrieben; Verzeichnis und Datei erhalten restriktive
  Rechte. Beschädigte Kataloge werden nicht still überschrieben.
- Katalogeinträge sind in der Sprecheransicht auswählbar und einzeln löschbar.

### Sprecher-Review und Bedienung

- Lange Transkripte verwenden den Seiten-Scrollbereich und werden nicht mehr durch
  einen verschachtelten `60vh`-Bereich abgeschnitten.
- Die Sprecherliste ist ein kompakter zweispaltiger Master-Detail-Picker mit
  aktiver Auswahl, Waveform-Farben und Tastaturnavigation.
- Sprecher lassen sich direkt an jeder Namensmarke im Transkript bearbeiten.
  Manuelle Eingabe, gespeicherte Namen und Vorschläge aktualisieren alle
  Vorkommen, die Übersicht und die Waveform gemeinsam.
- Hörprobe und Navigation sind getrennt: Abspielen verändert die Scrollposition
  nicht; „Im Transkript zeigen“ navigiert ausdrücklich zum ersten Segment.
- Ein schwebender „Änderungen anwenden“-Knopf bleibt auch am Ende langer
  Transkripte erreichbar und zeigt Speichererfolg oder Fehler direkt an.

### Globale Optionen und Design

- Transkriptionsoptionen befinden sich in einem eigenen App-Reiter und gelten
  gemeinsam für Einzeltranskription und Batch.
- Die aktiven globalen Optionen werden in Transkribieren und Batch kompakt
  zusammengefasst und sofort in `~/.config/bort/settings.json` gespeichert.
- Die pywebview-Oberfläche nutzt ein Mimic-inspiriertes Glassmorphism-/
  Neumorphism-Design unter Beibehaltung der Cyan-/Violett-Farbwelt.

### Build und Qualitätssicherung

- Ein PyInstaller-Onefile-Build bündelt GUI, Web-Ressourcen, `whisper-cli` und
  dessen Shared Libraries für Linux x86_64.
- GGML-Modelle und das externe CUDA-/whisperX-Projekt bleiben absichtlich extern.
- Ergänzt wurden Tests für Stimmenkatalog, Review-Schema v3, Backend-Profile,
  whisper.cpp-Laufzeitumgebung, Persistenz und transaktionales Schreiben.

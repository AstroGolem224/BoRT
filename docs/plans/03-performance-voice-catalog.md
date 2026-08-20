# BoRT Performance- und Stimmenkatalog-Plan

Stand: 2026-08-20
Branch: `codex/performance-voice-catalog`

## Umsetzungsstand dieses Branches

Bereits umgesetzt und getestet:

- `large-v3-turbo` ist der neue Default für neue Installationen; bestehende
  gespeicherte Modellwahlen bleiben erhalten.
- Die GUI bietet die reproduzierbaren Decode-Profile `Schnell` (Beam 1),
  `Ausgewogen` (Beam 3) und `Maximale Qualität` (Beam 5); Batchgröße und Profil
  werden an whisper-tagger durchgereicht und in den Laufmetadaten festgehalten.
- whisper.cpp erhält automatisch eine passende Threadzahl und einen lokalen
  `LD_LIBRARY_PATH`, wodurch der zuvor nicht startbare Vendor-Build wieder läuft.
- Ohne Diarisierung überspringt whisper-tagger das nicht benötigte Alignment.
- ASR- und Alignment-Modelle werden vor der nächsten GPU-Phase freigegeben.
- Phasenlaufzeiten und reproduzierbare Laufmetadaten landen in Review Schema v3.
- Ein atomarer lokaler Namens- und Stimmenkatalog samt Modell-/Dimensionsschutz,
  Zentroid-Updates und konservativem Kosinus-Matching ist implementiert.
- Die Web-UI bietet Namen per Auswahlliste an. Biometrische Profile sind opt-in;
  Treffer erscheinen nur als anklickbare Vorschläge. Einzelne Katalogprofile sind
  in der Oberfläche sichtbar und löschbar.
- whisper-tagger liefert auf Wunsch die bereits von pyannote berechneten
  Embeddings. Reviews mit diesen Daten werden mit Dateimodus `0600` geschrieben.
- Transkriptionswerte liegen in einem globalen Optionen-Reiter und werden von
  Einzel- und Batchverarbeitung gemeinsam genutzt.
- Lange Sprechertranskripte verwenden den Seiten-Scrollbereich und werden nicht
  mehr durch einen verschachtelten `60vh`-Bereich abgeschnitten.
- Der Sprecher-Workflow bietet einen kompakten Picker, direkte Namensbearbeitung
  im Transkript, gespeicherte Namen, getrennte Hörprobe/Navigation und einen
  schwebenden Anwenden-Knopf mit unmittelbarem Speicherstatus.
- Die Oberfläche verwendet ein Mimic-inspiriertes Glassmorphism-/Neumorphism-
  Design unter Beibehaltung der bestehenden Farben.

Reale Warm-Cache-Smoke-Tests mit 38,3 Sekunden Audio:

- whisper.cpp `base`: 0,856 Sekunden beziehungsweise rund 44,7-fache Echtzeit.
- whisperX `medium` plus Alignment, Diarisierung und Embeddings: 3,846 Sekunden
  interne Pipelinezeit, zwei Sprecher und je ein 256-dimensionales Profil.
- whisperX `large-v3-turbo` vollständig: 4,236 Sekunden interne Pipelinezeit;
  `large-v3`: 5,261 Sekunden. Turbo war auf diesem kurzen Beispiel intern rund
  19,5 Prozent schneller, inklusive Prozessstart rund 11,7 Prozent.
- Turbo ohne Diarisierung und ohne nun unnötiges Alignment: 1,824 Sekunden
  interne Pipelinezeit.

Der vollständige BoRT-Subprocess-Aufruf brauchte bei Turbo 8,664 Sekunden. Damit
entfallen auf Python-/CUDA-Import und Prozessstart rund 4,4 Sekunden. Das bestätigt
den persistenten GPU-Worker als wichtigsten nächsten Hebel für viele kurze Dateien.
Diese kurzen Tests messen vor allem Warm-Cache-Verhalten und ersetzen noch keinen
reproduzierbaren Goldkorpus-Benchmark.

Noch offen sind insbesondere der persistente GPU-Worker, Community-1-Evaluation,
segmentgenaues Splitten an Sprecherwechseln, Katalog-Export/Gesamtreset
und die profilbasierte Qualitätskaskade.

## Zielbild

BoRT soll lange deutsch-/englischsprachige Aufnahmen lokal schneller verarbeiten,
die Qualität der Sprechertrennung erhöhen und wiederkehrende Personen über mehrere
Transkripte hinweg als bestätigte Namensvorschläge erkennen können.

Die bestehende Trennung bleibt erhalten:

- `whisper.cpp` ist der kleine, robuste CPU-Pfad.
- `whisperX` bleibt der GPU-Pfad für Alignment und Diarisierung.
- Neue große Python-/CUDA-Abhängigkeiten bleiben im externen `whisper-tagger`.
- Audio, Transkripte, Embeddings und Katalogdaten verlassen den Rechner nicht.

## Sicherheits- und Produktentscheidungen für Stimmprofile

Stimm-Embeddings sind biometrische Daten. Deshalb gelten folgende Regeln:

1. Stimmprofile sind standardmäßig deaktiviert und werden ausdrücklich aktiviert.
2. Ein Modelltreffer benennt niemals automatisch einen Sprecher um. Er ist nur ein
   Vorschlag mit Ähnlichkeitswert und muss bestätigt werden.
3. Der Katalog liegt lokal im XDG-Datenverzeichnis, das Verzeichnis erhält Modus
   `0700`, die JSON-Datei Modus `0600`.
4. Gespeichert werden Name, normalisierter Embedding-Zentroid, Embedding-Modell,
   Dimension, Anzahl bestätigter Beispiele und Zeitstempel. Es werden keine
   Audioausschnitte in den Katalog kopiert.
5. Ein Namenseintrag darf auch ohne Embedding existieren. Damit funktioniert der
   Katalog als Namensauswahl, wenn für eine ältere Review kein Stimmprofil vorliegt.
6. Profile verschiedener Embedding-Modelle oder Dimensionen werden nie direkt
   verglichen.
7. Löschen, Exportieren und Zurücksetzen des Katalogs werden in der UI vorgesehen.

## Messbasis

Beobachteter Ist-Zustand auf Ryzen 9 9900X3D und RTX 5090:

- whisperX `large-v3`, Alignment und Diarisierung: 3.682 Sekunden Audio in rund
  144 Sekunden, also etwa 25,6-fache Echtzeit.
- whisper.cpp `base`, vier Threads: 120 Sekunden Audio in 4,33 Sekunden.
- whisper.cpp `base`, zwölf Threads: 120 Sekunden Audio in 2,37 Sekunden.
- Der aktuelle whisper.cpp-Build hat einen veralteten RUNPATH und findet seine
  gemeinsam genutzten Bibliotheken ohne manuellen `LD_LIBRARY_PATH` nicht.

## Phase 0 – Messbarkeit und Reparaturen

### Änderungen

- whisper.cpp mit einem pro Prozess gesetzten Bibliothekspfad zuverlässig starten.
- Threadzahl anhand der verfügbaren CPU sinnvoll setzen und später als Expertenwert
  überschreibbar machen.
- Gesamt- und Phasenlaufzeiten mit `time.perf_counter()` erfassen.
- Backend, Modell, Compute-Type, Batchgröße, Sprache und Diarisierungsmodus in der
  Review als reproduzierbare Laufmetadaten speichern.
- Fortschrittsphasen explizit aus dem Backend melden.

### Akzeptanz

- CPU-Transkription startet aus GUI und CLI ohne Shell-Workaround.
- Ein Runtime-Smoke-Test prüft das echte vendorte Binary mit seinen Bibliotheken.
- Jede neue Review enthält mindestens Gesamtdauer, Backend und Modell.
- Alte Review-Schemas bleiben lesbar.

## Phase 1 – Schnelle Profile und Modellwahl

### Änderungen

- `large-v3-turbo` in CLI, Web-UI und Validierung aufnehmen.
- Produktprofile einführen:
  - `Schnell`: Turbo, optional Beam 1 bis 3, Alignment nur wenn benötigt.
  - `Ausgewogen`: Turbo oder Large-v3, Beam 5, Alignment und Diarisierung.
  - `Maximale Qualität`: Large-v3, feste Sprecherzahl wenn bekannt.
- Bei `no_diarize` Alignment standardmäßig überspringen, sofern keine
  Wortzeitstempel angefordert werden.
- `batch_size`, `beam_size`, `compute_type`, VAD-Schwelle und Hotwords kontrolliert
  durchreichen.
- Sprachmodus explizit zwischen festem Deutsch, festem Englisch,
  Deutsch/Englisch-Mix und allgemeinem Auto unterscheiden.

### Akzeptanz

- Turbo kann ohne neuen Download gewählt werden, wenn es bereits gecacht ist.
- Ein identischer Testkorpus vergleicht Geschwindigkeit und Qualität mit Large-v3.
- Der Schnellmodus erreicht mindestens 35-fache Echtzeit im vollständigen Pfad oder
  dokumentiert, welche nachgelagerte Phase das Ziel verhindert.
- Turbo wird nicht stillschweigend für Übersetzung angeboten.

## Phase 2 – Persistenter GPU-Worker

### Änderungen

- Den einmaligen Subprocess pro Datei durch einen langlebigen lokalen Worker ersetzen.
- ASR-, Alignment- und Diarisierungsmodelle nach Schlüssel cachen.
- Idle-Timeout und explizites Entladen implementieren.
- Batchgröße aus freiem VRAM und gewähltem Profil ableiten.
- Abbruchsignal bis in den aktiven Backendprozess durchreichen.
- Bei Speicherknappheit zwischen Durchsatzmodus und speicherschonendem Entladen
  umschalten.

### Akzeptanz

- Ein Batch mit fünf kurzen Dateien lädt jedes gewählte Modell höchstens einmal.
- Abbruch beendet den aktiven Job und hinterlässt keinen verwaisten GPU-Prozess.
- Kein OOM bei einem vorab definierten freien-VRAM-Budget.
- Nach Idle-Timeout wird GPU-Speicher nachweisbar freigegeben.

## Phase 3 – Bessere Sprechertrennung

### Änderungen

- `pyannote/speaker-diarization-community-1` evaluieren und als neuen lokalen
  Standard übernehmen, sofern der Goldkorpus die Verbesserung bestätigt.
- Exklusive Diarisierung verwenden, wenn verfügbar.
- Wortzeitstempel über einen linearen Intervall-Sweep Sprecherintervallen zuordnen.
- Transkriptsegmente an Sprecherwechseln teilen, statt einem kompletten ASR-Chunk
  nur den Mehrheits-Sprecher zu geben.
- Bekannte Sprecherzahl prominenter anbieten und in Laufmetadaten dokumentieren.
- Die doppelte, quadratische Sprecherzuordnung entfernen.

### Akzeptanz

- Sprecherwechsel innerhalb eines 15-Sekunden-ASR-Chunks bleiben erhalten.
- Laufzeit der Zuordnung wächst näherungsweise linear mit Wörtern und Intervallen.
- DER und speaker-attributed WER verschlechtern sich auf keinem freigegebenen
  Testszenario; Ziel ist eine messbare Verbesserung bei Meetings.

## Phase 4 – Lokaler Namens- und Stimmprofilkatalog

### Datenfluss

1. whisper-tagger fordert bei aktivierter Option Sprecher-Embeddings aus der
   Diarisierung an.
2. Das Backend liefert `speaker_embeddings` und eine stabile
   `embedding_model`-Kennung im JSON.
3. BoRT legt diese Daten nur bei aktivierter Funktion in der Review ab.
4. Beim Öffnen einer Review vergleicht BoRT jedes Sprecher-Embedding per
   Kosinusähnlichkeit mit kompatiblen Katalogprofilen.
5. Die UI zeigt die besten Vorschläge und vorhandene Katalognamen an.
6. Nach manueller Namensbestätigung kann der Nutzer ausgewählte Sprecher in den
   Katalog aufnehmen oder ein bestehendes Profil mit einem weiteren bestätigten
   Beispiel aktualisieren.

### Matching

- Embeddings werden vor Speicherung und Vergleich auf Länge 1 normalisiert.
- Ein Profil speichert einen laufend aktualisierten Zentroid und `sample_count`.
- Die anfängliche Schwelle ist konservativ und wird auf einem lokalen Korpus
  kalibriert. Unterhalb der Schwelle gibt es keinen Namensvorschlag.
- Die besten drei kompatiblen Kandidaten können angezeigt werden; Gleichstände oder
  geringe Abstände werden als unsicher markiert.
- Kein Profilmatching zwischen unterschiedlichen Modellkennungen.

### Akzeptanz

- Ein Name kann ohne Embedding angelegt und in späteren Reviews ausgewählt werden.
- Ein bestätigtes Embedding kann einem Namen hinzugefügt und in einer neuen Review
  als Vorschlag gefunden werden.
- Unbestätigte Vorschläge verändern weder Review noch Ausgabedateien.
- Dateirechte, atomisches Schreiben, kaputte JSON-Dateien und nicht-finite Vektoren
  sind getestet.
- Ein einzelnes Profil und der ganze Katalog sind aus der UI löschbar.

## Phase 5 – Alternative ASR-Backends und Qualitätskaskade

### Kandidaten

- Parakeet TDT 0.6B v3 als drittes Subprocess-Backend. Das vendorte whisper.cpp
  enthält bereits `parakeet-cli`.
- Canary 1B v2 als Qualitäts-Challenger für europäische Sprachen.
- Qwen3-ASR 0.6B/1.7B als experimenteller Kandidat für schwieriges Audio und
  Code-Switching.

### Kaskade

- Schneller Erstlauf mit Turbo oder Parakeet.
- Konfidenzen und problematische Audioabschnitte erhalten.
- Nur unsichere Abschnitte mit Large-v3 oder einem Qualitätsmodell wiederholen.
- Roh- und korrigierten Text getrennt und reversibel speichern.

## Benchmark- und Freigabestrategie

Der lokale Goldkorpus soll mindestens enthalten:

- klares Deutsch,
- klares Englisch,
- Deutsch/Englisch-Code-Switching,
- Meeting mit mindestens drei Personen,
- überlappende Sprache,
- leise oder verrauschte Abschnitte,
- interne Namen und Fachabkürzungen.

Gemessen werden:

- WER/CER,
- Diarization Error Rate und speaker-attributed WER,
- Gesamt- und Phasen-RTF,
- Peak-VRAM und Peak-RAM,
- Anzahl unbekannter oder zusätzlicher Sprecher,
- Katalog-Top-1/Top-3-Trefferrate sowie Falschzuordnungsrate.

Freigaben erfolgen profilweise. Ein schnelleres Modell ersetzt Large-v3 erst dann,
wenn die lokal relevante Qualität akzeptabel ist; externe Benchmarkwerte allein
reichen nicht aus.

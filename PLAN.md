# Plan: BoRT Bibliothek, Co-located Dateilayout, BoR-Peaks
_Locked via grill — by Claude (Forge) + Matthias, 2026-07-24. Alle drei Grill-Fragen bejaht
(Co-located als Batch-Standard + Checkbox; Migration mit dry-run; Bibliothek v1 schlank).
Supersedes den Redesign-PLAN.md (gebaut & committed, b15a5ea); Historie in git._

## Goal

Drei aufeinander aufbauende Features:
**(B) Co-located Layout** — Transkripte und `.review.json` liegen künftig neben der `.m4a`
im Sync-Tagesordner statt in einem getrennten `BoR_Transkripte`-Baum; Migrationsskript mit
dry-run für den Bestand.
**(C) Bibliotheks-View** — vierter Sidebar-Eintrag, zeigt alle Aufnahmen eines Ordners mit
Mini-Waveform (aus BoR-`peaks`), Dauer, Badges (Transkript/Review/Marker) und Aktionen
(Review öffnen, Transkription starten).
**(A) BoR-Peaks als Sofort-Waveform** — die 104 Peaks aus der BoR-Meta-Sidecar rendern die
Sprecher-View-Waveform sofort, bis die hochauflösenden ffmpeg-Peaks sie ersetzen.
Reihenfolge der Umsetzung: B → C → A.

## Kontext (Ist-Zustand, verifiziert)

- BoR-Android schreibt pro Aufnahme `NAME.m4a` + `NAME.json` (Meta-Sidecar) in
  Tagesordner `yyyy-MM-dd/`. Sidecar-Schema laut Handover
  (`/home/itiger013/Dokumente/UMBRA-Notes/DDs/BoRT/Peaks_Handover_BoRT_Implementer.md`):
  `version, file, startedAt, durationMs, markers[{timeMs,type,label}], peaks[104]`.
  `peaks`: 0..1, Bucket-Maximum, gleichmäßig über `durationMs`; kann fehlen/leer/≠104 sein.
- BoRT parst diese Sidecar bereits als Marker-Datei: `markers.py::_is_android_format`
  (Erkennung via `timeMs`), `find_companion_marker` findet `NAME.json` neben der Audio.
- Outputs heute: `writers.py::write_outputs(output_dir, base_name, formats, …)` legt bei
  `overwrite=False` einen Datums-Unterordner an und macht den Basenamen kollisionsfrei
  (`_unique_base_name`); bei `overwrite=True` wird exakt `output_dir/base_name.*` geschrieben.
  Review-Sidecar (`.review.json`, Schema v2 mit `speaker_id`) wird mitgeschrieben.
- Batch: `batch.py::scan_pending(watch_dir, output_dir)` listet Audios ohne aktuelles Output;
  `_has_output` sucht per `rglob` im getrennten Output-Baum. `is_file_stable` (Doppel-Stat).
- Transkription: `controller/jobs.py` — `TranscriptionParams.output_dir`; whisperX-Pfad
  schreibt bei `auto_markers` eine `*.markers.json` in den Output-Ordner (Zeile ~225).
- UI: 3 Views (Transkribieren, Batch, Sprecher) in `src/bort/web/{index.html,app.js,style.css}`,
  `wave_math.js` (pure Logik, node-getestet), Bridge-Pattern via pywebview (`app.py::Bridge`),
  CSP verbietet Inline-JS/CSS. Sprecher-View lädt Reviews über `pick_review_file`
  (Dialog → `load_review` → `RegisteredReview` → opake `review_id`).
- Waveform: `get_waveform(review_id)` → ffmpeg-Peaks (Cache, Koaleszenz); Frontend rendert
  Canvas mit Guards (`waveformResult`, Readiness-Gate, Stale-Guard).
- Tests: pytest (101) + node-Tests; `tests/conftest.py` isoliert `Config()`.

## Approach

### Teil 0 — Einstiegspunkte begradigen (Vorarbeit, Codex-R1 #1)

0. `pyproject.toml`: `bort-gui = "bort.app:main"`; `__main__.py`: GUI-Zweig importiert
   `bort.app:main` statt `bort.gui:main`. Die Tk-Module (`gui.py`, `speaker_manager.py`,
   `batch_window.py`) bleiben unangetastet liegen (Ausbau ist eigener Task), aber kein
   dokumentierter Startweg zeigt mehr auf sie. Smoke-Test: `bort-gui` öffnet die
   pywebview-App.

### Teil B — Co-located Layout

1. **`TranscriptionParams` + Settings:** neues Feld `colocate: bool`. UI: Checkbox
   „Neben der Audio-Datei speichern" im Transkribieren-Tab (bei aktiv: Ausgabeordner-Feld
   ausgegraut, nicht entfernt); persistiert via `save_output_options` + `initial_state`
   (Key `last_colocate`, Default **True**). Batch: nutzt dieselbe Einstellung
   (formSettings wird bereits an `start_batch` übergeben).
2. **Job-Pfad (`jobs.py`):** bei `colocate=True` wird effektiv
   `output_dir = params.audio_path.parent` und `write_outputs(..., overwrite=True)` mit
   `base_name = audio_path.stem` aufgerufen (kein Datums-Unterordner, kein Unique-Suffix —
   der Stem MUSS dem Audio entsprechen, sonst bricht die Paarung). Validierung Start: bei
   colocate muss der Audio-Ordner beschreibbar sein; Fehler klar melden.
   Ausgabeordner-Pflichtfeld entfällt in diesem Modus (Validierungszweig anpassen).
   - **Output-Commit als Manifest-Transaktion (R1 #4/#5, R2 #1/#2, R3 #1–#4):**
     Garantie: Per-Datei-Atomarität + vollständiger Satz-Rollback über ein Manifest.
     Transaktions-ID `txn = uuid4`. Ablauf im overwrite-Modus:
     (a) alle Dateien (Formate, Review-Sidecar, `markers.json`) exklusiv als
     `NAME.EXT.<txn>.tmp` erzeugen (`open(..., 'x')`), schreiben, fsyncen, schließen;
     (b) Manifest `.bort-txn-<txn>.json` — Liste `{final_name, had_predecessor,
     staged_sha256, predecessor_sha256|null}` (R5 #1) — als UUID-tmp schreiben, fsyncen,
     per `os.replace` publizieren, **Zielordner fsyncen** (R4 #2);
     (c) je Bestandsdatei Backup `NAME.EXT.<txn>.bak` per `os.replace`, danach dir-fsync;
     (d) alle tmp per `os.replace` publizieren, danach dir-fsync;
     (e) **Commit-Punkt = atomares Löschen des Manifests** + dir-fsync; erst DANACH
     Backups löschen (R4 #1). Recovery-Regel: Manifest existiert → Transaktion unvollständig → pro Mitglied gilt die
     **inhaltsverifizierte Wahrheitstabelle (R5 #1, R6):**
     | Zustand (Ziel-Hash / Backup) | Aktion |
     |---|---|
     | `had_predecessor`, Ziel fehlt ODER = `staged_sha256`, Backup valide (= `predecessor_sha256`) | Backup restaurieren |
     | `had_predecessor`, Ziel = `predecessor_sha256`, kein Backup | No-op (Publish war noch nicht dran) |
     | ohne Vorgänger, Ziel fehlt | No-op |
     | ohne Vorgänger, Ziel = `staged_sha256` | Ziel löschen |
     | jede andere Hash-/Backup-Kombination | Dateien unangetastet lassen, manueller Konflikt im Report |
     Die Tabelle wird als solche getestet (ein Testfall pro Zeile). Manifest fehlt →
     committed, verwaiste validierte `.bak`/`.tmp` der txn dürfen (mit Altersschwelle
     1 h) aufgeräumt werden (R4 #5).
     Fehler in (a/b) → tmp/Manifest löschen, Bestand unberührt. Fehler in (c) → ALLE
     bereits angelegten Backups restaurieren, dann aufräumen (R3 #1).
     **Recovery-Zeitpunkt (R4 #10):** nicht nur vor dem nächsten Schreiben — auch
     `scan_pending` und `scan_library` stoßen beim Antreffen eines Manifests im
     jeweiligen Ordner erst die Recovery an und lesen dann.
     **Manifest-Validierung (R4 #3):** Recovery mutiert nur nach strikter Prüfung —
     Schema, txn-ID = Dateiname, `final_name` basename-only mit erlaubtem Suffix,
     zugehörige tmp/bak-Namen exakt `<final>.<txn>.{tmp,bak}` im selben Ordner; alles
     andere wird in `.bort-txn-<txn>.json.invalid` umbenannt und gemeldet, referenzierte
     Dateien bleiben unangetastet.
     **Locking (R3 #3, R4 #4):** txn-Suffix auf tmp UND bak verhindert Namenskollisionen;
     zusätzlich OS-Advisory-Lock (`fcntl.flock` auf `.bort-lock` im Zielordner), gehalten
     über Recovery + gesamte Transaktion — schützt auch gegen eine zweite BoRT-Instanz.
3. **Batch (`batch.py`):** `scan_pending` scannt Root **plus direkte Unterordner**
   (Tiefe 1, Symlink-Verzeichnisse ausgeschlossen) — deckt die BoR-Struktur
   `Sync-Root/yyyy-MM-dd/*.m4a` ab, egal ob der User Root oder Tagesordner wählt (R1 #2).
   - **Fertig-Semantik (R1 #3, R2 #3/#4, R3 #5):** Frontend übergibt `formSettings()` an
     `scan_batch` (ganze Kette: `app.js` → Bridge validiert → `BatchController.scan` →
     `scan_pending`). EINE geteilte Funktion `expected_artifacts(settings)` — von Worker
     UND Scanner benutzt — definiert den Satz exakt nach realem Worker-Verhalten:
     gewählte Formate; `.review.json` bei jedem whisperX-Lauf (auch `no_diarize`, so
     schreibt `_review_data` heute); `.markers.json` nur bei
     whisperX ∧ auto_markers ∧ ¬no_diarize. Eine Aufnahme gilt nur als erledigt, wenn
     ALLE anwendbaren Artefakte neben dem Audio existieren und aktuell sind
     (mtime ≥ Audio). Zwei definierte Zweige (R4 #6): colocate prüft direkte Nachbarn;
     Nicht-colocate behält den Output-Baum-Lookup (`output_dir/**`), aber **familienweise
     (R5 #4)**: alle erwarteten Artefakte müssen im SELBEN Verzeichnis mit demselben
     Basenamen liegen — ein Verzeichnis, das den kompletten Satz aktuell enthält, zählt;
     Streu-Treffer aus verschiedenen Datumsordnern kombinieren sich nicht. Beide Zweige
     nutzen denselben `expected_artifacts`-Satz.
   - **Scan/Start-Kohärenz (R3 #6):** `_pending_batch` speichert einen normalisierten
     Settings-Fingerprint des Scans; `start_batch` mit abweichenden relevanten Settings
     (Formate, Backend, colocate, no_diarize, auto_markers) → Fehler „Bitte neu scannen".
   - **Re-Check pro Item (R3 #7):** `_process_item` prüft den gebundenen Artefakt-Satz
     direkt vor der Verarbeitung erneut und überspringt Items, die inzwischen (Sync,
     anderer Lauf) vollständig sind — als „Übersprungen: bereits vollständig" gemeldet.
   - mtime bleibt das Aktualitätskriterium (R1 #6 teilweise abgelehnt, siehe Key decisions).
4. **„Öffnen"-Button** im Transkribieren-Tab öffnet im colocate-Fall den Audio-Ordner.
   - **Review-Umbenennen im Colocate-Fall deaktivieren (R1 #9, R2 #7):** Durchsetzung
     im **Backend**: `rename_review` lehnt ab, sobald die exakte `<stem>.json` neben dem
     Audio EXISTIERT — auch wenn sie gerade nicht valide lesbar ist (halb geschriebene
     Sync-Datei darf kein Bypass sein, R3 #10) —
     `rename_base` würde sonst die BoR-Paarung brechen; in die BoR-Sidecar schreiben wir
     grundsätzlich nicht (Out of scope). Das readonly-Feld + Hinweis im UI ist reine
     Präsentation derselben Regel. Nicht-BoR-Reviews behalten das Umbenennen unverändert.
5. **Migrationsskript `scripts/migrate_colocate.py`:** CLI; Default **dry-run**
   (druckt geplante Moves), `--apply` führt aus. Argumente `--transcripts DIR
   --recordings DIR`, Defaults auf die bekannten Pfade.
   - **Zuordnung (R1 #8):** primär über das validierte `audio_path`-Feld der
     `.review.json` (existiert die Aufnahme dort, gehört die ganze Output-Familie —
     gleicher Stem wie die Review — dorthin, auch `_1`-nummerierte Basenames). Nur
     Familien OHNE Review fallen auf exakten Stem-Match zurück; mehrdeutige Treffer
     (mehrere Audios gleichen Stems) werden als Konflikt gelistet und übersprungen.
   - **Transaktional pro Familie (R1 #7, R2 #5/#6):** erst alle Quellen/Ziele/Kollisionen
     der kompletten Familie prüfen; jede Kollision → ganze Familie skippen (gelistet).
     - **Nummerierte Altbestände:** die Familie wird beim Move auf den **exakten
       Audio-Stem umbenannt** (`session_1.review.json` → `session.review.json`), sonst
       bricht die Paarungs-Invariante. Existieren mehrere Generationen zum selben Audio,
       gewinnt die mit der jüngsten Review-mtime; übrige Generationen werden als
       Konflikte gelistet und nicht angefasst.
     - **Copy-verify-delete, gestuft (R3 #11, R4 #7/#8/#9):** in UUID-tmp-Dateien AM
       ZIEL kopieren, fsync, **SHA-256** Quelle↔tmp vergleichen. Die Review wird BEREITS
       IM ZIEL-TMP normalisiert (`audio_path` = neuer Nachbarpfad, `base_name` = exakter
       Audio-Stem, R3 #8/R4 #7) — publiziert wird nie ein intern veralteter Zustand.
       Dann alle tmp per `os.replace` publizieren; Quelldateien erst löschen, wenn die
       GANZE Familie verifiziert publiziert ist.
       **Explizit KEIN Ziel-Rollback — resumierbare Migration (R4 #9):** Abbruch lässt
       Quellen intakt (Copy-first); erneuter Lauf setzt fort. Done-Erkennung pro Datei:
       Ziel identisch mit Quelle (SHA-256) — für die Review gegen die **normalisierten
       Erwartungs-Bytes** verglichen (R4 #8) — sonst Konflikt. Report weist teilweise
       migrierte Familien als „fortgesetzt" aus.
       **Quell-Löschreihenfolge (R5 #2):** die Quell-Review wird als LETZTE gelöscht —
       sie ist der Resume-Anker für `_1`-Familien (ohne sie fände der Stem-Fallback die
       umbenannten Geschwister nicht mehr). Crash-Resume-Test nach jeder einzelnen
       Quell-Löschung.
     - **Pfad-Constraint (R3 #9):** `audio_path` aus der Review wird resolved und MUSS
       strikt unterhalb des resolved `--recordings`-Roots liegen und eine unterstützte
       Audiodatei sein; Symlink-Escapes und Fremdpfade → Konfliktliste, keine Migration.
   - `<stem>.markers.json` (BoRT-Auto-Marker) wird mitmigriert; die BoR-Sidecar
     `<stem>.json` liegt bereits am Ziel und wird NIE angefasst.

### Teil C — Bibliotheks-View

6. **Sidecar-Reader (neues Modul `sidecar.py`):**
   `read_recording_meta(json_path, audio_name) -> RecordingMeta | None` mit
   `{started_at, duration_ms, marker_count, peaks, warnings}`.
   - **Nur die exakte BoR-Sidecar** `<audio.stem>.json`; Validierung `file == audio.name`,
     sonst `None`. KEIN Fallback auf `.markers.json` (R1 #11).
   - **Strikte Wert-Validierung (R1 #12):** Datei > 2 MB → ablehnen; `peaks` nur endliche
     Zahlen, geclampt auf [0,1], max. 1000 Einträge (Rest verworfen); `durationMs` endlich,
     0 ≤ x ≤ 24 h, sonst 0; `startedAt` ISO-Parse best-effort sonst None; ungültige
     Marker-Einträge einzeln verwerfen. Jede Verwerfung erzeugt einen `warnings`-Eintrag.
   - **Beobachtbarkeit (R1 #19):** Parse-/Validierungsfehler werden mit Pfad + Grund über
     `logging` protokolliert; der Rückgabewert trägt die Warnungen für die Scan-Aggregation.
   - Pure Funktion, pytest-getestet (fehlend, leer, halbes JSON, Müll-Typen, NaN/Inf,
     Riesenliste, 104er-Normalfall, `file`-Mismatch).
7. **Bridge `scan_library()`:** scannt den konfigurierten Bibliotheks-Ordner (eigener
   Picker `pick_library_dir`, Persistenz `last_library_dir`, Default = Batch-Sync-Ordner)
   über Root + direkte Unterordner (Tiefe 1, keine Symlink-Verzeichnisse) nach
   unterstützten Audios.
   - **Harte Scan-Grenzen (R1 #15):** max. 5000 untersuchte Verzeichniseinträge, max.
     500 Ergebnis-Items, Sidecar-Größenlimit aus Schritt 6; Rückgabe enthält
     `{items, scanned, truncated, warning_count}` — das UI zeigt Trunkierung und
     Warnungsanzahl an.
   - Pro Audio: `{item_id (opak, pro Scan neu), name, folder, duration_ms, started_at,
     marker_count, peaks34, formats_present, has_review}`. `formats_present` statt eines
     einzelnen Bits (R1 #18-Basis).
   - **`peaks34` (R1 #13):** `resample_peaks(peaks, 34)` liefert für JEDE nichtleere
     Eingabe exakt 34 Werte — Downsampling per max-Bucket, Upsampling per
     Nearest-Neighbor-Wiederholung, keine Renormalisierung; leere Eingabe → `[]`.
     Referenzvektoren im Test (104→34, 34→34, 5→34, 200→34).
   - **Sortierung (R1 #14, R2 #10):** rein numerischer Sortschlüssel pro Item:
     `started_at` → UTC-Epoch (naive Zeiten als lokale Zeit interpretiert), ungültig/None
     → Audio-mtime als Fallback-Epoch; Sekundärschlüssel Name. Absteigend. Kein
     datetime-Vergleich gemischter Awareness (nur floats).
   - **Top-500 statt Erste-500 (R2 #9):** der Scan untersucht bis zum 5000-Eintrag-Cap
     ALLE Kandidaten und hält dabei eine begrenzte Top-500-Auswahl nach dem finalen
     Sortschlüssel (heapq.nlargest) — das Cap liefert die neuesten, nicht die zufällig
     zuerst gefundenen.
   - **Scan-Generation (R1 #16):** jede `scan_library`-Antwort trägt eine Generation;
     `item_id → Pfade`-Map wird unter `_state_lock` atomar ersetzt. Aktionen validieren
     Generation + Datei-Existenz + Zugehörigkeit zum Bibliotheks-Root und antworten sonst
     mit „Bitte neu scannen".
8. **Bridge-Aktionen:**
   - `open_library_review(item_id)`: lädt `<stem>.review.json` über den aus
     `pick_review_file` extrahierten gemeinsamen Helfer `_register_review_from_path(path)`
     (Refactor: Dialog-Teil und Lade-Teil trennen; identisches Response-Format).
   - `prepare_library_transcription(item_id)`: setzt Audio- (und falls vorhanden Marker-)
     Pfad in den Bridge-State (`_paths`) und liefert beide als Strings zurück (gleiches
     Muster wie `pick_audio`; `initial_state` liefert `_paths` ohnehin ans JS — die
     frühere „kein Pfad-Leak"-Behauptung ist gestrichen, R1 #17). Frontend füllt das
     Formular und wechselt in den Transkribieren-Tab. KEIN Autostart (v1 schlank).
   - **„Transkribieren"-Button ist IMMER sichtbar** (R1 #18): auch bei vorhandenen
     Outputs (Reparatur/Format-Nachzug); Badges zeigen `formats_present` und Review-Status.
9. **Frontend:** vierter Nav-Eintrag „Bibliothek" (Icon: Ordner/Regal-SVG) zwischen Batch
   und Sprecher. View: Ordnerzeile (Pfad + „Wählen" + „Scannen"), Liste als Cards im
   bestehenden Neon-Stil: Mini-Waveform-Canvas (34 Balken, globaler Gradient
   cyan→violett analog BoR-Look), Name, Datum/Dauer (`durationMs` formatiert), Badges
   `formats_present`-Badges + „Review ✓ / ⚑ n Marker", Buttons „Review öffnen" (nur wenn
   Review vorhanden) / „Transkribieren" (**immer sichtbar**, R2 #8). Klick „Review öffnen"
   wechselt in die Sprecher-View mit geladenem Review. Leere/fehlende `peaks` → flacher Platzhalterbalken.
   Mini-Waveform-Zeichnung als kleine pure Helper in `wave_math.js`
   (`resamplePeaks(peaks, n)`), node-getestet; Canvas-Loop in `app.js`.

### Teil A — BoR-Peaks als Sofort-Waveform (Sprecher-View)

10. `pick_review_file`/`_register_review_from_path`-Response erhält zusätzlich
    `sidecar_peaks` (Liste oder `[]`) UND `sidecar_duration_ms`: Backend liest die exakte
    BoR-Sidecar `<audio.stem>.json` neben `review.audio_path` via Reader aus Schritt 6
    (inkl. `file`-Validierung, kein `.markers.json`-Fallback — R1 #11).
11. Frontend (R1 #10): Sidecar-Renderpfad DARF vor `loadedmetadata` zeichnen — als
    Zeitachse dient `sidecar_duration_ms/1000` (nur wenn > 0, sonst kein Sofort-Render);
    Peaks symmetrisch gespiegelt (`[[-p, p]]`), `waveformResult.source = 'sidecar'`.
    Das bestehende Readiness-Gate gilt weiter für den ffmpeg-Pfad; sobald
    `loadedmetadata` da ist, wird auf `audio.duration` umgezogen (Overlays/Seeking
    unverändert Media-Autorität), und sobald `get_waveform` eintrifft, ersetzt
    `source: 'ffmpeg'` das Sidecar-Rendering endgültig. Stale-Guards unverändert.
    Fehlt die Sidecar oder ist die Dauer 0 → exakt heutiges Verhalten.

### Verifikation

- pytest: Sidecar-Reader (Fälle aus Schritt 6), `scan_pending` (Tagesordner-Rekursion,
  Artefakt-Vollständigkeit via `expected_artifacts`, Symlink-Skip),
  **Transaktions-Fault-Injection (R3 #12):** Fehler je Phase (tmp-Schreiben,
  Backup-Anlage, mitten im Publish), Crash-Recovery aus hinterlassenem Manifest
  (inkl. Rollback neuer Dateien ohne Vorgänger und Restore trotz existierendem Ziel),
  verwaiste Alt-Backups bleiben unangetastet; Scan/Start-Fingerprint-Mismatch;
  `resample_peaks`-Referenzvektoren, `scan_library` (tmp-Baum, Caps, Top-500-Auswahl,
  Generation-Invalidierung), `save_output_options` + `colocate`.
  Migration (R1 #20): Match via `audio_path`, nummerierte Altoutputs, Teilkollision in
  Familie (ganze Familie geskippt), **Abbruch mitten in der Publikation → Resume beim
  nächsten Lauf, Quellen bis Familien-Publish intakt (R5 #3)**, Crash nach jeder
  einzelnen Quell-Löschung → Resume via zuletzt gelöschter Review (R5 #2), dry-run
  ändert nichts, apply idempotent bei Wiederholung, ungültige Review-JSON →
  Konfliktliste; Recovery-Konflikt bei extern verändertem Ziel (Hash-Mismatch) lässt
  Datei unangetastet (R5 #1).
  node: `resamplePeaks`-Spiegelung der Python-Referenzvektoren.
- Manuell (Checkliste): Batch-Lauf schreibt neben m4a; Re-Scan zeigt nichts Ausstehendes;
  Bibliothek listet Aufnahmen mit Waveform-Preview; „Review öffnen" landet korrekt in der
  Sprecher-View; Sofort-Waveform erscheint vor den ffmpeg-Peaks; Migration dry-run/apply
  auf Kopie des echten Bestands.

## Key decisions & tradeoffs

- **Colocate über `overwrite=True` + Audio-Stem:** bewusster Verzicht auf Unique-Suffixe —
  Stem-Gleichheit ist die Paarungs-Invariante für Batch-Skip, Bibliothek und BoR-Sync.
  Re-Transkription überschreibt alte Outputs desselben Audios (gewollt).
- **Sync-Ordner wird beschrieben:** Syncthing trägt Transkripte aufs Handy zurück —
  von Matthias abgenickt (Grill-Frage 1).
- **`peaks34` im Backend, Resampling-Helfer trotzdem im Frontend:** Listen-Payload klein
  halten (500 × 34 Floats), aber `resamplePeaks` als pure JS-Funktion für die
  Sprecher-View-Sofort-Waveform wiederverwendbar und node-testbar.
- **Kein Autostart bei „Transkribieren" aus der Bibliothek:** v1 schlank (Grill-Frage 3);
  Formular füllen + View-Wechsel reicht und nutzt die bestehende Validierung.
- **Migration als Skript, nicht als UI:** einmaliger Vorgang mit dry-run (Grill-Frage 2);
  UI-Einbau wäre Scope-Creep.
- **`item_id` opak wie `review_id`** — als Handle mit Scan-Generation, nicht als
  Security-Feature (Pfade erreichen das JS ohnehin über `initial_state`).
- **mtime bleibt Aktualitätskriterium (R1 #6 teilweise abgelehnt):** eine
  Completion-Metadatei neben der m4a würde in den Sync wandern und den Ordner
  zumüllen. Risiko (Uhr-Drift maskiert neue Audiofassung) akzeptiert — BoR-Aufnahmen
  werden nach dem Sync nicht neu geschrieben, und der immer sichtbare
  „Transkribieren"-Button in der Bibliothek ist der manuelle Ausweg. Begründung geloggt.
- **Rename bei BoR-Reviews deaktiviert statt Familien-Rename:** in die BoR-Sidecar
  schreiben ist out of scope (Android-Schema-Hoheit liegt bei BoR); ein halber Rename
  wäre schlimmer als keiner.

## Risks / open questions

- Sehr große Bibliotheken (>500): Cap + Hinweis; Pagination erst bei Bedarf.
- BoR-Sidecar kann während des Scans vom Sync halb geschrieben sein → Reader fängt
  JSON-/Validierungsfehler ab und liefert `None` (R2 #11, ein Verhalten überall):
  die Aufnahme erscheint in der Bibliothek ohne Preview/Metadaten, der Fehler wird
  geloggt und zählt in `warning_count`; Fallback-Rendering ist getestet.
- `markers.json`-Altlasten (`auto_markers`-Outputs) heißen `<stem>.markers.json` — Migration
  und Bibliothek dürfen sie nicht mit der BoR-Sidecar (`<stem>.json`) verwechseln.
- Duplikat-Stems über mehrere Tagesordner: `item_id` pro Pfad, Anzeige mit Ordner-Kontext;
  Migration behandelt Mehrdeutigkeit als Skip.

## Out of scope

- Suche/Filter/Sortierung/Player in der Bibliothek (v2).
- Kein Löschen/Verschieben von Aufnahmen aus der Bibliothek.
- Keine Änderungen am BoR-Android-Schema; kein Rückschreiben in die BoR-Sidecar.
- Kein Autostart der Transkription aus der Bibliothek.
- Kein Umbau des bestehenden Nicht-colocate-Modus (bleibt als Checkbox-Aus-Fall voll erhalten).

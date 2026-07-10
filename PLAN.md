# Plan: BoRT UI-Redesign → Neumorphism (pywebview + HTML/CSS)
_Locked via grill — by Claude + Matthias (2026-07-10), hardened through Codex adversarial review.
Supersedes the earlier batch-handoff PLAN.md (already built & committed); its history remains in git._

## Goal
Ersetze BoRTs Tkinter/customtkinter-Oberfläche durch eine pywebview-basierte Single-Window-App im
Neumorphism-Stil (dunkelgrau + weiß + kühl-blauer Akzent). Die drei bisherigen Fenster
(Transkribieren, Speaker-Manager, Batch) werden zu drei Views EINES Fensters (SPA-Routing). Zusätzlich
das „Vorschau"-Feature: zeigt das fertige Transkript ausschließlich NACH erfolgreicher Transkription.

**Kernkorrektur nach Codex-Review:** Die bisherige Behauptung „nur View-Schicht wird ersetzt, Backend
bleibt unangetastet" war ungenau. Die drei _View-Dateien_ (`gui.py`, `speaker_manager.py`,
`batch_window.py`) enthalten erhebliche NICHT-View-Logik (Job-Steuerung, Validierung, Params-Bau,
Job-Lock, `AudioPlayer`, Rename-Algorithmus, `transcription_worker`). Diese muss zuerst in
UI-unabhängige Controller-/Service-Module extrahiert werden — mit weiterlaufender alter Tk-UI —, bevor
die neue UI gebaut wird. Erst so ist der Rewrite risikoarm und testbar.

## Verifizierte Rahmenbedingungen (empirisch geprüft, nicht angenommen)
- BoRT-venv ist **Python 3.14.6**. `pywebview` + `pycairo` + `PyGObject` + `WebKit2 4.1` **importieren
  und laufen auf 3.14.6** (in frischer uv-venv getestet) — kein Version-Showstopper.
- pywebview rendert auf dieser KDE-Wayland/NVIDIA-5090-Kiste NUR mit **`GDK_BACKEND=x11`** (XWayland).
  Ohne: Black-Window (Prozess läuft, rendert nichts) — per screenshot­verifiziertem Probe-Fenster
  bestätigt. Zusätzlich `WEBKIT_DISABLE_DMABUF_RENDERER=1` + `WEBKIT_DISABLE_COMPOSITING_MODE=1` als
  Gürtel-und-Hosenträger.
- Launcher-Realität: `launch.sh` (PyInstaller-Binary `dist/bort/bort` + Tk-XCB-`LD_PRELOAD`-Shim) UND
  `run-gui.sh` (venv → `bort-gui`) existieren. `~/Desktop/bort.desktop` (Exec=`launch.sh`) existiert
  **außerhalb des Repos** (daher im read-only Repo-Scan unsichtbar). `__main__.py`/`bort-gui`-Script
  zeigen auf `bort.gui:main`.
- Transkripte sind lang: reale Meetings ergeben **~370–450 Segmente** → Vorschau-DOM muss dafür
  ausgelegt sein.

## Cross-cutting Design-Regeln (gelten für ALLE Bridge/Frontend-Arbeit)
1. **Thread-Sicherheit:** `js_api`-Methoden laufen auf separaten Threads und sind NICHT thread-safe.
   Controller-State + `Config`-Writes werden mit einem echten `threading.Lock` geschützt; gleichzeitige
   `start_transcription`/`process_all` liefern einen strukturierten „busy"-Fehler (kein bloßes Boolean).
2. **Python→JS-Push nur über die GTK-Mainloop, gebündelt/beschränkt:** Progress/Done/Log werden aus dem
   Worker-Thread NICHT direkt gepusht, sondern in eine Queue gelegt und via `GLib.idle_add` (GTK-Mainloop)
   gedrained. Der Push nutzt `window.run_js` (nicht `evaluate_js`, siehe Regel 5). **Queue-Semantik:** pro
   Job wird nur das JÜNGSTE Progress-Event gehalten (coalescing), Logs sind größenbeschränkt, Events für
   inaktive/geschlossene Job-IDs werden verworfen — verhindert GTK-Backlog bei langen Läufen / nach
   Route-Wechsel. Erst pushen nach beidseitigem Readiness-Gate (Regel 6).
3. **Kein String-Interpolieren in JS/HTML — niemals:** Alle Backend-Werte (Transkripttext, Logs,
   Dateinamen, Sprechernamen, Review-Text, Batch-Status) gehen als `json.dumps`-serialisierte Daten an
   JS und werden ausschließlich per `textContent` / DOM-Node-Bau gerendert (nie `innerHTML` mit
   Backend-Daten). Dataclasses werden vorher in JSON-sichere Dicts umgewandelt. Verhindert
   Escaping-Bugs UND JS-Injection.
4. **Autoritativer State bleibt in Python:** Von JS gelieferte Pfade/Zahlen sind untrusted. Ausgewählte
   Audio-/Marker-/Output-Pfade und geladene Review-Daten werden Python-seitig gehalten und über
   opake **Job-IDs / Review-IDs** referenziert. **JS bekommt NIE eine pfad-annehmende Methode** — z.B.
   lädt+registriert `pick_review_file()` die Review komplett in Python und gibt nur `review_id` +
   JSON-sichere Anzeigedaten zurück (kein `load_review_data(path)`). Bridge-Methoden validieren
   Pfade/Typen/Wertebereiche (z.B. Playback `0 <= start < end`) serverseitig und weisen Aufrufe außerhalb
   des aktiven Job-/Review-Kontexts ab.
5. **WebView-Sicherheit + CSP-vs-eval-Konflikt:** strikte CSP (kein Remote-Navigieren, keine externen
   Ressourcen, kein `file://`-Zugriff aus JS); pywebview bedient lokale relative Assets selbst (kein
   `http_server=True`). **Achtung:** `window.evaluate_js` ist `eval`-basiert und kollidiert mit einer
   strikten CSP (`unsafe-eval`). Daher: Push über `window.run_js` (führt Skript ohne `eval`-Rückgabe aus)
   ODER, falls doch `evaluate_js` nötig, die minimale CSP-Ausnahme explizit testen+dokumentieren — NIE
   still `unsafe-eval` hinzufügen.
6. **Beidseitiges Readiness-Gate + Handshake:** Python pusht erst nach `window.events.loaded`. JS ruft
   `pywebview.api.*` erst nach `window.pywebviewready`-Event. Initialer State (Config, letzte Pfade) wird
   über einen definierten Handshake (JS fordert nach `pywebviewready` an, Python antwortet) übertragen,
   nicht über einen ungetakteten frühen Push.
7. **Native GTK-Dialoge laufen auf der GTK-Mainloop:** `window.create_file_dialog(...)` wird aus einer
   `js_api`-Worker-Thread-Methode über die GTK-Mainloop ausgeführt (nicht direkt im Worker-Thread);
   Rückgabe `tuple | None` normalisiert. Teil des On-Target-Dialog-Smoke-Tests. **Deadlock-Vermeidung:**
   der Mainloop-Handoff wartet NIE, während der Controller-/Config-Lock gehalten wird (sonst kann ein
   Dialog-Callback den `js_api`-Request-Thread verklemmen) — Lock vor dem Dialog freigeben.
8. **Ein fester JS-Dispatcher für Push:** alle `run_js`-Pushes gehen durch EINE feste JS-Dispatcher-Funktion
   mit JSON als einzigem variablem Input (z.B. `__bortDispatch(<json>)`), nicht durch pro-Call-Site
   zusammengebaute Skript-Snippets — hält die Injection-Angriffsfläche minimal und die Push-Semantik
   einheitlich.

## Approach (phasiert — alte UI bleibt lauffähig, bis die neue verifiziert ist)

### Phase 0 — Controller/Service-Extraktion (kein UI-Wechsel, alte Tk-UI bleibt aktiv)
Ziel: die UI-unabhängige Logik aus den drei View-Dateien in testbare Module ziehen, die BESTEHENDE
Tk-UI darauf umstellen, alle 46 bestehenden Tests grün halten. De-risking-Fundament.

**Feature-Parität-Checkliste (Phase 0 muss JEDE bestehende Option abdecken, mit Akzeptanztests):**
Backend-/Modell-Wahl, Sprache/Task, min/max Sprecher, no-diarize, auto-markers, Ausgabeformate,
keep-WAV, verbose, Companion-Marker-Auto-Load, persistierte Config (`last_*`-Keys inkl. neu
`last_review_dir`/`last_watch_dir`), Ausgabeordner-Öffnen. Für jede dieser Optionen + jedes
Persistenz-Verhalten ein Controller-/Akzeptanztest — die bestehenden 46 Tests decken das meiste davon
NICHT ab.

1. `controller/jobs.py` — `TranscriptionParams`, `transcription_worker`, Validierungs-/Params-Bau als
   **reine Funktion** `build_params(settings: TranscriptionSettings) -> ParamsResult` (nimmt ein typisiertes
   Settings-Objekt statt CTk-Variablen zu lesen; gibt ein strukturiertes Ergebnis mit Fehlerliste zurück
   statt Tk-Dialoge zu öffnen — Widget-/Dialog-Besitz bleibt bei der jeweiligen UI-Schicht). Job-Lock
   (echter `threading.Lock`), Progress-Callback-Abstraktion (UI-agnostisch, injiziertes `emit(event)`
   statt Tk-Queue).
2. `controller/playback.py` — `AudioPlayer` (ffplay-State-Machine) 1:1 aus `speaker_manager.py`, plus
   `start < end`-Validierung und „ffplay fehlt"-Fehlerpfad.
3. `controller/speaker_edit.py` — Rename/Rewrite-Algorithmus (Rename-Map → `write_outputs(overwrite=True,
   review_data=...)`), Erhalt von bookmarks/markers/output-location/unique-basename/formats/overwrite;
   arbeitet gegen eine per Review-ID gehaltene, validierte Review-Datenstruktur.
4. `controller/batch.py` (dünn) — kapselt die bestehende `batch.scan_pending`/`is_file_stable`-Nutzung
   plus die verbatim erhaltenen Batch-Semantiken: Pre-Item-Stabilitäts-Recheck (Audio+Marker),
   Per-Item-Erfolg/Fehler/Übersprungen-Zählung, garantierte Lock-Freigabe (try/finally), kooperativer
   „nach aktuellem Item"-Abbruch, Stale-Scan-/Doppelklick-Schutz.
5. Bestehende Tk-`gui.py`/`speaker_manager.py`/`batch_window.py` auf diese Controller umstellen (View
   ruft nur noch Controller). **Neue Unit-Tests** für jeden Controller (Job-Lock unter Nebenläufigkeit,
   Playback-Bounds, Rename-Map-Anwendung inkl. leere Namen/Duplikat-Anzeigenamen/fehlende Speaker-ID/
   wiederholtes Anwenden, Batch-Zählung/Cancel/Lock-Freigabe, sowie die Feature-Parität-Checkliste oben).
   `pytest` bleibt grün. **Abschluss-Gate Phase 0:** manueller Tk-Regressionslauf (alte UI startet, alle
   drei Fenster funktionieren wie zuvor) BEVOR Phase 1 beginnt — „46 Tests grün" allein reicht nicht.

### Phase 1 — pywebview-Shell + Bridge + EIN View (Transcribe), hinter Launcher-Flag
6. Deps: `pywebview`, `pycairo`, `PyGObject` in `pyproject.toml` (Runtime). `uv.lock` regenerieren.
   Import-Smoke belegt `uv run python -c "import webview, gi"` auf der Zielkiste.
7. `src/bort/web/` (vanilla, kein Build): `index.html` (SPA-Grundgerüst, 3 `<section>`-Views),
   `style.css` (Neumorphism-Design-System, CSS-Variablen), `app.js` (Routing + Bridge-Calls +
   Push-Callbacks). Als **Package-Data** deklariert; Python löst Pfade über `importlib.resources.as_file`
   auf — der `as_file`-Context wird für die GESAMTE Fensterlebensdauer offen gehalten (nicht nur beim
   URL-Bau), damit Assets auch bei nicht-Dateisystem-Package-Repräsentation verfügbar bleiben.
8. `src/bort/app.py` — `webview.create_window(url=<index via as_file>)`, `Bridge`-Klasse als `js_api`.
   Native Dialoge über `window.create_file_dialog(...)` auf der GTK-Mainloop (Regel 7) — Rückgabe
   `tuple | None` normalisiert; GTK-Filter-Syntax (nicht Tk-Tupel) definiert + getestet;
   Last-Directory-Fallback. Review-Auswahl über `pick_review_file()` (lädt+registriert in Python → nur
   `review_id` zurück, Regel 4). Transcribe-View voll funktional inkl. Vorschau (Phase-1-Abschluss).
9. Vorschau: `#preview` `hidden` per Default, befüllt erst durch `onTranscribeDone(<JSON-Segmente>)`.
   Für lange Transkripte (~450 Segmente) **virtualisiert/paginiert** gerendert, per `textContent`; wird
   bei Job-Start geleert; Output-Pfade werden erst nach erfolgreichem `write_outputs` angezeigt.
10. Launcher (Phase-1, additiv): neues `run-webui.sh` setzt `GDK_BACKEND=x11` + `WEBKIT_*`-Vars **vor**
    dem Python-Start und ruft **`uv run python -m bort.app`** direkt auf (NICHT `python -m bort --ui=web`
    — das würde vom bestehenden `__main__.py` als CLI-Eingabe fehlinterpretiert; die `__main__`-Dispatch-
    Änderung kommt erst in Phase 3). Alte Tk-Launcher bleiben unverändert lauffähig. **On-Target-Smoke**
    (real, nicht nur Import): Fenster öffnet, rendert, Resize + Scrollen eines langen Transkripts +
    Hintergrund-Progress + Dialog-Abbruch funktionieren.

### Phase 2 — Speaker-Edit- + Batch-View
11. Speaker-Edit-View: Review über `pick_review_file() -> review_id + JSON-sichere Anzeigedaten` (Python
    lädt+registriert, Regel 4). Rename-Felder + „Abspielen" pro Sprecher (`play_segment(review_id,
    speaker_id)` → Controller-Playback, serverseitig validiert), „Anwenden"
    (`apply_speaker_rename(review_id, rename_map)` — akzeptiert NUR `{speaker_id: new_name}` für die
    registrierte Review; Controller wendet die validierte Map an). Getestet: leere Namen,
    Duplikat-Anzeigenamen, fehlende Speaker-IDs, wiederholtes Anwenden. Playback stoppt bei
    Route-/Fensterwechsel.
12. Batch-View: Sync-Ordner wählen → `scan()` → Liste → „Alle verarbeiten" (Controller-Batch, Job-State-
    Machine mit Batch-ID) → Per-Item-Outcomes + Erfolg/Fehler/Übersprungen. Verhalten für Stale-Scan,
    ungültige aktuelle Settings, Doppelklick, Fenster-Schließen, Abbruch-während-Subprozess ist explizit
    definiert (übernimmt die Phase-0-Semantik verbatim).

### Phase 3 — Umschalten + Alt-Code entfernen
13. `launch.sh` wird zum kanonischen Webui-Launcher umgeschrieben: `uv run python -m bort` mit
    `GDK_BACKEND=x11` + `WEBKIT_*` vor Python; **Tk-XCB-`LD_PRELOAD`-Shim entfernt** (Tk-spezifisch,
    für WebKit unnötig/potenziell schädlich). `run-gui.sh` entweder entfernt oder auf Webui gezeigt.
    `~/Desktop/bort.desktop` bleibt auf `launch.sh` (außerhalb Repo, keine Änderung nötig).
    **Entry-Points atomar + CLI-Vertrag erhalten:** `bort = bort.cli:main` bleibt UNVERÄNDERT (CLI-Vertrag
    nicht anfassen); nur der GUI-Entry-Point (`bort-gui`) und das argumentlose `__main__.py`-Verhalten
    zeigen auf `app.main()`; `__main__.py` mit Argumenten dispatcht weiter an `bort.cli`. Launch-Smoke-Test.
14. Erst NACH bestandenem On-Target-Smoke aller drei Views: `gui.py`, `speaker_manager.py`,
    `batch_window.py`, `theme.py`, `filedialogs.py`, `dialogs.py` + PyInstaller (`bort.spec`, `dist/`)
    entfernen. customtkinter aus Runtime-Deps streichen.

### Design-System (Neumorphism dunkel)
Basis-BG dunkelgrau (~`#2b2d31`); raised = gleicher BG + Dual-`box-shadow` (dunkel unten-rechts
~`#1e1f22`, hell oben-links ~`#383a3f`); gedrückt/aktiv = `inset`-Schatten; Text weiß/hellgrau; EIN
kühl-blauer Akzent (~`#5b9bd5`, gedämpft) für Primär-Button/Fortschritt/aktive States. Dunkles
Neumorphism hat subtile Kontraste — Schattenwerte werden visuell iteriert.

## Key decisions & tradeoffs
- **Controller-First-Phasierung statt direktem UI-Rewrite:** die drei View-Dateien enthalten
  Nicht-View-Logik; erst extrahieren (alte UI läuft weiter, Tests grün), dann neue UI. Reduziert Risiko,
  macht die neue Bridge dünn. Preis: mehr Phasen, aber jede Phase ist für sich lauffähig/verifizierbar.
- **pywebview + HTML/CSS statt Pillow-Schatten / Soft-Flat / GTK-CSS:** Nutzer will Mockup-Look pixelnah;
  CSS macht Neumorphism trivial. Preis: WebKitGTK-Laufzeit + Wayland/NVIDIA-Workaround + JS-Bridge-Disziplin.
- **Ein Fenster / drei Views (SPA):** konsistente „eine App", vermeidet pywebview↔Tk-Koexistenz. Preis:
  alle drei Views müssen portiert werden.
- **uv-run statt PyInstaller:** eliminiert WebKitGTK-Bündel-Risiko. Preis: `uv`+`.venv` zum Start (für
  Single-User-lokal irrelevant).
- **Vorschau erst am Ende, kein Live-Streaming; keine Wellenform; kühl-blauer Akzent statt Korallenrot:**
  Nutzer-Entscheidungen.
- **Backend-Module (`audio/batch/config/markers/speaker_review/speakers/streaming/transcription/`
  `whisperx_backend/writers`) bleiben unangetastet** — nur aufgerufen. Blast-Radius = View + neue
  Controller-Schicht.

## Risks / open questions
- WebKitGTK unter Last/Resize/langen DOMs: mit statischem Probe-Fenster verifiziert, nicht mit der echten
  App → Phase-1-On-Target-Smoke ist Pflicht-Gate vor Phase 2/3.
- `GLib.idle_add`-Dispatch + Readiness-Gate müssen korrekt sitzen, sonst verlorene/doppelte
  Progress-Events oder Crash bei geschlossenem Fenster.
- ffplay-Playback unter XWayland: unabhängig vom WebView, sollte unkritisch sein — im Smoke bestätigen.
- Dark-Neumorphism-Kontrast: subtil, braucht visuelle Iteration; schlecht getunt wirkt flach.
- uv-run-Startzeit minimal höher als PyInstaller-Binary — voraussichtlich vernachlässigbar.

## Out of scope
- Live-/Streaming-Vorschau; echte Audio-Wellenform; PyInstaller-Bündelung von WebKitGTK.
- Änderungen an Transkriptions-Backend, whisper-tagger, BoR↔BoRT-Handoff.
- Windows/macOS-Portabilität des neuen UI.
- Beibehaltung der BoR-Korallenrot-Marke (bewusst durch Blau ersetzt).
- Codex' Alternativvorschlag „direkte GTK/libadwaita-CSS-UI ohne JS-Bridge" — abgelehnt: trifft den
  gewünschten CSS-Neumorphism-Look weniger genau und ist ein anderer Tech-Stack als vom Nutzer gewählt.

# Plan Review Log: BoRT UI-Redesign → Neumorphism (pywebview)
Act 1 (grill) complete — plan locked with the user via interactive interview (render approach,
window structure, accent colour, preview timing, packaging model, waveform all decided by the user;
pywebview feasibility + the GDK_BACKEND=x11 black-window workaround empirically verified with a real
screenshotted probe window before locking). MAX_ROUNDS=5.
Reviewer model: gpt-5.6-terra (from ~/.codex/config.toml, unpinned) — codex-cli 0.144.1.

(Previous content of this file — the batch-handoff review log — is preserved in git history at the
commits from 2026-07-09/07-10; this file is reused for the new grill cycle per the skill convention.)

## Round 1 — Codex
- gui.py NICHT view-only: besitzt TranscriptionParams, transcription_worker, Logging-Lifecycle, Validierung, Config-Persistenz, Job-Lock; batch_window importiert davon. Löschen bricht Batch.
- speaker_manager.py ebenfalls nicht view-only: AudioPlayer + kompletter Rename/Rewrite-Algorithmus.
- js_api-Methoden laufen auf Threads, nicht thread-safe — Boolean-Job-Lock unzureichend für gleichzeitige start_transcription/process_all + Config-Writes.
- evaluate_js aus Worker-Thread ohne GTK-Mainloop-Dispatch/Readiness-Gate/Cancel-on-close/Serialisierung.
- Interpoliertes evaluate_js("onTranscribeDone(...)") bricht bei Quotes/Newlines + XSS + Dataclasses nicht JSON-serialisierbar.
- Gleiche XSS-Gefahr bei Logs/Dateinamen/Sprechernamen/Review-Text/Batch-Status via innerHTML.
- http_server=True redundant; CSP/Threat-Model fehlt.
- Von JS gelieferte Pfade + Playback-Bounds nicht serverseitig validiert.
- create_file_dialog liefert tuple|None (nicht str); GTK-Filter-Syntax != Tk-Tupel.
- XWayland-Workaround unvollständig: Env-Vars müssen VOR gi/webview-Import gesetzt sein; Launcher heißt run-gui.sh nicht launch.sh; kein bort.desktop im Repo.
- Tk-XCB-LD_PRELOAD-Shim für WebKit-Launcher unbegründet/schädlich.
- PyGObject in .venv nicht garantiert durch System-Install; Python-3.14-Kompatibilität unverifiziert.
- Entry-Points-Regression (uv run python -m bort vs __main__ → bort.gui vs bort-gui-Script).
- Statische web/-Assets nicht als Package-Data deklariert → nicht-editable-Install verliert sie.
- Batch-Vertrag (GUI-Params, Pre-Item-Stabilität, Per-Item-Accounting, Lock-Freigabe) explizit erhalten + testen.
- Speaker-Edit unterspezifiziert (bookmarks/markers/output-location/basename/formats/overwrite); opake Review-ID vorschlagen.
- Playback-State-Machine-Details (Stop-Toggle, Reset nach natürlichem Ende, Serialisierung).
- Vorschau ohne Scale/Error-Policy für lange Aufnahmen; virtualisieren, bei Job-Start leeren.
- Batch ohne definiertes Verhalten für Stale-Scan/Doppelklick/Close/Cancel-während-Subprozess.
- Kein Implementierungs-Testplan für die riskantesten Behauptungen.
- Simplere Route: erst Controller/Services extrahieren, alte GUI weiterlaufen lassen, dann pywebview hinter Launcher-Flag bis On-Target-Smokes bestehen.

VERDICT: REVISE

### Claude's response
Kritik zu ~95% berechtigt und stark. Vor der Revision zwei faktische Punkte empirisch geprüft:
1. BoRT-venv ist Python 3.14.6 (mein erster Smoke-Test war 3.12!). NEU getestet: pywebview+pycairo+
   PyGObject+WebKit2 4.1 importieren+laufen auf 3.14.6 → kein Showstopper.
2. Launcher-Realität: launch.sh (PyInstaller+Tk-Shim) UND run-gui.sh (venv) existieren; bort.desktop
   existiert unter ~/Desktop (AUSSERHALB Repo → Codex' read-only Scan sah sie nicht). __main__→bort.gui.

Übernommen (fast alles):
- NEUE Phase 0 „Controller/Service-Extraktion" vorangestellt: jobs.py/playback.py/speaker_edit.py/
  batch.py aus den View-Dateien ziehen, ALTE Tk-UI darauf umstellen + weiterlaufen lassen, 46 Tests
  grün halten, neue Controller-Unit-Tests. De-risking-Fundament (= Codex' „simplere Route").
- 5 Cross-cutting Design-Regeln fixiert: echter threading.Lock + strukturierte busy-Fehler;
  GLib.idle_add-Dispatch nach window.events.loaded-Gate; json.dumps + textContent überall, nie
  innerHTML mit Backend-Daten; autoritativer State in Python via opake Job-/Review-IDs +
  serverseitige Pfad/Bounds-Validierung; strikte CSP, kein http_server=True.
- create_file_dialog tuple|None + GTK-Filter normalisiert/getestet; Env-Vars VOR Python im Launcher;
  Tk-XCB-Shim aus Webui-Launcher entfernt; Entry-Points atomar umgestellt; web-Assets als Package-Data
  via importlib.resources; Vorschau virtualisiert für ~450 Segmente + bei Job-Start geleert;
  Batch-/Playback-/Speaker-Edit-Semantik verbatim aus Phase 0 übernommen; On-Target-Smoke-Gate vor
  Alt-Code-Löschung.
- Verifizierte Rahmenbedingungen als eigener Abschnitt in PLAN.md dokumentiert.

Abgelehnt: Codex' Alternativ-Stack „direkte GTK/libadwaita-CSS-UI ohne JS-Bridge" — trifft den
gewünschten Neumorphism-CSS-Look weniger genau, anderer Tech-Stack als vom Nutzer gewählt. Als
Out-of-scope dokumentiert.

## Round 2 — Codex
Bestätigt: Controller-First, echte Locks, Mainloop-Dispatch, JSON/DOM-Regeln, Package-Data, phasierte
Launch-Migration, Tk-Shim-Entfernung, On-Target-Gates = substanzielle Verbesserungen. Verbleibend:
- _build_params noch als „UI-unabhängig" bezeichnet, liest aber CTk-Vars + öffnet Tk-Dialoge → typisiertes TranscriptionSettings-Input + strukturiertes Ergebnis.
- Phase 0 ohne Feature-Parität-Checkliste (backend/model/language/task/min-max-speakers/no-diarize/auto-markers/formats/keep-wav/verbose/companion-auto-load/config/output-open) + Tests.
- load_review_data(path) widerspricht Opaque-ID-Regel (JS kann beliebigen Pfad senden) → pick_review_file() lädt+registriert in Python, nur review_id zurück.
- Strikte CSP kollidiert mit evaluate_js (eval-basiert) → window.run_js nutzen oder minimale CSP-Ausnahme testen/dokumentieren, nie still unsafe-eval.
- JS-Readiness-Gate fehlt: muss window.pywebviewready abwarten vor pywebview.api-Aufruf + getakteter Initial-State-Handshake.
- Progress-Dispatch braucht gebündelte/beschränkte Queue (jüngstes Progress pro Job, Logs bounded, Events inaktiver/geschlossener Jobs verwerfen).
- Native GTK-Dialoge aus js_api-Worker-Threads brauchen GUI-Thread-Ausführungsvertrag + Smoke.
- Phase 1 `python -m bort --ui=web` unlaunchbar (bestehendes __main__ behandelt es als CLI) → --ui=web-Dispatch in Phase 1 ODER python -m bort.app direkt.
- Phase 3: `bort`-CLI-Vertrag nicht anfassen — nur GUI-Entry-Points umziehen.
- importlib.resources braucht as_file-Lifetime für ganze Fensterlebensdauer.
- Speaker-Rename braucht ID-basierten Vertrag + Tests (leer/Duplikat/fehlend/wiederholt).
- „46 Tests grün" nicht genug → neue Controller-Tests + manueller Phase-0-Tk-Regressionslauf vor Phase 1.

VERDICT: REVISE

### Claude's response
Alle 12 Punkte übernommen, keine Ablehnung — durchweg berechtigte Verfeinerungen:
- Cross-cutting Regeln erweitert: Regel 2 (run_js statt evaluate_js + coalesced/bounded Queue + Events
  inaktiver Jobs verwerfen), Regel 4 (keine pfad-annehmende JS-Methode; pick_review_file lädt+registriert),
  Regel 5 (CSP-vs-eval explizit: run_js oder dokumentierte Ausnahme, nie still unsafe-eval), Regel 6
  (beidseitiges Readiness-Gate: window.events.loaded + window.pywebviewready + Handshake), Regel 7 (GTK-
  Dialoge auf Mainloop).
- Phase 0: build_params als reine Funktion (TranscriptionSettings-Input, strukturiertes Ergebnis, keine
  Dialoge); Feature-Parität-Checkliste mit Akzeptanztests für jede Option + Persistenz; Phase-0-Gate =
  manueller Tk-Regressionslauf vor Phase 1.
- Phase 1: pick_review_file() statt load_review_data(path); Launcher ruft `uv run python -m bort.app`
  direkt (nicht --ui=web); importlib.resources.as_file für ganze Fensterlebensdauer offen.
- Phase 2: apply_speaker_rename akzeptiert nur {speaker_id: new_name}, Tests für leer/Duplikat/fehlend/
  wiederholt.
- Phase 3: `bort = bort.cli:main` bleibt unverändert, nur bort-gui + argumentloses __main__ → app.main().

## Round 3 — Codex
Plan schließt die materiellen Punkte beider Vorrunden. Phase 0 trennt Controller-Verträge sauber von
Tk-Widgets, erhält CLI, staged Launcher-Migration, spezifiziert die zuvor fehlenden Bridge-/State-/
Security-/Packaging-/Regressionstest-Grenzen. Zwei Punkte als Akzeptanzkriterien (kein Plan-Revise nötig):
- GTK-Dialog-Mainloop-Handoff darf nie warten, während der Controller-/Config-Lock gehalten wird (sonst
  Deadlock des js_api-Request-Threads).
- run_js-Pushes über EINEN festen JS-Dispatcher mit JSON als einzigem variablem Input, keine pro-Call-Site
  zusammengebauten Snippets.
Phase-0-Parität-Gate + Phase-1/2-On-Target-Smoke-Gates sind adäquate Absicherung.

VERDICT: APPROVED

### Claude's response
Beide Akzeptanzkriterien trotzdem eingefaltet (Cross-cutting Regel 7 Deadlock-Vermeidung: Lock vor Dialog
freigeben; neue Regel 8: ein fester __bortDispatch(<json>)-Dispatcher). Plan nach 3 Runden APPROVED.

**Abschluss Act 2:** Konvergiert bei VERDICT: APPROVED in Runde 3 (von 5 max). Runde 1 deckte den
Kern-Denkfehler auf (View-Dateien enthalten Nicht-View-Logik → Controller-First-Phasierung), Runde 2
schärfte Bridge-/Security-/Entry-Point-Details, Runde 3 nur noch zwei Akzeptanzkriterien. Nutzer-Sign-off
ausstehend.

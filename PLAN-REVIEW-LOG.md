# Plan Review Log: BoR ↔ BoRT Handoff-Automatisierung (Batch-Scan)
Act 1 (grill) complete — plan locked with the user (via prior brainstorming session, not a fresh Act-1 interview). MAX_ROUNDS=5.
Reviewer model: gpt-5.6-terra (from ~/.codex/config.toml, unpinned) — codex-cli 0.144.1.

## Round 1 — Codex
- Tk-Thread-Verstoß in `_run_batch()` (Tk-Zugriff im Worker-Thread)
- Kein Job-Lock zwischen Haupt-Run und Batch-Run (GPU-Konflikt möglich)
- Root-Logger wird pro Lauf zerstört (`root.handlers.clear()`)
- `_drain_item_queue()` verwirft log/progress-Nachrichten
- „Bereits verarbeitet"-Check (`rglob(f"{stem}.*")`) zu locker — akzeptiert auch `<stem>.markers.json`
- Fehlschlag nach Auto-Marker-Schreiben wird fälschlich als Erfolg gezählt (Kernbug, direkte Folge des vorigen Punkts)
- Namenskollisionen zwischen Dateien gleichen Stems, unterschiedlicher Endung
- SMB-Teilkopien können verarbeitet werden (keine Stabilitätsprüfung)
- TOCTOU zwischen Scan und Verarbeitung
- Doppel-Verarbeitung bei zweitem Klick auf „Alle verarbeiten" ohne Rescan
- Fenster-Schließen während laufendem Batch nicht sicher
- Speaker-Manager-Nachbearbeitung für Batch+whisperX nicht erreichbar
- Auto-Marker werden bei Wiederholungsläufen überschrieben
- Irreführende Abschlusszahl („N Dateien" ohne Erfolg/Fehler-Aufschlüsselung)
- Fehlende Tests für die kritischen Randfälle
- SMB-Doku ohne Sicherheitsvorgaben (Gastzugriff, ACLs)

VERDICT: REVISE

### Claude's response
Übernommen: Thread-Sicherheit (Params im Main-Thread bauen), Job-Lock, benannter statt Root-Logger,
vollständiges Log-Forwarding, korrekter Verarbeitet-Check (echte Transkript-Endungen, markers.json
ausgeschlossen), Stabilitäts-Check gegen Teilkopien + Re-Check vor Verarbeitung, Pending-Liste nach
Lauf leeren (kein Doppel-Run ohne Rescan), sicheres Schließen mit Abbrechen-Button, getrennte
Erfolg/Fehler/Übersprungen-Zählung, zusätzliche Tests, SMB-Doku mit least-privilege-Hinweisen.

Abgelehnt (dokumentiert statt gebaut): Namenskollision gleicher Stem unterschiedlicher Audio-Endung
(unwahrscheinlich durch BoRs Datums-Zeit-Namenskonvention) — als Risiko vermerkt statt
Hash-Completion-Record gebaut. Persistenter Speaker-Review-Workflow für Batch+whisperX — echte Lücke,
aber neues Feature außerhalb des Scopes, als bekannte Einschränkung dokumentiert. Auto-Marker-
Überschreibung bei Wiederholungsläufen — durch strengeren Verarbeitet-Check jetzt seltener, kein
zusätzlicher Schutz gebaut.

## Round 2 — Codex
- Detaillierter Task-Plan (Code) wurde nicht nachgezogen, nur PLAN.md-Zusammenfassung — Fix: vor Implementierung nachholen.
- Logger-Isolation unterspezifiziert/wirkungslos (bort.worker fängt keine anderen Logger ab).
- Einzelner mtime-Schwellwert (15s) reicht nicht als Stabilitätsnachweis gegen SMB-Teilkopien.
- Stem-Kollision bleibt Datenverlust-Bug, nicht akzeptable Seltenheit.
- Speaker-Manager-Lücke: Dokumentieren allein erfüllt das Ziel (manuelle Nachbearbeitung bleibt möglich) nicht.
- Marker-Recheck vor Verarbeitung nur Existenzprüfung, nicht vollständiges Neu-Parsen.
- Job-Lock braucht explizite Ownership/Cleanup-Regeln für alle Beendigungspfade (Validierungsfehler, Exception, Abbruch, Fenster-Schließen).
- Tests fehlen weiterhin für: Stem-Kollision, Zwei-Sample-Stabilitätscheck, Lock-Freigabe auf jedem Pfad, Speaker-Review-Handoff.

VERDICT: REVISE

### Claude's response
Nutzer-Entscheidung eingeholt zur Speaker-Manager-Frage: nachträgliche Bearbeitung jederzeit gewünscht
(nicht nur direkt nach Lauf). Neuer Baustein entworfen: Review-Sidecar (`{unique_base}.review.json`,
geschrieben von `write_outputs()`) + Reopen-Flow, der die bestehende `SpeakerManagerWindow`
unverändert wiederverwendet. Batch öffnet Speaker-Manager nicht mehr automatisch (bleibt
"weglaufen"-fähig), schreibt aber die Sidecar für jede whisperX-Datei.

Übernommen: Logger-Fix (gezieltes removeHandler statt handlers.clear(), Propagation nutzen statt
neuer Logger-Namespace), Zwei-Sample-Stabilitätscheck (Größe+mtime, Abstand 2s), vollständiges
Marker-Reparsen vor Verarbeitung, zentrale Job-Lock-Freigabe in einer einzigen
Main-Thread-Completion-Routine für alle Beendigungspfade, zusätzliche Tests wie gefordert.

Abgelehnt (mit Begründung): volle Hash-basierte Completion-Identität gegen Stem-Kollision — würde
`base_name = audio_path.stem`-Konvention in `writers.py` ändern, betrifft CLI und Einzel-Lauf-Flow,
keine Batch-lokale Änderung mehr. Stattdessen Mini-Absicherung ergänzt: Output zählt nur als Nachweis,
wenn seine mtime nicht älter ist als die des Audios — deckt den wahrscheinlichen Fall (Aufnahme erneut
committed) ab, nicht aber zwei unabhängige Aufnahmen mit zufällig identischem Stem in derselben Minute
(dokumentiertes Restrisiko).

## Round 3 — Codex
- Task-Plan (Code) wurde erneut nicht aktualisiert — nur PLAN.md, wiederholter Kernvorwurf.
- Review-Sidecar-Typ-Mismatch: rohe `Segment`s gespeichert, `SpeakerManagerWindow` erwartet `SpeakerSegment`s.
- Sidecar fehlte `audio_path` (für Playback zwingend nötig).
- `write_outputs()` würde beim Reopen `_1`-Duplikate statt Overwrite erzeugen (zusätzlich: bereits bestehender Bug beim Live-Rename direkt nach einem Lauf, unabhängig vom Reopen-Feature).
- Keine Atomizitätsregel: Sidecar-Schreibfehler nach Transkript-Erfolg würde Aufnahme als "verarbeitet, aber nicht nachbearbeitbar" hinterlassen.
- Kein Schema/keine Validierung für die Sidecar-Datei.
- Widersprüchliche Altlasten in PLAN.md (alte 15s-Schwelle, alte "nicht erreichbar"-Aussage standen noch neben den neuen, ersetzenden Entscheidungen).
- Fehlende Tests für Sidecar/Reopen: `_1`-Namen, Wiederöffnung, fehlendes Audio, beschädigte Sidecar, Exportfehler.

VERDICT: REVISE

### Claude's response
PLAN.md komplett neu geschrieben (Endzustand statt Patch-Verlauf, Widersprüche entfernt — Verlauf lebt
ausschließlich in dieser Log-Datei). Zusätzlich JETZT den detaillierten Task-Plan
(docs/superpowers/plans/2026-07-09-batch-handoff-automation.md) vollständig überarbeitet und mit
echtem Code synchronisiert:

Übernommen: Sidecar speichert `SpeakerSegment`-kompatible Dicts (nicht rohe Segment), `audio_path`
im Schema ergänzt und beim Reopen auf Existenz geprüft, `write_outputs()` bekommt `overwrite`- und
`review_data`-Parameter (Task 2) — behebt zusätzlich den vorbestehenden `_1`-Duplikat-Bug in
`SpeakerManagerWindow._on_apply` (Task 7), Sidecar-Schreiben ist Teil desselben `write_outputs()`-
Aufrufs wie die Transkripte (Atomizität über den bestehenden Fehlerpfad in `transcription_worker`,
keine neue Infrastruktur), versioniertes Schema + `ReviewError`-Validierung in neuem Modul
`speaker_review.py` (Task 8) mit vollständiger Testabdeckung (fehlende Datei, ungültiges JSON,
fehlendes Pflichtfeld, falsche Version, fehlendes Audio). Neue Tests für `_1`-Vermeidung beim
Overwrite (Task 2), Sidecar-Ausschluss aus `scan_pending` und mtime-Schutz gegen veraltete Outputs
(Task 3).

Keine Ablehnungen in dieser Runde — alle Punkte waren berechtigt und wurden übernommen.

## Round 4 — Codex
- Logger-Fix (Task 5 Text) war nie als konkreter Code-/Test-Schritt im Task-Plan verankert.
- Review-Sidecar behält bei `_1`-Namenskollision fälschlich den alten `base_name` — Reopen würde falsche Datei überschreiben.
- Behauptete Atomizität stimmte nicht: Transkripte wurden vor der Sidecar geschrieben.
- `load_review()` würde bei falschen/fehlenden verschachtelten Feldern rohe KeyError/TypeError werfen statt ReviewError.
- Path-Traversal über manipulierten `base_name` in der Sidecar möglich (Schreiben außerhalb des Zielordners).
- Stabilitäts-Schutz endete nach dem Scan — Audio/Marker konnten sich vor der eigentlichen Verarbeitung noch ändern.
- Marker-Dateien wurden nie auf Kopierstabilität geprüft, nur Audio.
- `_run_batch()` hatte kein äußeres try/finally — eine Exception hätte das Job-Lock dauerhaft belegt.
- Fenster-Schließen während eines laufenden SCANS (nicht nur Batch-Lauf) war ungeschützt.
- Fehlende Tests für all diese Fälle.

VERDICT: REVISE

### Claude's response
Alle Punkte übernommen, keine Ablehnung in dieser Runde:
- Task 5: `_setup_worker_logging`/`transcription_worker` Handler-Lebenszyklus jetzt als konkreter
  Code-Schritt (Step 0/0b) mit Rückgabewert + try/finally-Teardown.
- Task 2: Sidecar wird VOR den Transkripten geschrieben (Atomizität), `base_name` in der Sidecar auf
  den tatsächlich gewählten `unique_base` normalisiert; 2 neue Tests (Kollisionsfall,
  Schreibfehler-verhindert-Transkript).
- Task 8: `load_review()` validiert `base_name` (kein Pfadtrenner/'..') und `formats` (gegen
  `writers.FORMATS`-Whitelist) explizit, wrapped die gesamte verschachtelte Rekonstruktion in
  try/except → einheitlich `ReviewError`; 3 neue Tests (malformed nested, path traversal, unknown
  format).
- Task 10 (`BatchWindow._run_batch`): erneuter Existenz- UND Stabilitäts-Check (Audio + Marker)
  unmittelbar vor jedem Item, komplette Schleife in try/finally gekapselt (garantiert
  `batch_finished` und damit Lock-Freigabe auch bei unerwarteter Exception). `_on_close` blockt jetzt
  auch während eines laufenden Scans, nicht nur während eines Batch-Laufs.

## Round 5 — Codex (MAX_ROUNDS erreicht)
- `write_outputs()`-Codeblock enthielt weiterhin zwei Transkript-Schleifen (Einfüge-/Entfern-Anweisung statt sauberem Endzustand) — widersprach der eigenen "Sidecar zuerst"-Aussage.
- Sidecar-zuerst allein schützt nicht vor Teilerfolg bei mehreren Formaten (TXT ok, CSV scheitert) — scan_pending() hätte die Aufnahme trotzdem als erledigt gesehen.
- `_run_batch()`-try/finally zählte eine unerwartete Exception nicht als Fehler — Zusammenfassung hätte fälschlich 0 Fehler gemeldet.
- `load_review()`: `Path(data["audio_path"])` konnte bei Nicht-String-Wert TypeError werfen; Datei-Lesefehler (OSError) wurden nicht in ReviewError übersetzt.
- Logger-Fix stellte Handler wieder her, aber nicht den vorherigen Root-Log-Level — verbose-Lauf hätte Logging global dauerhaft verändert.

VERDICT: REVISE (5. Runde — MAX_ROUNDS erreicht, Loop endet hier)

### Claude's response
Alle 5 Punkte übernommen, keine Ablehnung:
- `write_outputs()` final auf EINEN sauberen Codeblock reduziert: Format-Validierung vorab, dann
  Sidecar+alle Transkript-Writer in einem try-Block, bei JEDER Exception werden alle in diesem Aufruf
  bereits geschriebenen Dateien wieder gelöscht (alles-oder-nichts, deckt auch Teilerfolg bei
  mehreren Formaten ab, nicht nur Sidecar-vs-Transkript).
- `_run_batch`: pro Item in `_process_one_item()` gekapselt, äußeres try/except pro Item zählt eine
  unerwartete Exception jetzt explizit als "error" statt sie unter den Tisch fallen zu lassen.
- `load_review()`: `audio_path` wird vor `Path(...)`-Konvertierung als nicht-leerer String validiert,
  OSError beim Datei-Lesen wird in ReviewError übersetzt. Neuer Test für Nicht-String-audio_path.
- Logger-Fix: `_setup_worker_logging` gibt jetzt zusätzlich den vorherigen Root-Log-Level zurück,
  `transcription_worker`s finally-Block stellt ihn wieder her.

**Abschluss:** MAX_ROUNDS (5) erreicht mit VERDICT: REVISE. Keine der 5 Runden endete mit
VERDICT: APPROVED — das ist kein Deadlock durch Meinungsverschiedenheit (Claude stimmte in jeder
Runde allen Kernfunden zu), sondern schlicht daran, dass die Aufgabe (Batch-Verarbeitung +
nachträgliche Sprecher-Bearbeitung, thread-sicher, mit Datei-Race-Absicherung) genug Fläche bietet,
dass Codex bei jeder Version noch etwas Neues fand. Nutzer entscheidet nächsten Schritt.

## Act 3 — Build

### Round 1 — Codex build (full write access)
Implementierte alle 12 Tasks aus dem Task-Plan: markers.py-Extraktion, writers.py
overwrite/review_data/Atomizität, batch.py (scan_pending/is_file_stable), gui.py
(_build_params/Job-Lock/Sidecar-Erzeugung/Logger-Fix/Reopen-Button/Batch-Button),
speaker_manager.py (overwrite+Sidecar-Refresh), speaker_review.py (Loader+Validierung),
batch_window.py (Batch-Dialog), HANDOVER.md-Doku. Keine Commits erstellt (wie angewiesen).
Bericht: 46/46 Tests grün, Import-Check ok, keine Abweichungen vom Spec.

### Claude's Verifikation (Runde 1)
Unabhängig nachvollzogen: `git status`/`git diff` gelesen (alle Kern-Dateien: writers.py, gui.py,
speaker_manager.py, batch.py, speaker_review.py, batch_window.py) — Logik deckt sich exakt mit dem
Task-Plan (Sidecar-vor-Transkript-Reihenfolge, Alles-oder-nichts-Cleanup, base_name-Normalisierung,
Job-Lock-Acquire/Release, Re-Stabilitäts-Check pro Item, try/finally in _run_batch, Path-Traversal-
Validierung in load_review). `python -m pytest -v` selbst ausgeführt: 46/46 PASS, bestätigt.

**Aber:** `ruff check` (Projekt hat eigenes ruff-Setup, pyproject.toml) zeigte 210 Fehler gegenüber
202 Baseline-Fehlern vor dem Build — `batch_window.py` allein enthielt ~92 E702
(Semikolon-Statements)/E501 (Zeile-zu-lang)-Verstöße, fast so viele wie der GESAMTE Rest der
bestehenden Codebase zusammen. Dichter, schwer lesbarer Stil, passte nicht zum Rest des Projekts.
Kein Blocker für Korrektheit, aber ein echtes Stil-/Wartbarkeits-Problem für ein Tool, das der Nutzer
von Hand weiterpflegt.

### Round 2 — Codex fix (same session, reformat only)
Angefordert: reine Neuformatierung der von Runde 1 berührten/erstellten Dateien auf normalen
Python-Stil (kein Logik-Change). Bericht: alle 46 Tests weiterhin PASS, `ruff check` auf den
betroffenen Dateien "All checks passed!".

### Claude's Verifikation (Runde 2)
Unabhängig nachvollzogen: `python -m pytest -q` → 46/46 PASS. `ruff check` auf allen geänderten/neuen
Dateien selbst ausgeführt → "All checks passed!", bestätigt. `git diff --stat` zeigt reine
Zeilenumbruch-Änderungen (deutlich mehr Zeilen durch Multi-Line-Formatierung, kein Logik-Drift beim
Gegenlesen von batch_window.py). Fix-Runden verbraucht: 1 von MAX_FIX_ROUNDS=2.

**Ergebnis:** Build + 1 Fix-Runde reichten aus. Kein Takeover durch Claude nötig. Bereit für
Mensch-Freigabe vor Commit.

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

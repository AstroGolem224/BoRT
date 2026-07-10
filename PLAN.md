# Plan: BoR ↔ BoRT Handoff-Automatisierung (Batch-Scan + Speaker-Review)
_Locked via grill — by Claude + Matthias. Act 1 = vorherige Brainstorming-Session
(docs/superpowers/specs/2026-07-09-bor-bort-handoff-automation-design.md). Diese Fassung ist der
Endzustand nach 3 Codex-Review-Runden — Verlauf/Argumentation in PLAN-REVIEW-LOG.md, nicht hier._

## Goal
BookofRecords (Android, "BoR") speichert Aufnahmen (M4A+JSON) aktuell manuell nach Google Drive,
Download+Einzelauswahl in BoRT (Desktop-Transkriber) ist ebenfalls manuell. Ziel: Transfer
automatisieren (Tailscale+SMB als SAF-Ziel auf dem Handy, kein BoR-Code-Change) und Transkription per
Batch-Scan-Button in BoRT statt Einzeldatei-Auswahl, ohne Auto-Trigger (Nutzer startet Batch bewusst).
Sprecher-Umbenennung bleibt manuell, aber jederzeit — auch lange nach einem Batch-Lauf — über einen
Reopen-Flow möglich.

## Approach

1. **Marker-Suche extrahieren** (`src/bort/markers.py`): `_looks_like_marker_file` und neue
   `find_companion_marker(audio_path) -> Path | None` aus `gui.py` herausziehen (DRY),
   `gui.py._auto_load_companion_marker` nutzt sie.

2. **`scan_pending()`** (`src/bort/batch.py`, neu): reine Funktion, findet Audio-Dateien in
   `watch_dir` ohne gültiges Output-Transkript in `output_dir`.
   - Prüft nur echte Transkript-Endungen (`.txt/.md/.csv/.tsv`, aus `writers.FORMATS` abgeleitet),
     ignoriert explizit `*.markers.json` und `*.review.json`.
   - Eine gefundene Ausgabedatei zählt nur als Nachweis, wenn ihre `mtime` nicht älter ist als die
     des Audios (verhindert, dass ein altes Transkript ein später neu eingetroffenes, gleichnamiges
     Audio fälschlich als „erledigt" maskiert).
   - Eine Audiodatei gilt erst als „bereit" (nicht mehr mitten in einer SMB-Teilkopie), wenn zwei
     Beobachtungen von Größe+mtime im Abstand von ca. 2 Sekunden übereinstimmen.
   - Keine State-Datei — Dateisystem ist Wahrheitsquelle. Gibt `PendingItem(audio_path,
     marker_path | None)` zurück, `marker_path` via `find_companion_marker`.

3. **`_build_params()` extrahieren** (`gui.py`): `_validate()` in Validierung (Audio/Marker aus
   Tk-Feldern, nur im Main-Thread aufgerufen) + `_build_params(audio_path, marker_path)` (Rest:
   Backend/Modell/Formate/Sprache/Speaker-Optionen aus aktuellen Haupt-Einstellungen) aufteilen.
   Verhaltensgleicher Refactor, macht Params-Erzeugung für beliebige Pfade wiederverwendbar — wird
   ausschließlich im Main-Thread aufgerufen (siehe Punkt 5).

4. **Speaker-Review-Sidecar** (`src/bort/writers.py`, `write_outputs()` erweitert):
   - Neuer optionaler Parameter `review_data: dict | None`. Wenn gesetzt (nur beim
     whisperX-Backend), schreibt `write_outputs()` zusätzlich zu den Transkript-Formaten eine
     `{unique_base}.review.json` in denselben Datums-Ordner, mit dem exakt gleichen `unique_base`
     wie die Transkript-Dateien.
   - Inhalt (versioniertes Schema `"schema_version": 1`): `audio_path` (absoluter Pfad, beim Reopen
     auf Existenz geprüft), bereits sprecheraufgelöste `segments` (als `SpeakerSegment`-kompatible
     Dicts: start/end/speaker/text — **nicht** rohe `Segment`s, da `SpeakerManagerWindow` genau
     dieses Format erwartet), `speaker_map`, `markers`, `bookmarks`, `base_name`, `formats`.
   - Wird als Teil desselben `write_outputs()`-Aufrufs geschrieben wie die Transkripte: schlägt das
     Sidecar-Schreiben fehl, wirft `write_outputs()` eine Exception, die im bestehenden
     try/except von `transcription_worker` als Item-Fehler landet — eine Aufnahme gilt nie als
     „verarbeitet", ohne auch nachbearbeitbar zu sein (Atomizität über den bestehenden
     Fehlerpfad, keine neue Infrastruktur nötig).

5. **`BatchWindow`** (`src/bort/batch_window.py`, neu): `ctk.CTkToplevel` (Pattern wie bestehendes
   `SpeakerManagerWindow`).
   - UI: Sync-Ordner wählen + „Scannen" (ruft `scan_pending`) → Liste gefundener Paare → „Alle
     verarbeiten".
   - **Thread-Sicherheit:** alle `TranscriptionParams` für die Pending-Liste werden im Main-Thread
     gebaut (`parent_app._build_params()` je Item), bevor der Batch-Worker-Thread startet. Der
     Worker-Thread liest keine Tk-Variablen, öffnet keine Dialoge, ruft nur
     `transcription_worker(params, item_queue)` sequentiell auf.
   - **Job-Lock:** ein appweites Flag (`parent_app.job_running`) sperrt gegenseitig
     Haupt-„Transkribieren" und Batch-„Alle verarbeiten". Freigabe zentral in einer einzigen
     Main-Thread-Completion-Routine, die auf jedem Beendigungspfad läuft (Erfolg, Validierungsfehler,
     Exception im Worker, Abbruch durch Nutzer, Fenster-Schließen).
   - **Logger:** `_setup_worker_logging` entfernt nach Lauf-Ende gezielt nur den selbst
     hinzugefügten Handler (`root.removeHandler`) statt `root.handlers.clear()` — andere
     Logger-Hierarchien bleiben unangetastet und weiterhin per Propagation erfasst.
   - **Log-Forwarding:** alle `log`/`progress`-Nachrichten der Item-Queue werden an die
     Batch-eigene Queue weitergereicht, nicht verworfen.
   - **Vor jedem Item erneut geprüft:** Audio+Marker existieren noch, Marker-Datei wird vollständig
     neu geparst (nicht nur Existenz) — wird sie ungültig, gilt das Item als übersprungen, kein
     Absturz.
   - Ein Item-Fehler bricht den Batch nicht ab (loggen, überspringen, weiter).
   - Nach Abschluss: `self.pending` wird geleert, „Alle verarbeiten" bleibt deaktiviert bis zum
     nächsten expliziten Scan (kein Doppel-Run per Doppelklick).
   - Abschlussmeldung zählt Erfolg/Fehler/Übersprungen getrennt.
   - Fenster kann während eines laufenden Batches nicht zerstört werden — stattdessen expliziter
     „Abbrechen"-Button (stoppt nach aktuellem Item, gibt Lock frei).
   - Kein eigenes Settings-UI — nutzt Backend/Modell/Formate, die aktuell im Hauptfenster stehen.
   - **whisperX-Verhalten:** Diarization bleibt aktiv, aber der Speaker-Manager öffnet sich während
     eines Batch-Laufs nicht automatisch (Batch bleibt „weglaufen"-fähig für mehrere Dateien) —
     stattdessen wird pro Datei die Review-Sidecar geschrieben (Punkt 4), Sprecher-Umbenennung
     erfolgt über Punkt 6.

6. **Speaker-Review-Reopen-Flow** (`gui.py`, neuer Menüpunkt/Button „🎧 Sprecher nachträglich
   bearbeiten…"):
   - Dateiauswahl gefiltert auf `*.review.json`.
   - Lädt und validiert die Sidecar (Schema-Version prüfen, Pflichtfelder prüfen) — bei Fehler ein
     klares Fehlerdialog statt Stacktrace.
   - Prüft, ob `audio_path` noch existiert — falls nicht, Fehlerdialog statt Absturz beim
     Playback-Versuch.
   - Rekonstruiert `SpeakerSegment`-, `SpeakerMarker`-, `Bookmark`-Listen aus der Sidecar und öffnet
     die **bestehende, unveränderte** `SpeakerManagerWindow` (volle Wiederverwendung, kein neues
     Fenster nötig).
   - `SpeakerManagerWindow` ruft beim Umbenennen intern erneut `write_outputs()` auf. Damit das die
     **bestehenden** Transkript-Dateien überschreibt statt neue `_1`-Dateien zu erzeugen (aktuelles
     `_unique_base_name()`-Verhalten weicht Kollisionen aus), bekommt `write_outputs()` einen neuen
     Parameter `overwrite: bool = False`. Der Reopen-Flow ruft immer mit `overwrite=True` auf (der
     exakte `base_name` aus der Sidecar ist bekannt und eindeutig) — Einzel-Lauf und Batch bleiben
     beim Default `overwrite=False` (Kollisionsvermeidung wie bisher).

7. **Doku (kein Code)**: `HANDOVER.md` bekommt Abschnitt zum Tailscale+SMB-Setup — Samba-Freigabe mit
   least-privilege-Account (kein Gastzugriff, Zugriff auf Tailnet-Subnetz beschränkt), Tailscale-Tunnel,
   BoR-SAF-Ziel auf SMB-Pfad. Bestehender BoR-`Mover` bleibt unverändert.

## Key decisions & tradeoffs

- **Tailscale+SMB statt Syncthing/Google Drive**: weniger bewegliche Teile, Datei landet sofort,
  funktioniert auch remote. Tradeoff: SMB über VPN ist bei Verbindungsabbruch fragiler als Syncthings
  eingebautes Retry — durch Zwei-Sample-Stabilitätscheck entschärft (Punkt 2), nicht vollständig
  eliminiert.
- **Queue + manueller Batch-Start statt Auto-Trigger**: Nutzer entscheidet bewusst, wann verarbeitet
  wird.
- **Batch-Button in bestehender BoRT-GUI statt separates CLI-Script**: alles in einer App.
- **Dateisystem als Wahrheitsquelle** für „bereits verarbeitet" (kein State-File/DB): einfacher,
  bedeutet aber: löscht man ein Transkript manuell, taucht die Aufnahme beim nächsten Scan wieder als
  „pending" auf (akzeptiertes Verhalten, kein Bug).
- **Kein eigenes Settings-UI in `BatchWindow`**: Batch nutzt die aktuellen Haupt-Einstellungen —
  unterschiedliche Backend-Wahl pro Datei im selben Lauf ist nicht möglich (akzeptable Einschränkung
  fürs MVP).
- **Ein Item-Fehler bricht Batch nicht ab**: robuster bei mehreren Aufnahmen, aber Nutzer muss das Log
  durchsehen, um übersprungene Dateien zu erkennen.
- **Speaker-Review als Sidecar+Reopen statt Live-Modal im Batch**: löst den Zielkonflikt
  „Batch soll weglaufen-fähig sein" vs. „Sprecher müssen umbenennbar bleiben", indem die
  Nachbearbeitung zeitlich entkoppelt wird. Tradeoff: neuer Dateityp (`*.review.json`) und ein neuer
  `overwrite`-Pfad in `write_outputs()` — mehr Code als ein reines "Batch macht nichts mit Sprechern",
  aber notwendig, weil der Nutzer nachträgliche Bearbeitung explizit verlangt hat.
- **Stem-Kollision zwischen unterschiedlichen Audio-Endungen** (`x.m4a`/`x.mp3` gleicher Stem) wird
  nicht durch eine volle Hash-basierte Completion-Identität gelöst — das würde die
  Output-Namenskonvention (`base_name = audio_path.stem`) ändern, was auch CLI und Einzel-Lauf-Flow
  betrifft und damit keine Batch-lokale Änderung mehr wäre. Die mtime-Nicht-älter-als-Audio-Regel
  (Punkt 2) deckt den wahrscheinlichsten echten Fall ab (Aufnahme wird erneut committed), nicht aber
  zwei unabhängige Aufnahmen mit zufällig identischem Stem in derselben Minute — akzeptiertes
  Restrisiko angesichts BoRs Datums-Zeit-Namenskonvention (`YYYY-MM-DD_HH-mm_BoR[_Titel]`).

## Risks / open questions

- SMB-über-Tailscale-Verhalten bei Verbindungsabbruch während einer Datei-Kopie: durch
  Zwei-Sample-Stabilitätscheck entschärft, aber nicht unter echter Netzwerklast getestet — reines
  Infrastruktur-Risiko, keine weitere Code-Absicherung geplant.
- Android-Stock-Dateien-App SMB-Support (Android 10+) wird als ausreichend angenommen; Fallback-App
  (z.B. CX File Explorer) nur als Notiz erwähnt, nicht weiter spezifiziert.
- `BatchWindow` importiert `transcription_worker` aus `gui.py`, `gui.py` importiert `BatchWindow`
  lokal innerhalb einer Methode (Zirkularimport-Vermeidung) — noch nicht mit einem echten
  Import-Test verifiziert.
- Stem-Kollision zwischen unterschiedlichen Audio-Endungen — siehe „Key decisions", akzeptiertes
  Restrisiko.
- Review-Sidecar-Schema ist neu und noch nicht production-erprobt — Versionsfeld vorgesehen, damit
  künftige Formatänderungen erkennbar bleiben.

## Out of scope

- Automatischer Trigger der Transkription bei Dateiankunft (Auto-Watch).
- Google Drive oder Syncthing als Transfer-Weg (beide verworfen zugunsten Tailscale+SMB).
- Paralleles Verarbeiten mehrerer Dateien (GPU-Bindung durch whisperX schließt das aus).
- Hash-basierte Completion-Identität gegen Stem-Kollision (siehe „Key decisions").
- Automatisches Öffnen des Speaker-Managers während eines Batch-Laufs (bewusst durch
  Sidecar+Reopen ersetzt, damit Batch weglaufen-fähig bleibt).

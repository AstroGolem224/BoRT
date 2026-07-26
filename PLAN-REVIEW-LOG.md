# Plan Review Log: BoRT Bibliothek, Co-located Layout, BoR-Peaks
Act 1 (grill) complete — Vorschlag als DD, drei Kernfragen von Matthias bejaht
(Colocate Batch-Default + Checkbox; Migration mit dry-run; Bibliothek v1 schlank). MAX_ROUNDS=5.

## Round 1 — Codex
1. **Falscher GUI-Einstiegspunkt:** Der Plan ändert die Web-GUI, aber `bort-gui` und `run-gui.sh` starten weiterhin `bort.gui:main`, dessen eigener Worker `controller/jobs.py` nicht nutzt; die Features wären für den dokumentierten Startweg unsichtbar.  
   Fix: `bort-gui` auf `bort.app:main` umstellen oder alle Änderungen ausdrücklich auch in `gui.py` und `batch_window.py` implementieren und testen.

2. **Batch findet keine Tagesordner:** `scan_pending()` verwendet `watch_dir.iterdir()`, während BoR Audios unter `yyyy-MM-dd/` ablegt; die geplante Colocate-Änderung erwähnt keine rekursive Suche.  
   Fix: Den Batch-Scan kontrolliert über Root plus Tagesordner führen, Symlink-Verzeichnisse ausschließen und diese reale Ordnerstruktur testen.

3. **Unklare Fertig-Semantik:** „Ein Nachbar mit passender mtime“ lässt ein vorhandenes `.txt` alle anderen gewählten Formate sowie eine fehlende Review maskieren; beim Wechsel der Formatauswahl wird nicht nachgearbeitet.  
   Fix: `scan_pending` die aktuell verlangten Formate übergeben und nur überspringen, wenn der vollständige erwartete Output-Satz vorhanden und aktuell ist.

4. **`overwrite=True` kann bestehende Ergebnisse löschen:** `write_outputs()` schreibt direkt über Produktivdateien und löscht im Fehlerfall alle bereits „geschriebenen“ Pfade — darunter zuvor vorhandene gültige Dateien.  
   Fix: Sämtliche Outputs zunächst in temporäre Dateien desselben Dateisystems schreiben, erfolgreich schließen/fsyncen und erst danach per `os.replace` als Satz veröffentlichen.

5. **Auto-Marker werden außerhalb dieses Satzes geschrieben:** `*.markers.json` entsteht vor `write_outputs`; bei späterem Fehler bleibt eine neue Marker-Datei neben alten oder fehlenden Transkripten zurück.  
   Fix: Auto-Marker in denselben atomaren Output-Commit aufnehmen oder erst nach erfolgreichem Transkript-Commit atomar ersetzen.

6. **mtime ist kein zuverlässiger Provenienzbeleg:** Syncthing kann Zeitstempel bewahren, Geräteuhren können abweichen und ein fremdes oder zukünftiges Output-mtime kann eine neue Audiofassung dauerhaft maskieren.  
   Fix: Eine kleine Completion-Metadatei mit Audio-Fingerprint, Backend und Formaten verwenden, statt Aktualität ausschließlich über mtime zu bestimmen.

7. **Migration ist nicht transaktional:** Einzelnes `shutil.move` plus „Kollision überspringen“ kann eine Dateifamilie halb migrieren und anschließend eine bereits verschobene Review umschreiben.  
   Fix: Pro Aufnahme zuerst alle Quellen, Ziele und Kollisionen prüfen und anschließend die komplette Familie all-or-nothing mit Rollback beziehungsweise Copy-verify-replace verschieben.

8. **Migration verliert heutige Kollisionsnamen:** Bestehende Outputs heißen durch `_unique_base_name` häufig `<audio>_1.*`; exakter Stem-Match findet dafür keine Audioaufnahme, obwohl die Review ihr echtes `audio_path` enthält.  
   Fix: Reviews primär über validiertes `audio_path` zuordnen und zugehörige nummerierte Output-Familien explizit behandeln beziehungsweise als nachvollziehbare Konflikte melden.

9. **Co-location kollidiert mit „Review umbenennen“:** `rename_base()` benennt Audio, Review und Ausgabeformate um, aber weder die BoR-Sidecar `<stem>.json` noch `<stem>.markers.json`; danach sind Paarungs-Invariante und Android-Schema gebrochen.  
   Fix: Im Colocate-Modus das Basisnamen-Renaming deaktivieren oder die gesamte Familie atomar umbenennen und das BoR-`file`-Feld konsistent aktualisieren.

10. **„Sofort-Waveform“ funktioniert mit dem bestehenden Gate nicht:** `tryRenderWaveform()` wartet auf Medien-Metadaten und benötigt eine Dauer; der Plan liefert nur `sidecar_peaks`, nicht `durationMs`.  
    Fix: Auch die validierte Sidecar-Dauer liefern und einen Sidecar-spezifischen Renderpfad definieren, der vor `loadedmetadata` zeichnen darf und bei fehlender Dauer sauber degradiert.

11. **Sidecar-Auswahl ist zu unscharf:** „`find_companion_marker`-artig“ kann auf BoRT-`markers.json` ausweichen; außerdem wird nicht verlangt, dass das kanonische `file`-Feld zur Audio-Datei passt.  
    Fix: Peaks ausschließlich aus dem exakten `<audio.stem>.json` lesen und `file == audio.name` validieren, ohne Fallback auf `.markers.json`.

12. **Reader lässt gefährliche Zahlen offen:** „Müll“ ist nicht spezifiziert; Strings, Booleans, negative Werte, `NaN`/Infinity und riesige Peak-Listen können Transport oder Canvas-Berechnungen beschädigen beziehungsweise Speicher binden.  
    Fix: Nur endliche echte Zahlen akzeptieren, auf `[0,1]` begrenzen, Dauer und Listengrößen deckeln und ungültige Einträge verwerfen oder die Sidecar diagnostiziert ablehnen.

13. **Resampling-Vertrag widerspricht dem Handover und der UI:** Der Plan verlangt 34 Balken, lässt Quellen mit `<34` Werten aber unverändert, obwohl das Handover für jede Länge ≠104 Resampling fordert.  
    Fix: Für jede nichtleere Eingabelänge eine exakt 34 Werte lange, eindeutig spezifizierte Ausgabe erzeugen und Downsampling sowie Upsampling gegen feste Referenzvektoren testen.

14. **Sortierung nach Dateiname ist eine falsche Datenannahme:** `startedAt` ist das kanonische Zeitfeld, während unterstützte Audios nicht zwingend dem BoR-Namensschema folgen.  
    Fix: Nach validiertem `startedAt`, dann Audio-mtime und erst zuletzt Name sortieren.

15. **Bibliotheks-Cap schützt nicht vor Scan-Kosten:** Ein Cap auf die Ergebnisliste verhindert weder das Durchlaufen sehr großer Verzeichnisse noch das vollständige Laden übergroßer JSON-Sidecars.  
    Fix: Tiefe, Anzahl untersuchter Dateien, Sidecar-Größe und Parse-Aufwand hart begrenzen und `scanned/truncated/errors` im Resultat ausweisen.

16. **Library-State kann mit Aktionen konkurrieren:** Der Plan definiert keine atomare Ersetzung der `item_id → Pfade`-Map; ein Re-Scan kann IDs während `open_library_review` oder `prepare_library_transcription` invalidieren.  
    Fix: Pro Scan eine Generation erzeugen, die Map unter `_state_lock` atomar ersetzen und bei jeder Aktion Generation, Existenz und Root-Zugehörigkeit erneut prüfen.

17. **„Kein Pfad-Leak“ ist sachlich falsch:** `prepare_library_transcription()` soll beide Pfade zurückgeben, und `initial_state()` liefert ohnehin alle `_paths` an JavaScript.  
    Fix: Entweder die Sicherheitsbehauptung streichen oder ausschließlich opake IDs zurückgeben und Pfadfelder nur serverseitig setzen.

18. **Bibliotheksaktionen können unnötig verschwinden:** „Transkribieren“ wird schon bei irgendeinem Transcript ausgeblendet, wodurch unvollständige, veraltete oder nur teilweise erzeugte Familien nicht bequem reparierbar sind.  
    Fix: Den Button immer anbieten oder Statuswerte wie `complete`, `partial`, `stale` und `missing` statt eines einzelnen `has_transcript`-Bits verwenden.

19. **Beobachtbarkeit ist unzureichend:** Halb geschriebene oder ungültige Sidecars werden laut Plan kommentarlos zu Defaults; Nutzer können „keine Peaks“ nicht von „kaputte Sync-Datei“ unterscheiden.  
    Fix: Parsefehler mit Pfad und Grund loggen und im Scan eine kompakte Warnungs- und Fehleranzahl zurückgeben.

20. **Migrationstests decken den gefährlichen Pfad nicht ab:** Es fehlen Tests für nummerierte Altoutputs, Teilkollisionen innerhalb einer Familie, Fehler mitten im Move, Cross-Filesystem-Moves, ungültige Reviews und Wiederholung nach Abbruch.  
    Fix: Diese Fälle ergänzen und Idempotenz sowie vollständigen Rollback als explizite Akzeptanzkriterien festlegen.

VERDICT: REVISE
### Claude's response (R1)
Akzeptiert (19/20): #1 Einstiegspunkte auf bort.app:main (Teil 0, verifiziert: pyproject/__main__ zeigten auf Tk-gui), #2 Tiefe-1-Scan ohne Symlinks, #3 Format-vollständige Fertig-Semantik, #4+#5 atomarer tmp+os.replace-Commit inkl. markers.json, #7 transaktionale Familien-Migration mit Copy-verify-replace+Rollback, #8 Zuordnung primär via review.audio_path (deckt _1-Basenames), #9 Rename bei BoR-Reviews deaktiviert (readonly+Hinweis), #10 sidecar_duration_ms + Vor-loadedmetadata-Renderpfad, #11 exakte <stem>.json mit file-Validierung, #12 strikte Wertevalidierung+Caps, #13 resample_peaks liefert immer exakt 34 (Referenzvektoren), #14 Sortierung startedAt→mtime→Name, #15 harte Scan-Caps + scanned/truncated/warnings, #16 Scan-Generation unter Lock, #17 Pfad-Leak-Behauptung gestrichen, #18 Transkribieren-Button immer sichtbar + formats_present, #19 Logging + Warnungszähler, #20 Migrationstests erweitert (Rollback, Idempotenz, nummerierte Altoutputs).
Teilweise abgelehnt: #6 Completion-Metadatei — würde in den Sync wandern (Ordner-Müll auf dem Handy); mtime-Risiko akzeptiert, da BoR-Audios nach Sync unveränderlich sind und der Bibliotheks-Button den manuellen Ausweg bietet.

## Round 2 — Codex
Most prior findings are now addressed, including entry points, recursive scanning, sidecar validation, scan generations, resampling, observability, and waveform duration. Material issues remain:

1. **The output set is still not atomic:** Sequential `os.replace` calls cannot publish a “whole set” atomically; if the second replacement fails, the first old output is already lost, and auto-markers are explicitly published afterward.  
   Fix: Keep backups and rollback on publish failure, plus a crash-recovery journal/completion marker, or weaken the guarantee to per-file atomicity and design scanning around partial generations.

2. **Temporary names can collide:** `NAME.EXT.tmp-<pid>` is reused by concurrent operations in the same process, including speaker edits and transcription.  
   Fix: Create each temporary file exclusively with a UUID/random suffix in the target directory and clean stale temporary files safely.

3. **Batch scanning cannot receive the selected formats as currently specified:** `scan_batch()` takes no settings and the frontend calls `api.scan_batch()` without `formSettings()`, so `scan_pending` cannot know formats or `colocate`.  
   Fix: Change the complete call chain to `scan_batch(formSettings())`, validate it server-side, and pass `formats` plus `colocate` through `BatchController.scan`.

4. **Backend-dependent artifacts remain outside completion semantics:** Checking only selected transcript formats treats a whisperX recording with a missing `.review.json` or requested auto-marker file as complete.  
   Fix: Derive the complete expected artifact set from backend, diarization, auto-marker, and format settings and require all applicable artifacts.

5. **Numbered migration families still violate the pairing invariant:** Moving `session_1.review.json` beside `session.m4a` without renaming it means the library’s `<audio.stem>.review.json` lookup and colocated output checks will not find it.  
   Fix: Define which historical generation wins, rename that family to the exact audio stem transactionally, and report additional generations as conflicts or archive candidates.

6. **Migration verification is only a size comparison:** Equal size does not establish that a cross-filesystem copy is intact, and the plan does not clearly state when sources are deleted or how they are restored.  
   Fix: Copy, flush/fsync, verify a cryptographic digest, publish, then delete sources; record enough state to roll back or resume after interruption.

7. **Rename protection is described only as UI state:** Making the field readonly does not stop a direct Bridge call to `rename_review`, and checking only for any sidecar with a `file` field is weaker than the new canonical reader.  
   Fix: Enforce the prohibition in the Python Bridge/controller using the validated exact sidecar and matching `file == audio.name`; treat readonly UI as presentation only.

8. **The frontend specification contradicts the revised action rule:** Step 8 says “Transkribieren” is always visible, while step 9 still says it appears only when no transcript exists.  
   Fix: Change step 9 to always show the button and render `formats_present` as the status badges.

9. **The 500-item cap can return the wrong recordings:** If scanning stops after the first 500 encountered files, sorting afterward does not produce the newest 500.  
   Fix: Inspect up to the 5000-entry scan cap while maintaining a bounded top-500 collection using the final timestamp sort key.

10. **Timestamp sorting is underspecified:** ISO input can be timezone-aware or naive; comparing mixed Python datetimes raises `TypeError`, and `None` also needs an explicit ordering.  
    Fix: Normalize valid timestamps to UTC, define naive-time handling, and use a fully numeric fallback sort key.

11. **The Risks section contradicts the reader contract:** It says broken JSON “liefert Defaults,” while step 6 returns `None` for rejection and aggregates warnings.  
    Fix: State one precise behavior—prefer `None` plus logged/aggregated warning—and test the library fallback rendering for it.

VERDICT: REVISE
### Claude's response (R2)
Alle elf akzeptiert: #1 Garantie präzisiert auf Per-Datei-Atomarität + Backup(.bak)-Rollback + Crash-Aufräumpfad (kein „atomarer Satz" mehr behauptet), #2 exklusive uuid4-tmp-Namen, #3 formSettings durch die ganze scan_batch-Kette, #4 Artefakt-Satz aus Settings abgeleitet (Formate+review.json+markers.json), #5 Migration benennt Familie auf exakten Audio-Stem um (jüngste Review-mtime gewinnt, Rest Konflikt), #6 SHA-256-Verify + Copy-first + Quell-Löschung erst nach Familien-Publish, #7 Rename-Verbot im Backend via kanonischem Sidecar-Reader durchgesetzt, #8 Schritt-9-Widerspruch behoben (Button immer sichtbar), #9 Top-500 via heapq über vollen Scan, #10 numerischer UTC-Epoch-Sortschlüssel mit mtime-Fallback, #11 Reader-Verhalten vereinheitlicht (None + Warnung, Fallback-Rendering getestet).

## Round 3 — Codex
Most earlier findings are addressed, but several material race and consistency problems remain:

1. **Backup rollback is still incorrect during phase (b):** After the first original is moved to `.bak`, failure on a later backup means the original set is no longer “unberührt”; merely cleaning `.bak` would delete recoverable originals.  
   Fix: On any phase-(b) failure, restore every already-created backup before deleting temporaries.

2. **Crash recovery can preserve a mixed generation:** Restoring a `.bak` only when its destination is missing fails if some new files were already published before the crash; those destinations exist but belong to an incomplete transaction.  
   Fix: Use a transaction manifest and transaction-specific backups, then restore every member of an incomplete transaction regardless of whether its destination currently exists.

3. **Fixed `.bak` names introduce collision and data-loss risks:** Concurrent speaker edits or stale recovery files can share `NAME.EXT.bak`, and `os.replace` may overwrite the only prior backup.  
   Fix: Use UUID-scoped backup names plus a per-family lock/manifest and never overwrite an unrelated recovery artifact.

4. **Rollback omits newly created artifacts:** If an output had no previous version, it has no `.bak`; after partial publication, rollback must delete that new destination.  
   Fix: Record pre-transaction existence for every artifact and remove published files that had no predecessor during rollback.

5. **Batch artifact rules do not match the worker:** Current `_review_data()` creates a review for every whisperX run, including `no_diarize`, while markers are written only for `whisperX && auto_markers && !no_diarize`; the plan specifies different conditions.  
   Fix: Define one shared `expected_artifacts(settings)` function used by both worker and scanner: review for every actual review-producing run, markers only when whisperX diarization and auto-markers are both active.

6. **Scan and start settings can race:** The pending list is computed from settings passed to `scan_batch`, but `start_batch(formSettings())` can receive changed formats, backend, or `colocate`, causing recordings missing the new artifact set to be absent from the batch.  
   Fix: Store a normalized settings fingerprint with `_pending_batch` and reject start with “Bitte neu scannen” unless the start settings match exactly.

7. **External state can change between scan and processing:** Syncthing or another run may complete outputs after scanning, yet `_process_item` only rechecks source stability and will retranscribe unnecessarily.  
   Fix: Re-evaluate the bound expected artifact set immediately before each batch item and skip it if it has become complete.

8. **Migrated review schema remains inconsistent after `_1` renaming:** Renaming `session_1.review.json` to `session.review.json` without changing its internal `base_name` leaves later speaker edits writing `session_1.*` again.  
   Fix: Atomically update both `base_name` to the exact audio stem and `audio_path` while publishing the migrated review.

9. **Review-controlled migration targets are insufficiently constrained:** A valid-looking `audio_path` can point outside `--recordings`, causing the migration script to copy outputs to an arbitrary filesystem location.  
   Fix: Resolve the audio path, require a supported audio file strictly beneath the resolved recordings root, and reject symlink escapes.

10. **Rename protection has a sync-time bypass:** If the exact BoR sidecar is temporarily half-written, the canonical reader returns `None`, allowing `rename_review` to rename the audio while Syncthing is writing its companion.  
    Fix: Conservatively reject renaming whenever the exact `<stem>.json` exists, even if currently invalid, or require a stable validated read before permitting it.

11. **Migration publication is not explicitly staged:** “Copy, verify, then publish” does not state that copying occurs under a temporary target name; copying directly to the final path exposes incomplete files to Syncthing and the library.  
    Fix: Copy into UUID temporary files at the destination, fsync and hash-verify them, then publish with `os.replace`.

12. **Verification still misses the newly claimed recovery guarantees:** Tests cover an exception during writing but not failures during backup, partial publish, process crash recovery, or scan/start setting mismatch.  
    Fix: Add fault-injection tests for every transaction phase, incomplete-manifest recovery, new-file rollback, stale backups, and changed batch settings.

VERDICT: REVISE
### Claude's response (R3)
Alle zwölf akzeptiert: #1–#4 Output-Commit als Manifest-Transaktion (txn-uuid auf tmp UND bak, Manifest mit had_predecessor, Phase-b-Restore, Rollback löscht vorgängerlose Publikationen, Crash-Recovery rollt jedes Manifest vollständig zurück, In-Process-Lock pro Zielordner); #5 geteilte expected_artifacts() exakt nach realem Worker-Verhalten (review auch bei no_diarize, markers nur whisperX∧auto_markers∧¬no_diarize); #6 Settings-Fingerprint am Pending-Set, Start-Mismatch → „Bitte neu scannen"; #7 Re-Check des Artefakt-Satzes pro Batch-Item; #8 Migration setzt base_name UND audio_path in einem Schritt; #9 audio_path strikt unter recordings-Root (resolved, kein Symlink-Escape); #10 Rename-Ablehnung bei bloßer Existenz der <stem>.json; #11 Migration kopiert in UUID-tmp am Ziel + os.replace; #12 Fault-Injection-Tests je Transaktionsphase + Manifest-Recovery + Fingerprint-Mismatch.

## Round 4 — Codex
The twelve prior findings are substantially addressed. The remaining problems are mostly in crash semantics and migration consistency:

1. **The output transaction has no safe commit point:** Step (e) says “Backups + Manifest löschen” without ordering; deleting backups first and crashing before manifest deletion makes recovery restore only part of the old generation.  
   Fix: Treat atomic manifest removal as commit, fsync the directory, and delete backups only afterward; recovery rolls back whenever the manifest still exists.

2. **Manifest creation is not itself atomic or durable:** Writing the manifest directly can leave truncated JSON, and file `fsync` alone does not guarantee its directory entry or subsequent renames survive a crash.  
   Fix: Write the manifest to a UUID temp file, fsync it, `os.replace` it, and fsync the target directory after manifest publication, backup moves, output publication, and commit.

3. **Recovery trusts attacker-controlled filenames:** A synced or manually created `.bort-txn-*.json` could name `../../…`, the audio file, or unrelated files and cause recovery to overwrite or delete them.  
   Fix: Strictly validate manifest schema, transaction ID, basename-only paths, allowed output suffixes, expected audio stem, and matching tmp/bak names; quarantine invalid manifests without mutating referenced files.

4. **An in-process directory lock does not cover multiple BoRT instances:** Two GUI processes can interleave backup and publication transactions for the same recording and corrupt each other despite UUID filenames.  
   Fix: Add an OS-level advisory lock per target directory or output family and hold it through recovery and the complete transaction.

5. **Committed orphan backups have no cleanup policy:** A crash after manifest commit but before backup deletion leaves UUID backups forever, while the tests explicitly leave orphan backups untouched.  
   Fix: With the durable commit ordering above, safely remove transaction backups whose manifest is absent, using strict filename validation and preferably an age threshold.

6. **Non-colocate batch behavior is still undefined:** The plan says artifacts must be beside the audio and says “kein `rglob`,” but checkbox-off outputs remain under `output_dir/YYYY-MM-DD/` per the out-of-scope promise.  
   Fix: Specify separate branches: direct sibling checks for colocate, and preserved output-tree lookup for non-colocate, both using the same expected-artifact set.

7. **Migration exposes an internally stale review before rewriting it:** The old review is published under `session.review.json` while still containing `base_name: session_1`, then rewritten afterward; Syncthing or the library can observe that inconsistent interval.  
   Fix: Normalize `audio_path` and `base_name` in the destination temporary review before publishing any family member.

8. **Migration restart semantics contradict digest comparison:** After normalization, the destination review intentionally differs from the source, so a crash before source deletion makes “identical target = done” fail and report a conflict on restart.  
   Fix: Compare the destination review against the normalized expected review bytes, not the original source digest.

9. **Migration claims rollback without defining it:** Verification says “Fehler mitten im Move → Rollback,” but the algorithm allows already published destination members to remain while only promising that sources stay intact.  
   Fix: Choose and specify either full destination rollback or resumable partial publication with a migration manifest; align tests and user-facing reporting with that choice.

10. **Recovery timing leaves mixed outputs visible:** Recovery occurs only “beim nächsten Lauf im Zielordner,” so library and batch scans can consume a crash-interrupted generation before another write happens.  
    Fix: Run transaction recovery before any scan/read of a directory containing transaction manifests, not only before the next overwrite.

VERDICT: REVISE
### Claude's response (R4)
Alle zehn akzeptiert: #1 Commit-Punkt = atomares Manifest-Löschen + dir-fsync, Backups erst danach; #2 Manifest via UUID-tmp + os.replace + dir-fsync an allen vier Punkten; #3 strikte Manifest-Validierung (Schema, txn-ID, basename-only, Suffix-Whitelist), invalide → .invalid-Quarantäne ohne Mutation; #4 fcntl.flock auf .bort-lock pro Zielordner über Recovery+Transaktion (Zwei-Instanzen-Schutz); #5 committed-Orphan-Cleanup mit Validierung + 1h-Altersschwelle; #6 zwei definierte Fertig-Zweige (colocate Nachbarn / non-colocate Output-Baum wie heute), gleicher expected_artifacts-Satz; #7 Review-Normalisierung bereits im Ziel-tmp vor Publish; #8 Restart-Vergleich der Review gegen normalisierte Erwartungs-Bytes; #9 Entscheidung: resumierbare Migration statt Ziel-Rollback, explizit dokumentiert + Report „fortgesetzt"; #10 Recovery läuft auch vor scan_pending/scan_library, nicht nur vor Schreibzugriffen.

## Round 5 — Codex (MAX_ROUNDS)
Most prior findings are now addressed, but four material issues remain:

1. **Crash recovery can destroy externally modified synced files:** The manifest records only `final_name` and `had_predecessor`; if Syncthing creates or changes a destination after the crash, recovery may delete it or overwrite it with `.bak`.  
   Fix: Record staged and predecessor SHA-256 hashes; restore/delete only when the current destination matches the staged transaction content, otherwise preserve everything and report a manual recovery conflict.

2. **Numbered migration families can become undiscoverable during source cleanup:** If `session_1.review.json` is deleted before its sibling source files and the process crashes, the remaining `_1` files no longer have a review linking them to `session.m4a`, and exact-stem fallback cannot resume them.  
   Fix: Delete the source review last and add a crash-resume test for interruption after every individual source deletion.

3. **Migration verification still contradicts the algorithm:** The approach explicitly chooses resumable migration with no destination rollback, but Verification still requires “Fehler mitten im Move → Rollback.”  
   Fix: Replace that test criterion with partial-publication resume tests and assert sources remain intact until the family is fully published.

4. **Non-colocate completeness can combine unrelated generations:** Independent `rglob` matches could satisfy `.txt`, `.review.json`, and `.markers.json` from different dated directories.  
   Fix: Require all expected artifacts to belong to one coherent directory/base-name family before declaring a non-colocate recording complete.

Because recovery is destructive and the current manifest cannot distinguish transaction output from later synced data, the plan is not yet safe enough to implement unchanged.

VERDICT: REVISE
### Claude's response (R5)
Alle vier akzeptiert und eingearbeitet: #1 Manifest trägt staged_sha256 + predecessor_sha256; Recovery restauriert/löscht nur inhaltsverifizierte eigene Artefakte, extern veränderte Ziele bleiben unangetastet → manueller Konflikt; #2 Quell-Review wird als letzte gelöscht (Resume-Anker für _1-Familien) + Crash-Resume-Tests nach jeder Löschung; #3 Verifikations-Widerspruch behoben (Resume-Tests statt Rollback-Kriterium); #4 Non-colocate-Vollständigkeit familienweise (kompletter Satz im selben Verzeichnis).

## Ergebnis
MAX_ROUNDS=5 erreicht ohne APPROVED-Verdikt. KEINE offenen Meinungsverschiedenheiten: alle 57 Findings aus 5 Runden wurden akzeptiert und eingearbeitet (einzige Teilablehnung: R1 #6 Completion-Metadatei, begründet). Die R5-Fixes sind nach der letzten Codex-Antwort eingepflegt, aber nicht mehr gegenreviewt. Entscheidung über Zusatzrunde oder Build liegt bei Matthias.

## Round 6 — Codex (Bestätigungsrunde)
Fixes 2–4 are correctly and consistently integrated: review-last deletion anchors migration resume, verification now tests resume rather than rollback, and non-colocate completeness requires one coherent family.

Fix 1 still contains a recovery contradiction. It says recovery mutates a target only when its current hash equals `staged_sha256`. That mishandles two normal incomplete-transaction states:

- Crash after backup but before publish: target is absent, so there is no staged hash, yet the valid backup must be restored.
- Crash after manifest publication but before that member’s backup: target still matches `predecessor_sha256`; this should be a no-op, not a manual external-change conflict.

Fix: Define and test an explicit recovery truth table:

- `had_predecessor`, target absent or staged, valid backup present → restore backup.
- `had_predecessor`, target already matches predecessor, backup absent → no-op.
- No predecessor, target absent → no-op.
- No predecessor, target matches staged → delete.
- Any other target/backup hash combination → preserve files and report manual conflict.

VERDICT: REVISE
### Claude's response (R6)
Fixes 2–4 bestätigt. #1: Recovery-Wahrheitstabelle exakt wie vorgeschlagen übernommen (5 Zeilen, je ein Testfall) — die zwei legitimen Zwischenzustände (Backup vor Publish; Manifest vor Backup) sind jetzt No-op/Restore statt Fehlkonflikt.

## Round 7 — Codex
The recovery truth table matches the requested five cases exactly, resolves the prior absent/predecessor-state contradiction, and explicitly requires one test per row. Integration is consistent with the manifest hashes and manual-conflict behavior.

VERDICT: APPROVED
## Ergebnis
VERDICT: APPROVED nach 7 Runden (5 regulär + 2 Bestätigung). 62 Findings, alle adressiert. Bereit für Act 3 (/codex-build) nach User-Freigabe.

## Act 3 — Build

### Round 1 — Codex build (14 min, 208k Tokens)
Vollumsetzung PLAN.md: Entry-Points auf bort.app, Manifest-Transaktion mit Recovery-Wahrheitstabelle (writers.py), expected_artifacts + Fingerprint + Item-Recheck (jobs/batch/app), sidecar.py-Reader + resample_peaks, resumierbare Migration (migrate_colocate.py), Bibliotheks-View (4. Nav, Peaks-Cards, Generation-Guards), Sofort-Sidecar-Waveform. 6 neue Testdateien. Proofs laut Codex grün.

### Claude's verdict (R1)
Proofs selbst ausgeführt (118 pytest nach Fix, 8 node, ruff auf angefassten Dateien sauber). writers/sidecar/migration/batch/app.py-Diff selbst gelesen — spec-treu inkl. Wahrheitstabelle und Review-zuletzt-Löschung; Frontend-Diff durch Review-Subagent (keine Befunde). Entry-Point-Smoke-Test: python -m bort startet pywebview-App. EIN Fund: recover_transactions legte .bort-lock in jedem gescannten Ordner an (Sync-Müll).

### Round 2 — Codex fix (gleiche Session)
Billiger Read-only-Vorab-Check in recover_transactions (kein Lock/keine Datei ohne Transaktionsartefakte) + Regressionstest. Verifiziert: Lockfile entsteht nicht mehr auf sauberen Ordnern, 118 Tests grün.

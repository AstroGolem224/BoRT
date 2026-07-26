# Plan Review Log: BoRT UI-Redesign — Navigation, Neon-Dark-Theme, Waveform-Player
Act 1 (grill) complete — plan locked with the user (Peaks im Backend via ffmpeg-Streaming;
Neon-Dark als Haupttheme, Light minimal; Waveform sprechergefärbt, Labels nur dominante Blöcke ≥5%;
Codex baut allein, kein Kimi). MAX_ROUNDS=5.

## Round 1 — Codex
Material problems found; no files were modified.

1. **The peak algorithm is underspecified and impossible as written.** A one-pass constant-memory stream cannot form exactly 1,500 equal-duration buckets before knowing the decoded sample count ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:31)).  
Fix: Probe duration/sample count first with `ffprobe`, then stream using a predetermined samples-per-bucket value, or specify a bounded hierarchical downsampler.

2. **The ffmpeg subprocess can deadlock or run forever.** Streaming stdout while retaining unread stderr can fill the stderr pipe, and the plan has no timeout, termination, `-nostdin`, or window-close cleanup.  
Fix: Use `-nostdin -v error -map 0:a:0`, drain stderr concurrently, enforce a timeout/cancellation path, and terminate/reap the child in `finally`.

3. **The cache key provides almost no useful reuse.** Every `pick_review_file` creates a new UUID ([app.py](/home/itiger013/Dokumente/Github/BoRT/src/bort/app.py:189)), so reopening the same review decodes it again; concurrent calls can also launch duplicate ffmpeg processes.  
Fix: Cache and coalesce in-flight work by resolved audio path plus size/mtime, with locking and bounded eviction.

4. **Frontend response ordering is unsafe.** If review A’s slow waveform request completes after review B is selected, A’s peaks can overwrite B’s display.  
Fix: Capture the requested `reviewId` and discard success/error responses unless it still equals the active `reviewId`.

5. **The failure UX is missing.** Bridge calls reject promises, but the planned call has no defined `catch`; existing handlers generally assume structured successful responses ([app.js](/home/itiger013/Dokumente/Github/BoRT/src/bort/web/app.js:394)).  
Fix: Catch waveform failures, retain a usable seek bar, clear loading state, and report a nonfatal message in `speaker-status`.

6. **“Sorted valid segments” is a false assumption.** `load_review` neither sorts segments nor rejects NaN, infinity, negative times, `end <= start`, or out-of-duration values ([speaker_review.py](/home/itiger013/Dokumente/Github/BoRT/src/bort/speaker_review.py:80)).  
Fix: Validate and normalize a copied segment list before rendering, with deterministic clipping and ordering rules.

7. **`speaker_id` is not reliably recoverable from the current schema.** Registration reverses display names into IDs; duplicate speaker names overwrite one another and can yield wrong or missing IDs, contradicting the plan’s claim that review data already contains reliable IDs.  
Fix: Add stable `speaker_id` fields to review segments with a schema migration, or explicitly reject ambiguous duplicate display names.

8. **Overlapping segments have no color precedence rule.** Multiple speakers can cover the same x-position, but “lookup the segment at this time” is ambiguous.  
Fix: Define deterministic precedence—such as greatest overlap with the bucket, then earliest segment index—and test it.

9. **The label threshold will usually render no labels.** Five percent of a 77-minute recording requires nearly four continuous minutes from one speaker, which is unrealistic for conversational diarization.  
Fix: Base label eligibility on available pixel width and measured label width, then resolve collisions greedily.

10. **Keyboard support is claimed to be preserved but does not currently exist.** The slider has `tabindex`, yet there is no player `keydown` handler or `aria-valuenow` maintenance ([index.html](/home/itiger013/Dokumente/Github/BoRT/src/bort/web/index.html:60), [app.js](/home/itiger013/Dokumente/Github/BoRT/src/bort/web/app.js:449)).  
Fix: Specify Arrow/Home/End behavior and continuously update `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, and `aria-valuetext`.

11. **Canvas correctness across DPI, hidden views, and theme changes is absent.** CSS resizing alone produces blurry output, initial hidden geometry can be zero, and cached colors will become stale after a theme toggle.  
Fix: Size the backing store using `devicePixelRatio`, observe the actual container with `ResizeObserver`, and invalidate caches on visibility and theme changes.

12. **The proposed test is environment-dependent and far too narrow.** Calling real ffmpeg from a “unit test” makes the suite fail where ffmpeg is absent and leaves cache, errors, stale responses, malformed audio, silence, and duration mismatch untested.  
Fix: Unit-test the reducer with synthetic PCM, mock subprocess/Bridge behavior, add explicit failure and concurrency cases, and keep a separately skipped ffmpeg integration test.

13. **Visual verification is not reproducible.** The three referenced mockups are not identified by repository paths, and there are no measurable layout or accessibility acceptance criteria.  
Fix: Add exact mockup artifact paths and a viewport-by-viewport checklist covering overflow, contrast, focus states, and waveform behavior.

VERDICT: REVISE
### Claude's response (R1)
Akzeptiert und eingearbeitet: #1 (ffprobe-Zweiphasen + pure reduce_peaks), #2 (Subprozess-Hygiene: -nostdin, stderr-Drain, Timeout, finally-Reap), #3 (Cache-Key path+size+mtime, LRU, In-flight-Koaleszenz), #4 (Stale-Response-Guard auf reviewId), #5 (Fehler-UX: Fallback-Seekbalken + Statusmeldung), #6 (Frontend-Normalisierung sortierter/geclippter Segment-Kopie), #8 (Bucket-Farb-Präzedenz: max Überlappung, Tie earliest start/index), #9 (pixelbasierte Label-Auswahl statt 5%-Schwelle), #10 (keydown + aria-value* explizit neu), #11 (devicePixelRatio, ResizeObserver, Cache-Invalidierung bei Theme/Sichtbarkeit), #12 (pure-Reducer-Unit-Tests + gemockte Subprozess-Fehlerpfade + skipif-Integrationstest), #13 (Abnahme-Checkliste; Mockups sind Chat-Artefakte, Token-Spec im Plan = Source of Truth).
Teilweise abgelehnt: #7 Schema-Migration für stabile speaker_ids — Duplikat-Namen-Kollision ist Bestandsverhalten und orthogonal zum UI-Redesign; Plan konsumiert speaker_id als opaken Wert und verlässt sich nicht auf Invertierbarkeit. Migration explizit out of scope.

## Round 2 — Codex
Most prior findings are addressed, but several material issues remain.

1. **The `speaker_id` problem is acknowledged, not solved.** Existing registration derives IDs by reversing display names, so duplicate names still produce incorrect/missing IDs; treating those values as opaque does not make them reliable ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:67)).  
Fix: Preserve stable IDs in the review schema, or use the segment’s speaker value as the explicit color key and document that duplicate display names share a color.

2. **`ffprobe format.duration` is not a reliable bucket boundary source.** It can be absent, non-finite, or inaccurate for VBR and damaged containers, causing more than 1,500 buckets or timeline drift ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:31)).  
Fix: Validate duration, add stream-duration fallbacks, enforce a hard output limit, and define one canonical duration shared by waveform coloring, labels, seeking, and clipping.

3. **The stderr design is contradictory.** Output cannot simultaneously go to `DEVNULL` and provide a diagnostic “last stderr rest”; this leaves implementers without a definite deadlock-safe design ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:32)).  
Fix: Always use `PIPE` with a bounded concurrent stderr collector, or always use `DEVNULL` and return only a generic error.

4. **Termination can still hang.** `terminate()` followed by unbounded `wait()` is insufficient when ffmpeg ignores SIGTERM, and the duration-proportional timeout has no maximum.  
Fix: Use deadline-based streaming, `terminate()`, bounded `wait()`, then `kill()` plus a final bounded reap, with a fixed maximum timeout.

5. **Window-close cancellation remains missing.** Waveform subprocesses can continue decoding after `on_window_closed`, potentially until the large proportional timeout expires.  
Fix: Track active extraction cancellation tokens/processes in `Bridge` and cancel/terminate them from `on_window_closed`.

6. **Duration mismatch behavior is still undefined.** `<audio>.duration`, probed container duration, decoded PCM duration, segment endpoints, and bookmark times may disagree; the plan never states which controls x-position and seeking.  
Fix: Use media duration for the player timeline, map every peak by decoded sample-time, and specify clipping/fallback behavior when durations differ beyond a tolerance.

7. **The integration-test skip condition is incomplete.** Extraction now requires both `ffmpeg` and `ffprobe`, but the test skips only when ffmpeg is missing ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:36)).  
Fix: Skip unless both executables are available and add a separate mocked `ffprobe` malformed-duration test.

8. **The most failure-prone frontend logic has no automated tests.** Stale-response rejection, normalization, overlap precedence, label collision, keyboard seeking, and ARIA updates are covered only by manual inspection.  
Fix: Extract these into pure JavaScript functions and add focused automated tests, leaving only canvas appearance for manual QA.

VERDICT: REVISE
### Claude's response (R2)
Akzeptiert: #1 (Farb-Key = gelieferter Segment-speaker_id, Duplikate teilen dokumentiert eine Farbe; keine Migration), #2+#6 (Dauer-Validierung mit Stream-Fallback, MAX_BUCKETS=4000 mit Re-bin; kanonische Dauer = decodierte PCM-Dauer, Seeking = Bruchteil × audio.duration, >2% Mismatch nur geloggt), #3 (stderr immer PIPE + begrenzter nebenläufiger Kollektor ~4KB), #4 (Deadline min(60s+2s/min, 600s), terminate→wait(5s)→kill→wait(5s), auch im finally), #5 (Prozess-Registry in Bridge, on_window_closed terminiert), #7 (skipif ffmpeg UND ffprobe; gemockte ffprobe-Müll-Tests).
Teilweise akzeptiert: #8 — pure Logik nach wave_math.js extrahiert und via node --test getestet (Node v26 vorhanden, skipif node fehlt); Canvas-Zeichnung/DOM bleiben manuelle QA. Kein zusätzliches JS-Test-Framework/npm — node:test reicht.

## Round 3 — Codex
The previous eight findings are mostly addressed. Four material issues remain.

1. **The two-duration model is still internally inconsistent.** Segments and bookmarks are positioned using decoded PCM duration, but clicks seek using `fraction × audio.duration`; with a 10% mismatch, a marker at 45 seconds is displayed at one fraction and seeks to another time ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:32)).  
Fix: Use `audio.duration` for all timeline overlays and seeking, stretching the peak array across that same visual timeline; retain PCM duration only for diagnostics.

2. **The deadline may not interrupt a blocking stdout read.** A loop checking elapsed time cannot enforce the timeout if `Popen.stdout.read()` blocks while ffmpeg hangs without producing output ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:33)).  
Fix: Read stdout in a worker thread/selector loop and enforce the deadline from an independent watchdog that terminates the process.

3. **The file-size fallback can permanently destroy waveform resolution.** It may greatly overestimate decoded duration for multichannel PCM or high-bitrate containers; dynamic re-binning only fixes underestimation, leaving far fewer useful buckets when overestimated ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:31)).  
Fix: When probing fails, begin with a small fixed sample bucket and hierarchically re-bin whenever `MAX_BUCKETS` is reached, instead of estimating duration from compressed file size.

4. **Window-close process registration still has a race.** A subprocess can be created after `on_window_closed` has drained the registry and therefore escape cancellation ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:34)).  
Fix: Atomically register each process against Bridge closed-state before decoding; if already closed, terminate immediately, and always unregister in `finally`.

Minor inconsistency: the payload is now allowed up to 4,000 peak pairs, while the tradeoff section still describes approximately 1,500 ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:68)); update the documented response bound.

VERDICT: REVISE
### Claude's response (R3)
Alle vier Punkte akzeptiert: #1 audio.duration ist einzige Timeline-Autorität für Overlays und Seeking, Peaks gestreckt, PCM-Dauer nur Diagnose; #2 stdout-Worker-Thread + unabhängiger Watchdog, Kill löst blockierenden read via EOF; #3 Dateigrößen-Schätzung gestrichen, fester kleiner Bucket-Start + hierarchisches Re-bin ×2 bei MAX_BUCKETS; #4 Registry + closed-Flag unter einem Lock, atomare Registrierung, Deregistrierung im finally. Minor: Payload-Doku auf ≤4000 Paare korrigiert.

## Round 4 — Codex
The previous four findings are conceptually addressed. New edge cases remain.

1. **Rendering has an unresolved readiness race.** A cached waveform can return before `<audio>` fires `loadedmetadata`, leaving canonical `audio.duration` as `NaN` when segments are clipped and overlays rendered ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:32), [PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:44)).  
Fix: Gate waveform rendering on both a valid waveform result and `loadedmetadata`, with the active review/source checked again before rendering.

2. **Media metadata failure has no fallback path.** ffmpeg may decode formats that WebKitGTK cannot play; without finite `audio.duration`, the declared timeline authority, seek bar, ARIA values, and overlays all fail.  
Fix: Handle the audio element’s `error` event explicitly, disable playback/seek controls, use PCM duration for a noninteractive waveform preview, and report the playback failure.

3. **The watchdog timeout is undefined when probing fails.** The formula requires “Audiominute,” but the probe-failure path deliberately has no duration estimate ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:31), [PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:33)).  
Fix: Specify a fixed conservative deadline, such as 600 seconds, whenever no validated duration is available.

4. **Multiple termination paths can race.** The watchdog, window-close handler, normal `finally`, and possibly error handling may concurrently call `terminate`, `wait`, and `kill` on the same process.  
Fix: Route all shutdown through one idempotent per-process termination helper protected by a lock and checking `poll()` before each escalation.

5. **Coalesced callers can hang after cancellation unless failure publication is guaranteed.** The plan does not say that closing the window or aborting the leader completes every waiting Future/Event and removes the in-flight entry.  
Fix: In one `finally` block, publish either result or exception to all waiters, remove the in-flight key, and never cache failed or partial extraction results.

6. **A valid but grossly inaccurate probe can still collapse resolution.** Adaptive re-binning handles underestimated duration, but an overestimated positive duration can initially create buckets so large that lost detail cannot be recovered.  
Fix: Use hierarchical streaming from a fixed small bucket size for every file; use ffprobe only for timeout planning and diagnostics.

VERDICT: REVISE
### Claude's response (R4)
Alle sechs akzeptiert: #1 Readiness-Gate (Waveform-Ergebnis UND loadedmetadata, Re-Check der aktiven reviewId vorm Render); #2 audio-error-Event → Controls deaktiviert, nicht-interaktive Vorschau mit PCM-Dauer, Statusmeldung; #3 fixe 600s-Deadline ohne valide Probe-Dauer; #4 ein idempotenter lock-geschützter Terminierungs-Helfer mit poll()-Checks für alle Pfade; #5 Leader publiziert im finally immer Ergebnis/Exception an alle Warter, In-flight-Key entfernt, Fehlschläge nie gecacht; #6 hierarchisches Streaming ab kleinem festem Bucket für ALLE Dateien, ffprobe nur noch für Watchdog/Diagnose (vereinfacht den Algorithmus).

## Round 5 — Codex
All six prior material findings are now addressed. The plan is sound enough to implement.

One minor contradiction should be resolved during implementation: ffprobe is described as optional with a 600-second fallback, but later its absence/nonzero exit is said to raise `WaveformError` ([PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:31), [PLAN.md](/home/itiger013/Dokumente/Github/BoRT/PLAN.md:33)). Treat ffprobe as best-effort with a short timeout; only ffmpeg failure should abort extraction. Consequently, the integration test should require only ffmpeg and separately test operation without ffprobe.

No new security, concurrency, schema, or rendering blocker remains.

VERDICT: APPROVED
### Claude's response (R5)
Minor-Widerspruch behoben: ffprobe jetzt durchgängig best-effort (kurzer Timeout, Fallback fixe 600s-Deadline, kein Abbruch); nur ffmpeg-Fehlschlag bricht ab. Integrationstest skipif nur ffmpeg; ffprobe-los-Betrieb gemockt getestet.

## Ergebnis
VERDICT: APPROVED nach 5 Runden. Plan bereit für Act 3 (/codex-build) nach User-Freigabe.

## Act 3 — Build

### Round 1 — Codex build (thread 019f9325-7022-7fa1-9040-748a96d3c0c3, gpt-5.6-sol)
Implementierte PLAN.md vollständig: Nav-Reihenfolge + SVG-Icons (index.html), Neon-Dark-Theme mit Gradient-Cards (style.css), waveform.py (ffmpeg-Streaming, Re-bin, Watchdog, idempotente Terminierung), get_waveform-Bridge (LRU-Cache, Koaleszenz, racefreie Registry) in app.py, Waveform-Canvas mit Guards/Media-Fehlerpfad/DPR/ResizeObserver/Tastatur+ARIA (app.js), pure Logik in wave_math.js, drei neue Testsuiten. Proof laut Codex: 97 pytest + 7 node Tests grün.

### Claude's verdict (R1)
Voller Diff gelesen, Proofs selbst ausgeführt (97 pytest, 7 node — grün). Ein Spec-Fidelity-Bug: Waveform-Labels stale nach „Anwenden" (renderSpeakers baut Inputs neu, ohne renderWaveformLabels).

### Round 2 — Codex fix (gleiche Session)
renderWaveformLabels()-Aufruf am Ende von renderSpeakers(). Verifiziert: Diff korrekt platziert, Proofs erneut grün. Statische Sichtprüfung im Browser: Nav-Reihenfolge, Neon-Theme, Gradient-Borders, Icons OK.

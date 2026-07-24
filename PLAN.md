# Plan: BoRT UI-Redesign — Navigation, Neon-Dark-Theme, Waveform-Player
_Locked via grill — by Claude (Forge) + Matthias, 2026-07-24. Supersedes the Neumorphism-rewrite PLAN.md (built & committed); history in git._

## Goal

Die BoRT-Web-UI (PyWebView/WebKitGTK, `src/bort/web/`) bekommt das neue Neon-Dark-Design aus den drei Mockups (Screens Transkribieren, Sprecher, Batch), die Sidebar-Reihenfolge wird zu *Transkribieren, Batch, Sprecher*, und die Sprecher-Seite erhält eine Waveform-Zeitleiste mit sprechergefärbten Segmenten, Sprecher-Labels, Play/Pause-Button und Zeitanzeigen. Peaks werden im Python-Backend erzeugt (kein `decodeAudioData` im Frontend). Bestehende Funktionalität (Bridge-API, IDs, Event-Handler, Batch, Rename) bleibt intakt.

## Kontext (Ist-Zustand)

- `src/bort/web/index.html` (104 Z.), `app.js` (541 Z.), `style.css` (447 Z.)
- App läuft als `file://`-Seite; Audio kommt als `file://`-URI in `<audio id="player-audio">`. CSP: `script-src 'self'; style-src 'self'; media-src 'self' file:` — **kein Inline-JS/CSS möglich**, `connect-src 'self'` (kein fetch auf file://; Peaks müssen über die pywebview-Bridge kommen).
- Player existiert bereits: `#player-card` mit Play-Button, Zeitbalken (`#player-bar`), Bookmark-Markern, Playhead. Wird zur Waveform umgebaut.
- Review-Daten liefern bereits alles für Färbung/Labels: `segments[] = {start, end, speaker_id, text}`, `speakers[] = {id, name}` (`app.py::pick_review_file`).
- ffmpeg wird bereits in `src/bort/audio.py` benutzt (Decode-Pfad vorhanden).
- Theme-Toggle (hell/dunkel) existiert, Default dunkel, persistiert via localStorage + Config.

## Approach

1. **Navigation umsortieren** (`index.html`): Nav-Buttons in Reihenfolge Transkribieren, Batch, Sprecher. `data-view`-Werte und Logik unverändert.

2. **Design-Tokens & Theme** (`style.css`, punktuell `index.html`):
   - CSS-Variablen für die Mockup-Palette (Dark): Hintergrund tiefes Blau-Schwarz (~`#050810`–`#0a0f1e`), Card-Hintergrund leicht heller, Akzent Cyan (~`#22d3ee`), Sekundärakzent Magenta/Violett (~`#c026d3`/`#8b5cf6`), gedämpfter Text.
   - Cards: abgerundete Ecken, Gradient-Border cyan→magenta via Doppel-Background-Trick (`background: linear-gradient(card) padding-box, linear-gradient(accent) border-box; border: 1px solid transparent`) — kein zusätzliches DOM nötig.
   - Section-Header: Versalien, letter-spacing, Akzentfarbe, kleines Inline-SVG-Icon (SVG direkt im HTML, CSP-konform).
   - Sidebar: Logo-Badge oben (Hexagon/„B"), aktiver Nav-Eintrag mit Akzent-Hinterlegung + Border, Icons je Eintrag (Inline-SVG), Footer-Element unten.
   - Buttons: Primär = Cyan-Outline mit Glow; Sekundär = dezenter Border. Inputs/Selects/Checkboxen/Progressbar im Neon-Stil. Checkbox „checked" cyan gefüllt.
   - Light-Theme: bestehende Variablen minimal nachziehen (lesbar, kein eigenes Neon-Design). Dark bleibt Default.
   - Keine ID-/Klassen-Umbenennungen an funktionalen Elementen; nur additive Klassen/Markup.

3. **Backend-Peaks** (`app.py` + neues Modul `src/bort/waveform.py`):
   - **Ein Algorithmus für alle Dateien — hierarchisches Streaming:** ffmpeg-Decode nach mono s16le (`ffmpeg -nostdin -v error -i X -map 0:a:0 -f s16le -ac 1 -ar 8000 -`), Stream-weise gelesen. Start immer mit kleinem festem `samples_per_bucket` (4000 ≈ 0,5 s); erreicht die Bucket-Zahl `MAX_BUCKETS = 4000`, werden Buckets paarweise zusammengelegt und `samples_per_bucket` verdoppelt (Re-bin ×2). Keine Dauer-Vorhersage nötig, Auflösung in jeder Richtung robust. Konstanter RAM. Kernreduktion als **pure Funktion** `reduce_peaks(pcm_chunks)` inkl. Re-bin — ohne Subprozess testbar. `ffprobe -v error -show_entries format=duration:stream=duration` dient NUR der Watchdog-Planung und Diagnose.
   - **Eine Timeline-Autorität:** `audio.duration` des Media-Elements bestimmt ALLE Overlays (Segment-Färbung, Labels, Bookmarks, Playhead) und das Seeking. Das Peak-Array wird gleichmäßig über diese visuelle Timeline gestreckt (Peaks sind ohnehin äquidistant). Die decodierte PCM-Dauer wird nur zurückgegeben für Diagnose; Abweichung > 2 % → Konsolenwarnung.
   - **Subprozess-Hygiene:** `-nostdin`; stderr immer `PIPE` mit nebenläufigem, **begrenztem** Kollektor (Drain-Thread, behält nur die letzten ~4 KB → deadlock-frei, Diagnose bei Exit ≠ 0). **Watchdog statt Elapsed-Check:** stdout liest ein Worker-Thread; ein unabhängiger Watchdog-Timer terminiert den Prozess bei Deadline-Überschreitung — ein blockierender `read()` wird dadurch durch EOF gelöst. Deadline: `min(60 s + 2 s/Audiominute, 600 s)` bei valider ffprobe-Dauer, sonst **fix 600 s**. **Alle Beendigungspfade (Watchdog, Fensterschluss, `finally`, Fehler) laufen durch EINEN idempotenten, lock-geschützten Terminierungs-Helfer** (`poll()`-Check vor jeder Eskalationsstufe: `terminate()` → `wait(5 s)` → `kill()` → `wait(5 s)`). **ffprobe ist best-effort** (kurzer Timeout; fehlt/scheitert → fixe 600-s-Deadline, kein Abbruch); nur ffmpeg-Fehlschlag (fehlt oder Exit ≠ 0) bricht die Extraktion mit `WaveformError` ab, kein Crash. Integrationstest verlangt entsprechend nur ffmpeg; Betrieb ohne ffprobe wird separat (gemockt) getestet.
   - **Abbruch bei Fensterschluss, racefrei:** Registry + `closed`-Flag unter EINEM Lock. Registrierung des Prozesses prüft atomar das Flag — ist es gesetzt, wird sofort terminiert statt gestartet; Deregistrierung im `finally`. `on_window_closed` setzt das Flag und ruft für alle registrierten Prozesse den Terminierungs-Helfer.
   - **Koaleszenz-Garantie:** der Leader publiziert im `finally` IMMER Ergebnis ODER Exception an alle Warter und entfernt den In-flight-Key — auch bei Abbruch/Fensterschluss hängt kein Warter. Fehlgeschlagene/partielle Extraktionen werden nie gecacht.
   - Bridge-Methode `get_waveform(review_id) -> {ok, duration, peaks} | {ok: False, error}` in `app.py`:
     - **Cache-Key = (resolved audio_path, size, mtime)** — nicht Review-ID; Wiederöffnen derselben Datei decodiert nicht erneut. Bounded (z. B. letzte 4 Einträge, LRU).
     - **In-flight-Koaleszenz:** Lock + Future/Event pro Key, damit parallele Aufrufe nicht doppelt ffmpeg starten.
   - **Tests** (`tests/test_waveform.py`): `reduce_peaks` mit synthetischem PCM (Stille, Vollausschlag, Rampen, Bucket-Randfälle, leerer Stream, Re-bin bei MAX_BUCKETS); Fehlerpfade mit gemocktem Subprozess (fehlendes Binary, Exit ≠ 0, Timeout, ffprobe liefert Müll/leer/`N/A`); Cache-Hit/Koaleszenz; dazu EIN Integrationstest mit echter Mini-WAV, `@pytest.mark.skipif(shutil.which("ffmpeg") is None)`.

4. **Frontend-Waveform** (`index.html`, `app.js`, neu `wave_math.js`, `style.css`):
   - **Pure Logik ausgelagert** nach `src/bort/web/wave_math.js` (zweites `<script src>`, CSP-konform; exportiert über `window.BortWave` und, wenn `module.exports` existiert, für Node): `normalizeSegments`, `bucketSpeaker` (Überlappungs-Präzedenz), `mergeBlocks`, `layoutLabels` (Kollisionsauflösung, bekommt Messfunktion injiziert), `keyboardSeekTarget`, `ariaValues`. Canvas-Zeichnung und DOM bleiben in `app.js`.
   - **JS-Tests:** `tests/test_wave_math.py` führt `node --test tests/wave_math.test.mjs` per Subprozess aus, `@pytest.mark.skipif(shutil.which("node") is None)` (Node v26 lokal vorhanden). Getestet: Normalisierung (NaN/Inf/negativ/end≤start/Clipping/Sortierung), Bucket-Präzedenz inkl. Ties, Label-Kollision, Keyboard-Stepping, ARIA-Werte, Stale-Guard-Helfer.
   - `#player-card` erweitert: `<canvas id="player-wave">` ersetzt optisch den bisherigen Balken; darüber Label-Ebene `#player-labels`; Play-Button rund links; `#player-time` links, `#player-duration` rechts (bestehende IDs bleiben).
   - Nach `pick_review_file`-Erfolg: `api.get_waveform(reviewId)` asynchron; bis Ankunft Platzhalterbalken (bisheriges Verhalten), dann Canvas-Render.
     - **Stale-Response-Guard:** angeforderte `reviewId` capturen; Antwort (Erfolg wie Fehler) verwerfen, wenn sie nicht mehr der aktiven `reviewId` entspricht.
     - **Readiness-Gate:** Overlay-/Waveform-Render erst, wenn BEIDES vorliegt — gültiges Waveform-Ergebnis UND `loadedmetadata` mit endlicher `audio.duration`; direkt vor dem Render wird die aktive `reviewId`/`src` erneut geprüft (Cache kann vor den Metadaten zurückkommen).
     - **Media-Fehlerpfad:** `error`-Event des `<audio>` behandeln (WebKitGTK kann Formate verweigern, die ffmpeg decodiert): Play/Seek/Tastatur deaktivieren, Waveform als nicht-interaktive Vorschau mit PCM-Dauer als Zeitachse rendern, Meldung in `#speaker-status`.
     - **Fehler-UX (Waveform):** `.catch()` + `ok:false`-Pfad definiert — Platzhalterbalken bleibt als funktionierender Seek-Balken, Ladezustand wird beendet, nicht-fatale Meldung in `#speaker-status`. Waveform ist Enhancement, kein Blocker.
   - **Segment-Normalisierung (Frontend, Kopie):** vor Rendering `reviewSegments` kopieren, filtern (endliche Zahlen, `end > start`, `start ≥ 0`), auf `[0, duration]` clippen, nach `start` sortieren. Original bleibt unangetastet (Transkript nutzt Originalreihenfolge).
   - Rendering: Peaks als vertikale min/max-Balken; Farbe pro Bucket aus dem Sprecher-Segment mit der **größten Zeitüberlappung im Bucket, Tie-Break: früherer `start`, dann niedrigerer Segment-Index**; Fallback-Farbe für Lücken. Feste Farbpalette (8–10 Farben, cyan/violett/magenta-Familie) per `speaker_id`-Index; `speaker_id` wird als opaker Wert aus den gelieferten Segmentdaten konsumiert (keine Annahme über Eindeutigkeit von Anzeigenamen).
   - Abgespielter Teil heller/gesättigter, Rest gedimmt; Playhead-Linie; Bookmark-Marker bleiben als Ticks.
   - Labels: zusammenhängende Sprecher-Blöcke berechnen (aufeinanderfolgende Segmente gleichen Sprechers mergen, Lücken < 2 s tolerieren). **Label-Auswahl pixelbasiert:** Blöcke absteigend nach Dauer; Label wird gesetzt, wenn gemessene Textbreite + Padding in die Blockpixelbreite passt und kein bereits platziertes Label überlappt (greedy). Kein fester Prozent-Schwellwert. Label-Text = aktueller Name aus den Eingabefeldern; bestehender `input`-Handler rendert Labels live mit.
   - **Seek & Tastatur:** Klick wie bisher (`seekToFraction`). Neu und explizit: `keydown` auf dem Slider-Container — Pfeil links/rechts ±5 s, Home/End Anfang/Ende — plus laufende Pflege von `aria-valuemin/-valuemax/-valuenow/-valuetext` (heute fehlt beides trotz `tabindex`).
   - **Canvas-Korrektheit:** Backing-Store mit `devicePixelRatio` skalieren; `ResizeObserver` auf dem Container (fängt auch „View war beim Laden hidden/0px"); Peak-Offscreen-Cache invalidieren bei Resize, Theme-Wechsel und Sichtbarwerden der Sprecher-View. Redraw bei `timeupdate` nur Playhead/Dimmung.

5. **Verifikation**:
   - Bestehende Tests laufen lassen (`pytest`), neue Waveform-Tests grün.
   - Die drei Mockups liegen nicht im Repo (Chat-Screenshots); **Design-Spec ist die Token-/Komponentenbeschreibung in Abschnitt 2**. Abnahme-Checkliste statt Pixelvergleich:
     - [ ] Sidebar-Reihenfolge Transkribieren, Batch, Sprecher; aktiver Eintrag hervorgehoben; Icons sichtbar
     - [ ] Alle Cards mit Gradient-Border, kein Layout-Überlauf bei 1280×900 und maximiert
     - [ ] Buttons/Inputs/Checkboxen/Selects/Progressbar im Neon-Stil, Fokuszustände sichtbar (Tastatur-Tab-Runde)
     - [ ] Kontrast Text/Hintergrund lesbar (Status-, Muted-, Log-Texte)
     - [ ] Theme-Toggle: Light bleibt benutzbar, Zustand persistiert
     - [ ] Waveform mit echtem Review (77-Min-Datei): Ladezeit akzeptabel mit Platzhalter, Farbwechsel an Sprechergrenzen, Labels kollisionsfrei, Klick-Seek, Pfeiltasten-Seek, Rename ändert Label live, Fensterresize bleibt scharf (DPR)
     - [ ] Waveform-Fehlerfall (Audio fehlt/ffmpeg weg): Seek-Balken funktioniert weiter, Meldung im Status

## Key decisions & tradeoffs

- **Peaks im Backend statt Web Audio API**: WebKitGTK-`fetch` auf `file://` unzuverlässig + CSP `connect-src 'self'`; 77-Min-Decode im JS wäre RAM-Risiko. ffmpeg-Streaming ist robust und schon Projektabhängigkeit.
- **Bridge statt HTTP**: kein neuer Server, kein CSP-Umbau; Peaks-JSON (Ziel ~1500, hart ≤ 4000 Paare) ist klein genug für den bestehenden JSON-Bridge-Weg.
- **Gradient-Border per Doppel-Background**: kein Wrapper-DOM, keine Pseudo-Element-Hacks pro Card.
- **Labels pixelbasiert statt fester Prozent-Schwelle**: 9 Sprecher × hunderte Segmente sind nicht darstellbar; 5 % von 77 Min wäre zudem fast nie erfüllt (Codex-Review R1). Passt-das-Label-in-den-Block ist selbstkalibrierend über alle Aufnahmelängen.
- **Farb-Key = gelieferter Segment-`speaker_id`, Duplikate teilen Farbe**: die bestehende Namens→ID-Rückabbildung kann bei doppelten Anzeigenamen kollidieren (Bestandsverhalten). Die Waveform färbt strikt nach dem per Segment gelieferten Wert; kollabieren zwei Sprecher auf denselben Wert, teilen sie dokumentiert dieselbe Farbe — funktional korrekt, optisch degradiert. Schema-Migration bewusst out of scope.
- **Eine Timeline-Autorität: `audio.duration`** für Overlays UND Seeking; Peaks werden über diese Timeline gestreckt. PCM-Dauer nur Diagnose, Mismatch > 2 % wird geloggt statt „korrigiert" (Codex R3: zwei Autoritäten hätten Marker-Anzeige und Seek-Ziel auseinanderlaufen lassen).
- **Ein Builder (Codex, Act 3)**, kein Kimi parallel: zwei Schreiber im selben 3-Dateien-Frontend = Konfliktrisiko ohne Nutzen.
- **8 kHz mono für Peak-Extraktion**: Hüllkurve braucht keine Vollauflösung; konstanter Speicher, schnell.

## Risks / open questions

- Exakte Mockup-Farbwerte sind aus Screenshots geschätzt; Feintuning nach Sichtprüfung.
- `canvas`-Performance unter WebKitGTK bei sehr breiten Fenstern: Offscreen-Cache sollte reichen; sonst Redraw-Drosselung.
- Sehr lange Audios (>3 h): ffmpeg-Streaming skaliert linear; Ladezeit ggf. wenige Sekunden → Platzhalter bis dahin.
- Bookmark-Marker vs. Sprecher-Labels könnten sich optisch beißen; Marker als dezente Ticks unterhalb der Labels.

## Out of scope

- Kein neues Light-Neon-Design (Light bleibt funktional-minimal).
- Keine Änderungen an Transkriptions-/Batch-Logik oder Bridge-Architektur.
- Kein Zoom/Scroll in der Waveform, keine Segment-Editierung per Drag.
- Kein Kimi-CLI-Einsatz.

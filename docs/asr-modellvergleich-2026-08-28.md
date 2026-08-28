# ASR-Modellvergleich für BoRT — Messung und Empfehlung

**Datum:** 2026-08-28 · **Stand des Repos:** `2231988` · **Kein Umbau.** Dieses
Dokument misst und empfiehlt; es ändert die Transkriptionsstrecke nicht.

Messstand: [`scripts/asr_bench.py`](../scripts/asr_bench.py),
Tests: [`tests/test_asr_bench.py`](../tests/test_asr_bench.py).

---

## Kurzfassung

1. **Die ASR ist nicht der Engpass.** In der vollen Strecke entfallen von
   327 s Laufzeit für 173,6 min Audio nur **41,4 s (12,7 %) auf die
   Transkription**. Alignment (48,5 s) und Diarisierung (76,4 s) sind zusammen
   dreimal so teuer. Ein ASR-Tausch spart **rund 3 % der Gesamtlaufzeit**.
2. **Parakeet ist qualitativ ebenbürtig, nicht besser.** Auf FLEURS-de,
   identische Auswertung: **Whisper `large-v3-turbo` 4,14 % WER,
   `parakeet-tdt-0.6b-v3` 4,64 % WER.**
3. **Der Katalog hängt wirklich an pyannote, nicht an Whisper** — am Code und
   an einer echten Aufnahmedatei nachgeprüft. Ein reiner ASR-Tausch kostet ihn
   nicht.
4. **Ein echter Befund fiel dabei ab, der nichts mit dem Modellwechsel zu tun
   hat:** Wer in BoRT die Sprache fest auf `de` stellt statt `auto`, bringt die
   heutige Strecke auf DE/EN-gemischten Meetings zum Schleifen — gemessen ein
   **102-fach wiederholtes 6-Gramm** und **10 % Wortverlust** auf einer
   62-Minuten-Aufnahme. Mit `auto` tritt das nicht auf. Parakeet zeigt den
   Fehler unter keiner der beiden Einstellungen.

**Empfehlung: nicht tauschen.** Aufwandszahl und Begründung unten.

---

## Hardware und Bedingung — gilt für jede gemessene Zahl

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 5090, 32607 MiB, Treiber 610.57.04 |
| CPU / RAM | 24 Threads / 30 GiB, davon ~19 GiB anderweitig belegt |
| Fremdbelegung GPU | ~8,6 GiB durch Desktop, Mimic und ComfyUI während aller Läufe |
| Datum | 2026-08-28, alle Läufe innerhalb einer Stunde, warmer Modell-Cache |
| Wiederholungen | ein Lauf je Zelle (siehe „Was nicht gemessen wurde") |

### Stand der gemessenen Fremdprojekte

Die Grundlinie läuft über `~/projects/whisper-tagger`, ein von BoRT nicht
versioniertes Fremdprojekt. Ändert es sich, verfällt die Grundlinie still.
Gemessener Stand:

| | |
|---|---|
| whisper-tagger | `6981fce`, 2026-08-27 |
| faster-whisper / ctranslate2 | 1.2.1 / 4.8.1 |
| whisperx | 3.7.2 |
| torch | 2.11.0+cu128 |
| pyannote-audio | 3.4.0, Modell `pyannote/speaker-diarization-3.1` |
| Parakeet-Weg | `onnx-asr` 0.12.0, `onnxruntime-gpu` 1.29.0, Silero-VAD |

---

## Was gemessen wurde

**Audio:** vier eigene deutsche Geschäftsmeetings vom 2026-08-27, zusammen
**173,6 min** (22,0 / 29,9 / 59,5 / 62,2 min), AAC 44,1 kHz mono, natürliches
DE/EN-Code-Switching, mehrere Sprecher. Die Dateien bleiben lokal; hier stehen
nur Zahlen, keine Inhalte und keine Dateinamen.

**Drei Läufe über dieselben vier Dateien:**

| Lauf | Was |
|---|---|
| `whisperx` | die heutige BoRT-Strecke: ASR + Alignment + Diarisierung |
| `whisperx-asr` | dieselbe Strecke mit `--no-diarize` — isoliert die ASR |
| `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` über onnx-asr + Silero-VAD, nur ASR |

Alle mit `language=auto`, also der BoRT-Vorgabe. Dass das die richtige
Bedingung ist, steht in `run_metadata` der `.review.json` vom Vortag:
`{"backend": "whisperx", "model": "large-v3-turbo", "language": "auto",
"performance_profile": "balanced"}`.

---

## Messtabelle 1 — Gesamtlaufzeit, 173,6 min Audio, **gemessen**

| Lauf | Wall s | RTFx | Laden s | ASR s | Align s | Diar s | Peak VRAM MiB | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|
| `whisperx` (heute, voll) | **327,1** | 31,9 | 8,6 | 41,4 | 48,5 | 76,4 | 5856 | 3258 |
| `whisperx-asr` (nur ASR) | 61,9 | 168,4 | 7,3 | 41,5 | — | — | 5856 | 2253 |
| `parakeet` (nur ASR) | **51,6** | 202,0 | 5,3 | 44,5 | — | — | 6072 | 1628 |

Die Phasenzeiten stammen aus `runtime_metrics` des whisperX-Skripts, die
Wall-Zeit aus dem Messstand. Die Lücke zwischen 309,5 s Skriptzeit und 327,1 s
Wall sind ~18 s Prozessstart und Torch-Import über vier Aufrufe.

**Peak-VRAM ist bei Parakeet nicht vergleichbar interpretierbar:** onnxruntime
belegt eine Arena, keinen bedarfsgenauen Puffer. Die Zahl ist eine Obergrenze
der Reservierung, kein Modellbedarf. Der Whisper-Wert ist bedarfsnah.

### Je Datei — **gemessen**

| Datei | min | Lauf | Wall s | RTFx | ASR s | VRAM MiB | RSS MiB | Wörter |
|---|---|---|---|---|---|---|---|---|
| A | 22,0 | whisperx-asr | 9,9 | 133,8 | 5,00 | 5824 | 1809 | 1715 |
| A | 22,0 | parakeet | 6,6 | 199,8 | 5,25 | 6068 | 1461 | 1883 |
| B | 29,9 | whisperx-asr | 11,7 | 154,2 | 6,48 | 5856 | 1883 | 2650 |
| B | 29,9 | parakeet | 10,9 | 165,2 | 7,70 | 5944 | 1477 | 2951 |
| C | 59,5 | whisperx-asr | 19,6 | 182,1 | 14,45 | 5856 | 2217 | 7679 |
| C | 59,5 | parakeet | 16,4 | 217,8 | 15,16 | 6072 | 1602 | 8774 |
| D | 62,2 | whisperx-asr | 20,7 | 179,9 | 15,52 | 5856 | 2253 | 7241 |
| D | 62,2 | parakeet | 17,7 | 210,7 | 16,38 | 6072 | 1628 | 8340 |

**Die reine ASR-Zeit spricht für Whisper** (41,5 s gegen 44,5 s in Summe).
Parakeet gewinnt die Wall-Zeit ausschließlich am billigeren Prozessstart.
Parakeet liefert durchweg **10–15 % mehr Wörter** — Whispers VAD verwirft
Material, das Parakeet transkribiert. **Ob das die besseren Wörter sind, ist
ohne geprüfte Referenz nicht entscheidbar.**

---

## Messtabelle 2 — echte WER, FLEURS de_de, **gemessen**

Öffentliches Set mit geprüftem Referenztext, 120 Äußerungen, 2823 Referenz-
wörter, identische Normalisierung (`asr_bench.error_rates`), identische
16-kHz-PCM-Dateien für beide Motoren.

| Modell | WER | CER | ASR-Zeit s | Wörter |
|---|---|---|---|---|
| faster-whisper `large-v3-turbo`, float16, beam 3, batch 24 | **4,14 %** | 1,31 % | 15,5 | 2815 |
| `nemo-parakeet-tdt-0.6b-v3`, onnx, fp32 | **4,64 %** | 1,50 % | 5,7 | 2808 |

**Zum Vergleich, nicht gemessen sondern übernommen:** die Parakeet-Modelcard
nennt für Deutsch auf FLEURS **5,04 %**. Der hier gemessene Wert liegt darunter,
weil Teilmenge (120 statt voller Testsplit) und Normalisierung abweichen. Beide
Spalten oben sind unter sich vergleichbar, gegen die Modelcard nicht.

**Nicht vergleichbar und deshalb hier nicht aufgeführt:** RTFx-Werte des
HuggingFace-ASR-Leaderboards. Die sind auf A100 mit Batch 64 an englischem
Audio gemessen — andere Karte, andere Batchgröße, andere Sprache.

Auf sauber gelesener Einzelsprache ist Parakeet also **2,7× schneller und
0,5 Prozentpunkte schlechter**. Auf den Meetings dreht sich der Zeitvorteil
um (Tabelle 1), weil Parakeet dort mit VAD-Segmentierung statt Batching läuft.

---

## Messtabelle 3 — Abweichung vom heutigen Transkript

> **Das ist KEIN WER.** Die `.txt`-Dateien neben den Aufnahmen stammen vom
> heutigen Backend. Gegen sie zu messen ergibt „Übereinstimmung mit dem
> aktuellen Modell". Jedes andere Modell sieht darin schlechter aus, egal wie
> gut es ist. Der Messstand nennt die Zahl deshalb
> `similarity_wer_vs_current` und nicht `wer`.

| Lauf | A | B | C | D |
|---|---|---|---|---|
| `whisperx-asr`, `language=auto` (Kontrolle) | 0,0000 | 0,0000 | 0,0001 | 0,0001 |
| `parakeet` | 0,3184 | 0,2698 | 0,2153 | 0,2529 |
| `whisperx-asr`, `language=de` erzwungen | 0,0146 | 0,0000 | 0,3149 | 0,4744 |

Die erste Zeile ist die wichtige: **die Grundlinie reproduziert die Ausgabe
vom Vortag exakt.** Der Messstand misst also, was er zu messen behauptet, und
die heutige Strecke ist unter gleichen Einstellungen deterministisch.

Damit ist die zweite Zeile lesbar als „Parakeet weicht auf echten Meetings um
gut ein Fünftel bis ein Drittel vom heutigen Ergebnis ab" — **und um keinen
Deut mehr. Welches der beiden näher an der Wahrheit liegt, sagt sie nicht.**

---

## Nebenbefund: `language=de` bringt die heutige Strecke zum Schleifen

Die dritte Zeile oben war ursprünglich ein Messfehler von mir — ich hatte
`--language de` erzwungen statt BoRTs `auto`. Der Fehler hat etwas gefunden.

Häufigkeit des häufigsten wiederholten 6-Gramms je Transkript, **gemessen**:

| Datei | heutiges `.txt` (auto) | `whisperx-asr` auto | `whisperx-asr` **de** | `parakeet` |
|---|---|---|---|---|
| B (29,9 min) | 2 | 2 | 2 | 2 |
| C (59,5 min) | 2 | 2 | **12** | 2 |
| D (62,2 min) | 3 | 3 | **102** | 3 |

Bei D fällt die Wortzahl dabei von 7241 auf 6542 — **rund 10 % des Gesprächs
gehen in der Schleife verloren.** Der Effekt tritt in **allen drei**
Leistungsprofilen auf (`fast` 66×, `balanced` 102×, `quality` 102×), ist also
keine Frage von `beam_size`/`batch_size`.

`language` ist in BoRT ein normal einstellbarer Wert
(`cli.py`, `controller/jobs.py`, Web-Oberfläche). Auf deutschen Meetings mit
englischen Einsprengseln ist `de` die naheliegende, falsche Wahl.

**Das ist unabhängig vom Modellwechsel und billiger zu beheben:** eine Warnung
oder eine Vorgabe, die `auto` bevorzugt. Nicht Teil dieses Auftrags, deshalb
hier nur gemeldet, nicht gebaut.

---

## Was ein Wechsel bricht — am Code nachgeprüft

### Was **nicht** bricht: der Stimmenkatalog

`voice_profiles.py:262` verwirft beim Vergleich jedes Profil, dessen
`embedding_model` nicht mit dem angefragten übereinstimmt. Das Embedding-Modell
kommt aus `whisperx_transcribe.py:373` und ist dort fest
`DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"` — kein Whisper-Bezug.
Bestätigt an einer echten Aufnahme: `.review.json` trägt
`"embedding_model": "pyannote/speaker-diarization-3.1"`.

→ **Nur die ASR tauschen und pyannote behalten kostet den Katalog nicht.**

### Was bricht

| # | Was | Wo | Kosten |
|---|---|---|---|
| 1 | Alignment entfällt. whisperX richtet Wörter mit wav2vec2 aus und braucht dafür Whisper-Segmente. Parakeets Segmente kommen aus dem VAD. | `whisperx_transcribe.py:238-268` | Ohne Alignment fällt die Wort-Sprecher-Zuweisung auf Segmentgranularität zurück — die Sprecherzuordnung wird gröber, der Katalog bleibt |
| 2 | `fast`/`balanced`/`quality` sind `beam_size`/`batch_size`, also Whisper-Parameter. Für Parakeet bedeutungslos. | `whisperx_backend.py:38-42`, dazu 5 weitere Dateien in `src/` und 2 Tests | Neu zu definieren oder für das neue Backend abzuschalten |
| 3 | Übersetzung fällt weg. Parakeet kann nur transkribieren. | `transcription.py:129-133` (`--translate`) | Funktionsverlust, nicht umgehbar |
| 4 | `parakeet-cli` im Vendor ist **kein gangbarer Weg** — siehe unten | `vendor/whisper.cpp/build/bin/` | Der Weg führt über Python, nicht über die vorhandene Binärdatei |
| 5 | Dritte Laufzeitumgebung. Der onnx-Weg ist Python 3.12 + onnxruntime-gpu, nicht die whisper-tagger-venv. | — | Eine venv mehr zu pflegen, oder onnxruntime in whisper-tagger aufnehmen |

### Warum `vendor/.../parakeet-cli` ausscheidet — **geprüft**

Die Binärdatei ist gebaut und lauffähig (`LD_LIBRARY_PATH` auf
`vendor/whisper.cpp/build/bin` nötig), aber:

- **kein `--output-json`.** `--help` kennt nur `-otxt`/`-of`.
- **keine Sprachoption.** Ein DE/EN-Meeting lässt sich nicht steuern.
- **Segmente gehen nach stderr**, im Format
  `Segment %d: [%lld -> %lld] "%s"` (`examples/parakeet-cli/parakeet-cli.cpp:206-215`).
  BoRTs Parser erwartet auf **stdout** `[HH:MM:SS.mmm --> HH:MM:SS.mmm] Text`
  (`transcription.py:27-43`). Die Formate haben nichts gemeinsam.
- **das Modell fehlt.** `models/` enthält nur `ggml-tiny.bin` und
  `ggml-base.bin`; `ggml-parakeet-tdt-0.6b-v3.bin` existiert nirgends im Baum.

Ein Parser für dieses Format zu bauen hieße, eine Zeitachse in Frame-Indizes
zurückzurechnen, für ein Format ohne Sprachsteuerung. Der onnx-Weg liefert
Segmentgrenzen in Sekunden und Text als JSON, mit einer Abhängigkeit.

---

## Empfehlung

**Nicht tauschen.** Drei Zahlen tragen das:

1. **Nutzen:** ~10 s von 327 s (3 %) und ~0,6 GiB weniger RSS. Auf FLEURS ist
   Parakeet **0,5 Prozentpunkte schlechter**; auf den Meetings ist die
   Qualitätsfrage ohne geprüfte Referenz offen.
2. **Kosten:** die fünf Punkte oben. Grob beziffert:

   | Posten | Aufwand |
   |---|---|
   | `ParakeetBackend` neben `whisperx_backend.py`, JSON-Vertrag wie heute | 0,5–1 Tag |
   | Diarisierung ohne Whisper-Segmente an Parakeet anschließen | 1–2 Tage, **das ist der Brocken** |
   | Leistungsprofile umdefinieren (8 Dateien) plus Tests | 0,5 Tag |
   | Backend-Auswahl in CLI, GUI, Web, Konfiguration, Persistenz | 0,5 Tag |
   | dritte venv einrichten und in `install`/Packaging führen | 0,5 Tag |
   | Messung wiederholen, Katalog-Trefferrate gegenprüfen | 0,5 Tag |
   | **Summe** | **3,5–5 Tage** |

3. **Risiko:** die Sprecherzuordnung wird schlechter, bevor sie besser wird —
   und genau daran hängt der Stimmenkatalog, das teuerste Bauteil im Repo.

**Was stattdessen lohnt, in dieser Reihenfolge:**

1. **`language=de` entschärfen** — der 102×-Schleifenbefund oben. Ein Tag Arbeit
   an einer Stelle, gegen einen Fehler, der 10 % eines Meetings frisst und im
   Ergebnis nicht auffällt. Größter Hebel im ganzen Dokument.
2. **Diarisierung angehen, nicht die ASR.** 76,4 s von 327 s. Wer die Laufzeit
   halbieren will, fängt hier an, nicht bei den 41 s Transkription.
3. **Parakeet als Zweitmeinung, nicht als Ersatz.** Der Messstand steht; ein
   zweiter Durchlauf über dieselbe Datei kostet 52 s für 173 min. Wo beide
   Modelle dasselbe sagen, stimmt es sehr wahrscheinlich. Das wäre ein
   Qualitätssignal ohne Referenzkorpus — deutlich billiger als ein Tausch.

**Canary-1b-v2 und Qwen3-ASR-1.7B wurden nicht gemessen** — Begründung unten.

---

## Was nicht gemessen wurde, und warum

| Nicht gemessen | Grund |
|---|---|
| **Echte WER auf den Meetings** | Es gibt keinen geprüften Referenztext. Matthias' Vorgabe war ausdrücklich, ohne Goldkorpus-Vorlauf zu messen. Ersatz: echte WER auf FLEURS (Tabelle 2) plus ausdrücklich als Ähnlichkeit beschriftete Abweichung (Tabelle 3) |
| **Diarization Error Rate, speaker-attributed WER, Katalog-Trefferrate** | Alle drei brauchen eine Sprecherreferenz je Zeitabschnitt. Die `.labels.txt` neben den Aufnahmen sind **0 Byte**. Ohne diese drei ist der Satz „der Katalog ist nicht in Gefahr" hier **am Code und an einer Aufnahmedatei belegt, nicht durch Messung** |
| **`nvidia/canary-1b-v2`** | Zeitbudget. Braucht NeMo, nicht den leichten onnx-Weg. Grundlinie plus ein sauber gemessener Kandidat war die Vorgabe |
| **`Qwen3-ASR-1.7B`** | dito, als „optional" beauftragt |
| **Streuung** | Ein Lauf je Zelle. Die Grundlinie reproduziert die Vortagsausgabe auf 0,0001 genau, die Ausgabe ist also stabil; über die **Zeit**streuung sagt das nichts. Für Differenzen unter ~10 % taugen die Zeitzahlen nicht |
| **Kalter Cache** | Alle Läufe warm. Der erste Lauf nach dem Booten ist langsamer |
| **CER auf den Meetings** | Kostet je 60-Minuten-Transkript ~2,5 min Rechenzeit und ändert die Aussage nicht. Steht im Messstand hinter `--cer` |

---

## Messung wiederholen

```bash
A=~/Dokumente/BoR_Aufnahmen/2026-08-27

# Grundlinie, volle Strecke
scripts/asr_bench.py --backend whisperx --language auto \
    --compare-suffix .txt --out /tmp/whisperx-full.json "$A"/*.m4a

# Grundlinie, ASR isoliert
scripts/asr_bench.py --backend whisperx-asr --language auto \
    --compare-suffix .txt --out /tmp/whisperx-asr.json "$A"/*.m4a

# Parakeet — braucht eine venv mit onnx-asr[gpu,hub]
uv venv --python 3.12 /tmp/asrbench
VIRTUAL_ENV=/tmp/asrbench uv pip install 'onnx-asr[gpu,hub]'
scripts/asr_bench.py --backend parakeet --worker-python /tmp/asrbench/bin/python \
    --language auto --compare-suffix .txt --out /tmp/parakeet.json "$A"/*.m4a
```

Echte WER gegen einen geprüften Referenztext: die Referenz als
`<audioname>.ref.txt` neben die Audiodatei legen, dann rechnet der Messstand
sie ohne weiteres Zutun mit — als `wer`, nicht als Ähnlichkeit.

**Die Ergebnis-JSONs gehören nicht ins Repo.** Sie tragen die Dateinamen der
Aufnahmen, und die enthalten Klarnamen.

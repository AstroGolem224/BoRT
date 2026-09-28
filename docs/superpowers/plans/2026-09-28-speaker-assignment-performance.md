# Sprecherzuordnung beschleunigen, laufendes BoRT schützen

Der Nutzer hat die Umsetzung des analysierten Engpasses mit vollständiger automatischer Sprechererkennung beauftragt. Originalcheckouts, laufende Prozesse, Einstellungen und Modelldateien bleiben unverändert. Arbeit in BoRT-performance und whisper-tagger-performance; Tests ausschließlich CPU mit niedriger Prozesspriorität.

## Designentscheidung

Die teure Mehrheitszuordnung bekommt einen einmal je Datei aufgebauten Intervallindex. Nach Startzeit sortierte Intervalle und das Präfixmaximum ihrer Endzeiten begrenzen jede Wortabfrage per Binärsuche. Treffer werden in ursprünglicher Zeilenreihenfolge summiert, damit Fließkommareihenfolge und Gleichstände erhalten bleiben. Die erste WhisperX-Zuordnung bleibt als unveränderter Fallback erhalten. Kein Modellwechsel, keine geänderten Beam-/Batch-Werte, keine abgeschaltete Diarisierung. Fehlende Wortzeiten, leere Intervalle und unsortierte/überlappende Intervalle werden gegen den bisherigen Code geprüft.

## Ausführung und Prüfung

1. Baseline: BoRT-Gesamttests; Backendtests ohne GPU. Neue CPU-Tests vergleichen die optimierte Funktion mit einer unveränderten Kopie der bisherigen Funktionen. Zufallsfälle und Randfälle plus ein Test, der DataFrame.iterrows während der Zuordnung verbietet; zuerst Rotlauf.
2. Backend: speaker_assignment.py enthält Intervallindex und dieselbe Mehrheitsregel. whisperx_transcribe.py importiert die bisherigen privaten Namen kompatibel und misst beide Zuordnungsphasen getrennt. Pipeline-Integration mit gefälschten Modellstufen prüft Diarisierungsaufruf, Speaker/Embeddings und JSON-Metriken ohne GPU.
3. BoRT: optionaler BORT_WHISPER_TAGGER_SCRIPT-Pfad erlaubt den neuen Backendcode bei unverändertem vorhandenen Python-/CUDA-Wrapper. Default bleibt bestehen. Test realer Subprozessaufruf mit einer lokalen Stub-Pipeline plus vorhandene Suite. Dokumentation und separater lokaler Starter machen die isolierte Fassung nutzbar.
4. Messung: CPU-Benchmark alter/neuer Funktion auf identischen synthetischen Wortzeitstempeln und echten gespeicherten Markerintervallen, ohne Transkriptinhalte zu speichern. Exakte Ergebnisgleichheit, Zeitmessung und getrennte Kennzeichnung gegenüber vollständiger Audiotranskription.
5. Review, gezielte Korrekturen, volle relevante Tests, Commits beider Worktrees. Keine Aktivierung im laufenden Programm. Starter/Commits und verbleibende echte GPU-End-to-End-Prüfung im Abschluss nennen.

Bewusst nicht Teil dieses Eingriffs: dauerhafter GPU-Worker, Modellcache-Umbau, Parakeet-Backend, Änderung der Originalzeitachse oder der Wortmehrheitsregel.

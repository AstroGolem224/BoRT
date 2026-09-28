# Aktivierte Transkriptionsoptimierung, 28.09.2026

Die Änderungen aus BoRT `e513943` und whisper-tagger `a50f870` sind in die regulären lokalen Checkouts übernommen. Der normale Desktop-Eintrag startet weiterhin `BoRT/launch.sh`; die virtuelle Umgebung importiert den aktualisierten Anwendungscode. Das reguläre Backend liegt unter `~/projects/whisper-tagger/whisperx_transcribe.py`. Ein separater Starter und Umgebungsvariablen sind nicht erforderlich.

Automatische Sprechertrennung, Alignment, Embeddings/Stimmprofile, Whisper-Modell und Decoderparameter bleiben unverändert. Optimiert wurde die zusätzliche Zuordnung der Sprecher zu den erkannten Wörtern/Segmenten. Der Index behält Überlappungs-, Gleichstands-, Summations- und Fallbackregeln bei.

## Vollständiger GPU-Lauf

Eine Aufnahme von 4.129,205 Sekunden (68:49 Minuten) wurde mit `large-v3-turbo`, automatischer Sprache, Beam 3, Batch 24, Diarisierung und Embeddings verarbeitet. Die vorhandenen Modelle wurden offline geladen.

| Phase | Sekunden |
|---|---:|
| Python-Imports | 2,532 |
| Modell und Audio laden | 2,378 |
| ASR einschließlich VAD | 30,158 |
| Alignment einschließlich Laden | 22,089 |
| Diarisierung einschließlich Laden | 32,265 |
| Erste WhisperX-Zuordnung | 3,380 |
| Optimierte Mehrheitszuordnung, ohne Diagnosekopien | 0,0112 |
| Backendpipeline einschließlich Diagnosekopien | 90,680 |
| Gesamter Diagnoselauf bis zum fertigen Transkript einschließlich Imports | 93,224 |

Das Ergebnis enthält 1.155 Segmente und acht Sprecher mit Embeddings. Die Mehrheitszuordnung verarbeitet 10.097 echte ausgerichtete Wörter und 1.941 Diarisierungsintervalle. Die interne Metrik `majority_assignment_seconds` dieses Diagnoselaufs beträgt 0,079 s, weil für den Referenzvergleich Eingabe und Ausgabe kopiert wurden; die eigentliche optimierte Funktion dauerte 0,0112 s.

Im früheren Diagnoselauf waren es 243,897 s einschließlich Imports. Damals lief parallel ein weiterer BoRT-Auftrag; daher ist das kein kontrollierter Gesamtvergleich und kein allgemeines Geschwindigkeitsversprechen.

## Ergebnisgleichheit auf echten Wortzeiten

Nach Abschluss der optimierten Pipeline wurde die unveränderte frühere Funktion aus Commit `6981fce` auf einer Kopie derselben Eingabe ausgeführt. Das gesamte Ergebnis der Sprecherzuordnung war exakt gleich, einschließlich Wortattributen und Segmentsprechern. Der Referenzlauf dauerte **152,045 s**, die neue Funktion **0,0112 s**. Diese Referenzarbeit fand nach der gemessenen Transkription statt und ist nicht in den 93,224 s enthalten. Der Vergleich misst den optimierten Schritt auf identischen Daten; er beansprucht keine Bewertung der allgemeinen ASR- oder Diarisierungsqualität.

## Regulärer BoRT- und Oberflächentest

Eine zweite, 70,635 Sekunden lange Aufnahme lief durch `transcription_worker` und dessen echten Subprozessaufruf des regulären Backends. Gesamtdauer 9,422 s; reine Backendpipeline 5,536 s. Alle vier Formate (TXT, Markdown, CSV, TSV), automatische Marker und die Review-Datei einschließlich Sprecherprofilen wurden erfolgreich in ein temporäres Testverzeichnis geschrieben. Vorhandene Aufnahmen und Ergebnisdateien wurden nicht überschrieben.

Die reguläre pywebview/GTK-Oberfläche wurde unter Xvfb geöffnet und nach dem Laden automatisch geschlossen; Einstellungen und Stimmkatalog lagen hierfür in einem temporären Verzeichnis. Die echte Benutzereinstellung und die geschützten Quelldateien des kurzen Tests sind per SHA-256 unverändert.

Nach der Integration bestanden 152 BoRT-Tests und 33 Backendtests. Ruff-Prüfungen mit den jeweiligen Projektvorgaben sowie Git-Whitespace-Prüfungen bestanden. Eine bereits vorhandene GLib-Abkündigungswarnung bleibt bestehen. Die neuen Funktionen waren zuvor unabhängig geprüft worden; es gab keine blockierenden Review-Befunde.

Die Messskripte und JSON-Belege liegen im lokalen Codex-Artefaktordner der Aufgabe (`bort-performance`). Die Tests ändern keine Transkriptionsoptionen oder Benutzerdateien. Der komplette Altalgorithmus wird nur im Referenztest ausgeführt, nicht mehr im regulären Produktivlauf.

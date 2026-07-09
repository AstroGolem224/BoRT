# BoR ↔ BoRT Handoff-Automatisierung — Design

Datum: 2026-07-09
Status: Approved, bereit für Implementierungsplan

## Problem

Aktueller Workflow: BoR (Android) speichert M4A+JSON, Upload nach Google Drive manuell, Download+lokale Ablage manuell, in BoRT (Desktop) jede Datei einzeln per Filepicker ausgewählt und transkribiert. Drei manuelle Schritte, kein Automatisierungsgrad.

Ziel: Transfer automatisieren, Transkription per Batch-Knopf statt Einzelauswahl. Tag/Sprecher-Nachbearbeitung bleibt bewusst manuell (kein Automatisierungsbedarf dort).

## A. Transfer: Tailscale + SMB

Kein Code-Change an BoR nötig — nutzt bestehenden SAF-`Mover` (`data/Mover.kt`) unverändert.

- PC: SMB-Freigabe (Samba) auf einen Zielordner.
- Tailscale auf PC und Handy, gleiches Tailnet.
- Handy: BoR-SAF-Ziel in Settings (`data/Settings.kt`) auf `\\<pc-tailscale-ip>\<share>` setzen, via Android-Stock-SMB-Netzwerkspeicher (Android 10+, keine Drittapp nötig, falls Stock-Support ausreicht — sonst Fallback-App wie CX File Explorer klären in Plan-Phase).
- Mover kopiert fertige Recording-Paare (Audio+JSON) bei Recording-Stop/App-Start/Library-Open automatisch auf die SMB-Freigabe, landet sofort im Sync-Ordner auf PC.
- Kein Google Drive, kein Syncthing.

**Risiko zu klären in Plan-Phase:** SMB über VPN-Tunnel bei Verbindungsabbruch — bestehende Crash-Safety des Movers (aktive Aufnahme bleibt lokal, erst abgeschlossene Paare werden verschoben) sollte Teilschreiben abfangen; im Implementierungsplan verifizieren, ob Mover bei Schreibfehler retryt oder Nutzer benachrichtigt.

## B. Pending-Erkennung: `scan_pending()`

Neues Modul `src/bort/batch.py`, reine Funktion:

```
scan_pending(watch_dir: Path, output_dir: Path) -> list[tuple[Path, Path]]
```

- Paart Audio+JSON im `watch_dir` nach Basisname (gleiche Konvention wie bestehende `markers.py`-Erkennung).
- Filtert Paare heraus, für die bereits ein Output-Transkript in `output_dir` existiert.
- Keine State-Datei/DB — Dateisystem ist alleinige Wahrheitsquelle. Einfachster Stand, der reicht.

## C. Batch-UI in BoRT

Neuer Tab/Abschnitt in `gui.py`:

- **Scan**-Button: ruft `scan_pending()`, listet gefundene Paare (Dateiname, Dauer).
- **Alle verarbeiten**-Button: iteriert Liste sequentiell, ruft für jedes Paar den bestehenden Transkriptions-Pfad auf (`transcription_worker` → `whisperx_backend.py`/`transcription.py`), keine Änderung an der Kernlogik selbst.
- Bleibt strikt sequentiell (ein File nach dem anderen) — GPU-gebundene whisperX-Pipeline erlaubt keine Parallelverarbeitung.
- `watch_dir`/`output_dir` über bestehende Konfigurationsmechanismen konfigurierbar (Details in Plan-Phase prüfen, da im Research nicht exploriert).

## D. Nachbearbeitung

Tag-/Sprecher-Zuordnung bleibt manuell in bestehender BoRT-GUI — kein Automatisierungsbedarf, bestehende Merge-Logik (`markers.py`, erkennt Android-Format bereits korrekt) unverändert.

## Test

`scan_pending()` ist pure Funktion, keine I/O-Seiteneffekte außer Dateisystem-Lesen → ein `test_batch.py` mit Fake-Verzeichnisstruktur (Paare mit/ohne existierendem Output) reicht als Pflicht-Check.

## Out of Scope

- Auto-Trigger der Transkription bei Dateiankunft (bewusst abgelehnt — Queue + manueller Batch-Start gewünscht).
- Automatisierung der Tag-/Sprecher-Nachbearbeitung.
- Google Drive / Syncthing als Transfer-Weg (verworfen zugunsten Tailscale+SMB).

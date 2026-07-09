# Plan: Tkinter-GUI für BoRT

## Ziel
Eine grafische Oberfläche (GUI) hinzufügen, mit der der Nutzer:
- eine MP3-Datei auswählen kann,
- optional eine JSON-Marker/Tag-Datei auswählen kann,
- das whisper.cpp-Modell auswählen kann,
- Sprache und Ausgabeformate festlegen kann,
- den Transkriptionsvorgang starten und den Fortschritt beobachten kann.

## Framework
**Tkinter** – in Python standardmäßig enthalten, keine zusätzlichen Dependencies.

## Architektur

### Neue Dateien
- `src/bort/gui.py` – GUI-Implementierung

### Geänderte Dateien
- `pyproject.toml` – neuer Entrypoint `bort-gui`
- `README.md` – GUI-Nutzung dokumentieren
- `AGENTS.md` – ggf. GUI-Hinweis ergänzen

## GUI-Elemente
1. **MP3-Datei**: Label + Eingabefeld + "Durchsuchen"-Button (`filedialog.askopenfilename`)
2. **JSON-Marker-Datei**: Label + Eingabefeld + "Durchsuchen"-Button; optional/leer erlaubt
3. **Modell-Datei**: Label + Eingabefeld + "Durchsuchen"-Button
4. **Sprache**: Combobox/Dropdown mit gängigen Sprachen (`de`, `en`, `fr`, `es`, `auto`)
5. **Ausgabeverzeichnis**: Label + Eingabefeld + "Durchsuchen"-Button (`filedialog.askdirectory`)
6. **Formate**: Checkboxes für `txt`, `md`, `csv`, `tsv` (Default: alle aktiviert)
7. **Optionen**: Checkbox "Temporäre WAV behalten"
8. **Aktionen**: "Transkribieren"-Button + "Beenden"
9. **Log/Fortschritt**: Scrollbares Textfeld für Statusmeldungen (Logger-Handler anbinden)

## Threading
- Die Transkription läuft in einem separaten Thread (`threading.Thread`), damit die GUI währenddessen nicht einfriert.
- Fortschritt und Ergebnisse werden über `queue.Queue` oder `tkinter.after()` in den Haupt-Thread zurückgemeldet.
- Der "Transkribieren"-Button wird während der Verarbeitung deaktiviert.

## Fehlerbehandlung
- Dialog-Fenster (`messagebox.showerror` / `messagebox.showinfo`) für Fehler und Erfolg.
- Validierung vor Start: MP3-Datei und Modell müssen ausgewählt sein.

## Implementierungsschritte
1. `gui.py` mit Tkinter-Oberfläche und Threading-Logik implementieren.
2. `pyproject.toml` um `[project.scripts]`-Eintrag `bort-gui` erweitern.
3. Package neu installieren (`pip install -e .`).
4. README.md und AGENTS.md aktualisieren.
5. GUI manuell mit JFK-Sample testen.

## Keine neuen Dependencies
Tkinter ist Teil der Standardbibliothek.

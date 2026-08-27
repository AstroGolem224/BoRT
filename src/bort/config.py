"""Persistente Einstellungen für die GUI."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "bort"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "settings.json"


class Config:
    """Einfacher JSON-basierter Konfigurationsspeicher."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CONFIG_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Lädt die Konfiguration aus der Datei."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._data = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Konfiguration konnte nicht geladen werden: %s", exc)
            self._data = {}

    def save(self) -> None:
        """Speichert die Konfiguration atomar in die Datei.

        Schreibt zuerst ein Tempfile im selben Verzeichnis und ersetzt die
        Zieldatei per ``os.replace``, damit ein Absturz mittendrin nie eine
        halb geschriebene settings.json hinterlässt.
        """
        try:
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            )
            temporary = Path(handle.name)
            try:
                with handle:
                    json.dump(self._data, handle, indent=2, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Konfiguration konnte nicht gespeichert werden: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        """Gibt einen Wert zurück oder den Default."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Setzt einen Wert."""
        self._data[key] = value

    def get_path(self, key: str) -> Path | None:
        """Gibt einen Pfad-Wert zurück, falls vorhanden und gültig."""
        value = self._data.get(key)
        if value:
            return Path(value)
        return None

    def set_path(self, key: str, path: Path | None) -> None:
        """Speichert einen Pfad-Wert."""
        if path:
            self._data[key] = str(path)

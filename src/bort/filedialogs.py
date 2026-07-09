"""Native Datei-/Ordner-Dialoge.

Nutzt die nativen Dateidialoge des Systems (kdialog auf KDE, zenity auf GTK-
Desktops, tkinter.filedialog als Fallback), damit der Anwender den gewohnten
Komfort hat: Rechtsklick-Kontextmenü, Mausrad-Scroll, „Neuer Ordner", Lese-
zeichen, Tastatur-Shortcuts usw.  Die öffentliche API ist kompatibel zur
vorherigen Implementierung.

Öffentliche API:
    ask_directory(parent, title, initialdir) -> str | None
    ask_open_file(parent, title, filetypes, initialdir) -> str | None
    ask_save_file(parent, title, filetypes, initialdir,
                  defaultextension, initialfile) -> str | None
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# --- Backends, die wir nutzen können ----------------------------------- #
_HAS_KDIALOG = shutil.which("kdialog") is not None
_HAS_ZENITY = shutil.which("zenity") is not None


class _BackendError(Exception):
    """Wird geworfen, wenn ein Backend nicht gestartet werden konnte
    (z. B. Binary nicht gefunden).  Ein _BackendError berechtigt den
    Dispatcher zum Fallback auf das nächste Backend.  Ein normales
    Abbrechen durch den Nutzer liefert dagegen ``None`` und löst KEINEN
    Fallback aus."""


# ====================================================================== #
#  kdialog (KDE) – primäres Backend auf KDE-Systemen
# ====================================================================== #
def _kdialog(
    args: list[str],
    parent: object | None = None,
) -> str | None:
    """Ruft kdialog auf und gibt dessen Stdout (Pfad) oder None zurück.

    Unterscheidet:
      - Nutzer bricht ab (returncode != 0)  → ``None`` (kein Fallback)
      - kdialog nicht startbar              → ``_BackendError`` (Fallback)
    """
    cmd = ["kdialog"]
    # An das Elternfenster andocken, damit der Dialog modal darüber liegt.
    if parent is not None and hasattr(parent, "winfo_id"):
        try:
            winid = parent.winfo_id()
            if winid:
                cmd += ["--attach", str(winid)]
        except Exception:
            pass
    cmd += args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        # Backend nicht startbar → Fallback erlauben
        raise _BackendError(str(exc)) from exc
    if proc.returncode != 0:
        # Nutzer hat abgebrochen → KEIN Fallback, sofort None
        return None
    out = proc.stdout.strip()
    # kdialog liefert URLs ggf. mit file://
    if out.startswith("file://"):
        out = out[7:]
    return out if out else None


def _kdialog_filter(filetypes: list[tuple[str, str]] | None) -> str:
    """Wandelt tkinter-Style filetypes in einen kdialog-Filter-String um.

    kdialog/Qt erwartet die Filter als positionales Argument im Format::

        "Label1 (*.ext1 *.ext2);;Label2 (*.ext3);;Alle (*)"

    Der Filter wird direkt nach dem Startordner übergeben, NICHT über ein
    ``--filter``-Flag (das akzeptiert kdialog für Dateidialoge nicht).
    """
    if not filetypes:
        return ""
    parts = []
    for name, pattern in filetypes:
        pats = " ".join(p for p in pattern.split() if p)
        # "*.*" bedeutet "alle Dateien" → in Qt "Alle (*)"
        if pats in ("*.*", "*"):
            parts.append(f"{name} (*)")
        else:
            parts.append(f"{name} ({pats})")
    return ";;".join(parts)


# ====================================================================== #
#  zenity (GTK) – sekundäres Backend
# ====================================================================== #
def _zenity(
    args: list[str],
) -> str | None:
    """Ruft zenity auf und gibt den Pfad oder None zurück.

    Unterscheidet:
      - Nutzer bricht ab (returncode != 0)  → ``None`` (kein Fallback)
      - zenity nicht startbar              → ``_BackendError`` (Fallback)
    """
    cmd = ["zenity", "--file-selection"] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        raise _BackendError(str(exc)) from exc
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if out.startswith("file://"):
        out = out[7:]
    return out if out else None


def _zenity_filetypes(filter_arg: list[tuple[str, str]] | None) -> list[str]:
    """Wandelt filetypes in zenity --file-filter Argumente um."""
    if not filter_arg:
        return []
    out: list[str] = []
    for name, pattern in filter_arg:
        pats = " ".join(p for p in pattern.split() if p)
        # zenity will: --file-filter="Name | *.ext1 *.ext2"
        out.append("--file-filter")
        out.append(f"{name} | {pats}")
    return out


# ====================================================================== #
#  tkinter-Backend (Fallback)
# ====================================================================== #
def _tk_ask(
    mode: str,
    parent: object | None,
    title: str,
    filetypes: list[tuple[str, str]] | None,
    initialdir: str | Path | None,
    defaultextension: str,
    initialfile: str,
) -> str | None:
    """Fallback über tkinter.filedialog (voll funktionsfähig, nativ)."""
    import tkinter.filedialog as fd

    initialdir_str = str(initialdir) if initialdir else None
    kwargs: dict = {
        "title": title,
        "initialdir": initialdir_str,
    }
    if parent is not None:
        # Nur übergeben, wenn es ein echtes Tk-Widget ist.
        if hasattr(parent, "winfo_id"):
            kwargs["parent"] = parent  # type: ignore[arg-type]

    if mode == "dir":
        return fd.askdirectory(**kwargs)
    if mode == "open":
        return fd.askopenfilename(filetypes=filetypes or [], **kwargs)
    if mode == "save":
        if defaultextension:
            kwargs["defaultextension"] = defaultextension
        if initialfile:
            kwargs["initialfile"] = initialfile
        return fd.asksaveasfilename(filetypes=filetypes or [], **kwargs)
    return None


# ====================================================================== #
#  Dispatcher
# ====================================================================== #
def _ask(
    mode: str,
    parent: object | None,
    title: str,
    filetypes: list[tuple[str, str]] | None,
    initialdir: str | Path | None,
    defaultextension: str,
    initialfile: str,
) -> str | None:
    """Wählt das beste verfügbare Backend und führt den Dialog aus."""

    init = str(initialdir) if initialdir else None
    if init and not os.path.isdir(init):
        init = os.path.expanduser("~")
    elif not init:
        init = os.path.expanduser("~")

    # --- kdialog ------------------------------------------------------
    if _HAS_KDIALOG:
        args: list[str] = []
        if mode == "dir":
            args.append("--getexistingdirectory")
        elif mode == "open":
            args.append("--getopenfilename")
        elif mode == "save":
            args.append("--getsavefilename")

        if title:
            args += ["--title", title]

        # Positionale Argumente: Startordner (mit "--" abgrenzen), dann Filter
        start_path = init
        if mode == "save" and initialfile:
            start_path = os.path.join(init, initialfile)
        args += ["--", start_path]

        if mode != "dir":
            flt = _kdialog_filter(filetypes)
            if flt:
                args.append(flt)

        try:
            return _kdialog(args, parent=parent)
        except _BackendError:
            pass  # kdialog nicht startbar → nächsten Versuch

    # --- zenity -------------------------------------------------------
    if _HAS_ZENITY:
        args: list[str] = []
        if mode == "dir":
            args.append("--directory")
        if title:
            args += ["--title", title]
        if init:
            args += ["--filename", init + "/" if mode == "dir" else init + "/"]
        if mode == "save":
            args.append("--save")
            if initialfile and init:
                args[-1] = "--save"
                args += ["--filename", os.path.join(init, initialfile)]
        args += _zenity_filetypes(filetypes) if mode != "dir" else []
        try:
            return _zenity(args)
        except _BackendError:
            pass  # zenity nicht startbar → Fallback auf tkinter

    # --- tkinter-Fallback --------------------------------------------
    return _tk_ask(
        mode=mode, parent=parent, title=title,
        filetypes=filetypes, initialdir=initialdir,
        defaultextension=defaultextension, initialfile=initialfile,
    )


# ====================================================================== #
#  Öffentliche API
# ====================================================================== #
def ask_directory(
    parent: object | None = None,
    title: str = "Ordner auswählen",
    initialdir: str | Path | None = None,
) -> str | None:
    """Öffnet einen nativen Ordner-Auswahl-Dialog."""
    return _ask(
        mode="dir", parent=parent, title=title,
        filetypes=None, initialdir=initialdir,
        defaultextension="", initialfile="",
    )


def ask_open_file(
    parent: object | None = None,
    title: str = "Datei auswählen",
    filetypes: list[tuple[str, str]] | None = None,
    initialdir: str | Path | None = None,
) -> str | None:
    """Öffnet einen nativen Datei-Auswahl-Dialog."""
    return _ask(
        mode="open", parent=parent, title=title,
        filetypes=filetypes, initialdir=initialdir,
        defaultextension="", initialfile="",
    )


def ask_save_file(
    parent: object | None = None,
    title: str = "Speichern unter",
    filetypes: list[tuple[str, str]] | None = None,
    initialdir: str | Path | None = None,
    defaultextension: str = "",
    initialfile: str = "",
) -> str | None:
    """Öffnet einen nativen Speichern-unter-Dialog."""
    return _ask(
        mode="save", parent=parent, title=title,
        filetypes=filetypes, initialdir=initialdir,
        defaultextension=defaultextension, initialfile=initialfile,
    )

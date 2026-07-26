"""Einstiegspunkt für die gebündelte ausführbare Datei (PyInstaller).

Startet die GUI (Default). Wird die Datei mit Argumenten aufgerufen, wird die
CLI gestartet, so dass die ausführbare Datei auch als CLI-Tool dient.
"""
from __future__ import annotations

import os
import sys

# -----------------------------------------------------------------------------
# Verwende das systemweite Tcl/Tk 8.6, damit CustomTkinter nicht gegen eine
# inkompatible/interne Tk-9.x-Library gelinkt (was unter XWayland zu XCB-
# Crashes führt).
# -----------------------------------------------------------------------------
if not os.environ.get("TK_LIBRARY"):
    system_tk = "/usr/lib/tk8.6"
    if os.path.isdir(system_tk):
        os.environ["TK_LIBRARY"] = system_tk
if not os.environ.get("TCL_LIBRARY"):
    system_tcl = "/usr/lib/tcl8.6"
    if os.path.isdir(system_tcl):
        os.environ["TCL_LIBRARY"] = system_tcl


def main() -> int:
    # Wenn Argumente übergeben werden, in den CLI-Modus wechseln.
    # Argumente, die der PyInstaller-Bootloader einfügt (beginnen mit
    # PyInstaller-Optionen), werden ignoriert.
    real_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(real_args) > 0 or any(
        a in sys.argv for a in ("--help", "-h", "--backend", "-b")
    ):
        from bort.cli import main as cli_main
        return cli_main()

    # Default: GUI starten
    from bort.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# Start-Wrapper für BoR Transcriber (BoRT).
#
# Problem: Tk 8.6 crasht unter XWayland 24.1.x (KDE Plasma/Wayland) mit einem
# XCB-Assertion-Fehler ("Extra reply data still left in queue"), weil XWayland
# fehlerhafte XKB-Replies (~215 kB / ~146 kB / ~109 kB) sendet, die den XCB-
# Queue überlaufen lassen.  Das betrifft schon tkinter.Tk().
#
# Lösung: LD_PRELOAD-Shim (libxcb_reply_fix_shim.so), der recv() abfängt und
# Replies größer als 50 kB verwirft.  Das ist ressourcenschonend und das
# Fenster erscheint direkt auf dem Wayland-Desktop (kein Xephyr/Xvfb nötig).

# Systemweites Tcl/Tk 8.6 verwenden
export TK_LIBRARY="/usr/lib/tk8.6"
export TCL_LIBRARY="/usr/lib/tcl8.6"
export NO_AT_BRIDGE=1

APP_DIR="/home/itiger013/Dokumente/Github/BoRT"
APP_BIN="$APP_DIR/dist/bort/bort"
SHIM="$APP_DIR/scripts/libxcb_reply_fix_shim.so"

# Shim laden, falls vorhanden
if [ -f "$SHIM" ]; then
    export LD_PRELOAD="$SHIM${LD_PRELOAD:+:$LD_PRELOAD}"
fi

exec "$APP_BIN" "$@"

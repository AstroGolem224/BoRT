/* xwayland_fix_shim.c — LD_PRELOAD-Shim
 *
 * Workaround für Tk-8.6-Crash unter XWayland:
 *   "[xcb] Extra reply data still left in queue / broken X extension library"
 *
 * Ursache: XWayland liefert für XGetWindowProperty fehlerhafte Replies
 * mit "Extra reply data", die den XCB-Queue überlaufen lassen.
 *
 * Lösung: XGetWindowProperty komplett durch eine leere Property ersetzen.
 * Tk bekommt dadurch keine X-Properties (Ressource-Manager, InterpRegistry),
 * aber das ist unkritisch für die Funktionalität.
 *
 * Build: gcc -shared -fPIC -o libxwayland_fix_shim.so xwayland_fix_shim.c -ldl
 * Use:   LD_PRELOAD=./libxwayland_fix_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <X11/Xatom.h>

typedef int (*XGetWindowProperty_t)(Display*, Window, Atom, long, long, Bool,
                                     Atom, Atom*, int*, unsigned long*,
                                     unsigned long*, unsigned char**);

int XGetWindowProperty(Display *display, Window w, Atom property,
                       long long_offset, long long_length, Bool delete,
                       Atom req_type, Atom *actual_type_return,
                       int *actual_format_return,
                       unsigned long *nitems_return,
                       unsigned long *bytes_after_return,
                       unsigned char **prop_return) {
    fprintf(stderr, "[shim] XGetWindowProperty(%lu) → leer\n", (unsigned long)property);
    /* Immer leer zurückgeben, ohne XWayland zu kontaktieren */
    if (actual_type_return) *actual_type_return = XA_STRING;
    if (actual_format_return) *actual_format_return = 8;
    if (nitems_return) *nitems_return = 0;
    if (bytes_after_return) *bytes_after_return = 0;
    if (prop_return) {
        *prop_return = (unsigned char *) malloc(1);
        if (*prop_return) (*prop_return)[0] = '\0';
    }
    return Success;
}

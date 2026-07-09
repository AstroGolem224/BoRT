/* xkb_disable_shim.c — LD_PRELOAD-Shim (v3)
 *
 * Deaktiviert die XKEYBOARD-Erweiterung vollständig, um den Tk-8.6-Crash
 * unter XWayland zu umgehen.
 *
 * XWayland 24.1.x liefert gigantische fehlerhafte XKB-Replies (408 kB!),
 * die den XCB-Queue überlaufen lassen.  Dieser Shim blockiert alle Xkb-*
 * Funktionen, die Replies erzeugen, sowie XQueryExtension("XKEYBOARD").
 *
 * Build: gcc -shared -fPIC -o libxkb_disable_shim.so xkb_disable_shim.c -ldl -lX11
 * Use:   LD_PRELOAD=./libxkb_disable_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <X11/Xlib.h>
#include <X11/XKBlib.h>

/* --- XkbQueryExtension blockieren --- */
typedef Bool (*XkbQueryExtension_t)(Display*, int*, int*, int*, int*, int*);
Bool XkbQueryExtension(Display *display, int *opcode_rtrn, int *event_rtrn,
                       int *error_rtrn, int *major_in_out, int *minor_in_out) {
    return False;
}

/* --- XkbUseExtension blockieren --- */
typedef Bool (*XkbUseExtension_t)(Display*, int*, int*);
Bool XkbUseExtension(Display *display, int *major_in_out, int *minor_in_out) {
    return False;
}

/* --- XkbGetMap blockieren (liefert die große Reply) --- */
typedef XkbDescPtr (*XkbGetMap_t)(Display*, unsigned int, unsigned int);
XkbDescPtr XkbGetMap(Display *display, unsigned int which, unsigned int device_spec) {
    return NULL;
}

/* --- XkbGetCompatMap blockieren --- */
typedef Status (*XkbGetCompatMap_t)(Display*, unsigned int, XkbDescPtr);
Status XkbGetCompatMap(Display *display, unsigned int which, XkbDescPtr xkb) {
    return 0;
}

/* --- XkbGetIndicatorMap blockieren --- */
typedef int (*XkbGetIndicatorMap_t)(Display*, unsigned long, XkbDescPtr);
int XkbGetIndicatorMap(Display *display, unsigned long which, XkbDescPtr xkb) {
    return 0;
}

/* --- XkbGetNames blockieren --- */
typedef Status (*XkbGetNames_t)(Display*, unsigned int, XkbDescPtr);
Status XkbGetNames(Display *display, unsigned int which, XkbDescPtr xkb) {
    return 0;  /* BadAlloc */
}

/* --- XkbGetControls blockieren --- */
typedef Status (*XkbGetControls_t)(Display*, unsigned long, XkbDescPtr);
Status XkbGetControls(Display *display, unsigned long which, XkbDescPtr xkb) {
    return 0;
}

/* --- XkbGetGeometry blockieren --- */
typedef Status (*XkbGetGeometry_t)(Display*, XkbDescPtr, Atom);
Status XkbGetGeometry(Display *display, XkbDescPtr xkb, Atom name) {
    return 0;
}

/* --- XkbGetKeyboard blockieren (ältere API) --- */
typedef XkbDescPtr (*XkbGetKeyboard_t)(Display*, unsigned int, unsigned int);
XkbDescPtr XkbGetKeyboard(Display *display, unsigned int which, unsigned int device_spec) {
    return NULL;
}

/* --- XkbGetState blockieren --- */
typedef Status (*XkbGetState_t)(Display*, unsigned int, XkbStatePtr);
Status XkbGetState(Display *display, unsigned int device_spec, XkbStatePtr state_return) {
    memset(state_return, 0, sizeof(XkbStateRec));
    return Success;
}

/* --- XkbGetKeyboardByName blockieren (verursacht die 408-kB-Reply!) --- */
typedef XkbDescPtr (*XkbGetKeyboardByName_t)(Display*, unsigned int, XkbComponentNamesPtr,
                                        unsigned int, unsigned int, Bool);
XkbDescPtr XkbGetKeyboardByName(Display *display, unsigned int device_spec,
                          XkbComponentNamesPtr names, unsigned int want,
                          unsigned int need, Bool load) {
    return NULL;  /* Keine Tastatur-Belegung laden → keine Reply */
}

/* --- XkbGetUpdatedMap blockieren --- */
typedef int (*XkbGetUpdatedMap_t)(Display*, unsigned int, XkbDescPtr);
int XkbGetUpdatedMap(Display *display, unsigned int which, XkbDescPtr xkb) {
    return 0;
}

/* --- XkbGetMapChanges blockieren --- */
typedef Status (*XkbGetMapChanges_t)(Display*, XkbDescPtr, XkbMapChangesPtr);
Status XkbGetMapChanges(Display *display, XkbDescPtr xkb, XkbMapChangesPtr changes) {
    return 0;
}

/* --- XkbGetNamedDeviceIndicator blockieren --- */
/* (Signatur ist Header-abhängig, wir lassen sie weg) */

/* --- XkbGetXlibControls blockieren --- */
typedef unsigned int (*XkbGetXlibControls_t)(Display*);
unsigned int XkbGetXlibControls(Display *display) {
    return 0;
}

/* --- XQueryExtension für XKEYBOARD blockieren --- */
typedef Bool (*XQueryExtension_t)(Display*, const char*, int*, int*, int*);
Bool XQueryExtension(Display *display, const char *name,
                     int *major_opcode_return,
                     int *first_event_return,
                     int *first_error_return) {
    if (name && strcmp(name, "XKEYBOARD") == 0) {
        *major_opcode_return = 0;
        *first_event_return = 0;
        *first_error_return = 0;
        return False;
    }
    static XQueryExtension_t real = NULL;
    if (!real) real = (XQueryExtension_t) dlsym(RTLD_NEXT, "XQueryExtension");
    if (real) return real(display, name, major_opcode_return,
                          first_event_return, first_error_return);
    return False;
}

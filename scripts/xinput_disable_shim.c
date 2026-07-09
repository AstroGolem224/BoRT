/* xinput_disable_shim.c — LD_PRELOAD-Shim (v3)
 *
 * Deaktiviert XInputExtension (XI2) unter XWayland, um den Tk-8.6-Crash
 *   "[xcb] Extra reply data still left in queue / broken X extension library"
 * zu umgehen.
 *
 * XWayland 24.1.x sendet fehlerhafte/gigantische XI2-Replies, die Tk's
 * XCB-Queue überlaufen lassen.
 *
 * Build: gcc -shared -fPIC -o libxinput_disable_shim.so xinput_disable_shim.c -ldl
 * Use:   LD_PRELOAD=./libxinput_disable_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <X11/Xlib.h>

typedef Bool (*XQueryExtension_t)(Display*, const char*, int*, int*, int*);

Bool XQueryExtension(Display *display, const char *name,
                     int *major_opcode_return,
                     int *first_event_return,
                     int *first_error_return) {
    /* XInputExtension blockieren */
    if (name && strcmp(name, "XInputExtension") == 0) {
        fprintf(stderr, "[shim] XInputExtension blockiert\n");
        *major_opcode_return = 0;
        *first_event_return = 0;
        *first_error_return = 0;
        return False;
    }
    static XQueryExtension_t real = NULL;
    if (!real) {
        real = (XQueryExtension_t) dlsym(RTLD_NEXT, "XQueryExtension");
    }
    if (real) {
        return real(display, name, major_opcode_return,
                    first_event_return, first_error_return);
    }
    return False;
}

/* Auch XOpenDevice / XIQueryVersion blockieren, falls Tk XI2 direkt nutzt */
typedef int (*XIQueryVersion_t)(void*, int*, int*);
int XIQueryVersion(void *display, int *major_inout, int *minor_inout) {
    fprintf(stderr, "[shim] XIQueryVersion blockiert\n");
    return 1;  /* BadRequest */
}

/* xge_disable_shim.c — LD_PRELOAD-Shim
 *
 * Deaktiviert die "Generic Event Extension" (XGE) unter XWayland, um den
 * Tk-8.6-Crash in Tk_HandleEvent zu umgehen.
 *
 * Crash: "[xcb] Extra reply data still left in queue / broken X extension
 * library" in Tk_HandleEvent+0x462, verursacht durch fehlerhafte
 * XGE-Event-Replies von XWayland 24.1.x.
 *
 * Build: gcc -shared -fPIC -o libxge_disable_shim.so xge_disable_shim.c -ldl
 * Use:   LD_PRELOAD=./libxge_disable_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>
#include <X11/Xlib.h>

typedef Bool (*XQueryExtension_t)(Display*, const char*, int*, int*, int*);

Bool XQueryExtension(Display *display, const char *name,
                     int *major_opcode_return,
                     int *first_event_return,
                     int *first_error_return) {
    /* XGE (Generic Event Extension) blockieren */
    if (name && (strcmp(name, "Generic Event Extension") == 0 ||
                 strcmp(name, "XInputExtension") == 0)) {
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

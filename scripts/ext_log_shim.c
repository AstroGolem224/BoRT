/* ext_log_shim.c — loggt alle XQueryExtension-Aufrufe */
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
    fprintf(stderr, "[ext] XQueryExtension: %s\n", name ? name : "(null)");
    fflush(stderr);
    static XQueryExtension_t real = NULL;
    if (!real) {
        real = (XQueryExtension_t) dlsym(RTLD_NEXT, "XQueryExtension");
    }
    if (real) {
        Bool r = real(display, name, major_opcode_return,
                      first_event_return, first_error_return);
        fprintf(stderr, "[ext]   → %s (major=%d)\n", r ? "OK" : "FAIL", *major_opcode_return);
        fflush(stderr);
        return r;
    }
    return False;
}

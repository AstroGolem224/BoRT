/* xtrace_shim.c — erweitertes Logging mit XGetWindowProperty-Blockade */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/XKBlib.h>

typedef Bool (*XkbQueryExtension_t)(Display*, int*, int*, int*, int*, int*);
Bool XkbQueryExtension(Display *d, int *a, int *b, int *c, int *e, int *f) {
    fprintf(stderr, "[X] XkbQueryExtension aufgerufen\n");
    fflush(stderr);
    return False;
}

typedef Atom (*XInternAtom_t)(Display*, const char*, Bool);
typedef int (*XGetWindowProperty_t)(Display*, Window, Atom, long, long, Bool,
                                     Atom, Atom*, int*, unsigned long*,
                                     unsigned long*, unsigned char**);
typedef int (*XSync_t)(Display*, Bool);
typedef int (*XFlush_t)(Display*);
typedef Status (*XGetWMProtocols_t)(Display*, Window, Atom**, int*);
typedef int (*XNextEvent_t)(Display*, XEvent*);
typedef int (*XPeekEvent_t)(Display*, XEvent*);
typedef Bool (*XQueryExtension_t)(Display*, const char*, int*, int*, int*);
typedef Window (*XCreateWindow_t)(Display*, Window, int, int, unsigned int,
                                   unsigned int, unsigned int, int, unsigned int,
                                   Visual*, unsigned long, XSetWindowAttributes*);
typedef int (*XMapWindow_t)(Display*, Window);

Atom XInternAtom(Display *display, const char *name, Bool only_if_exists) {
    fprintf(stderr, "[X] XInternAtom(%s)\n", name ? name : "(null)");
    fflush(stderr);
    static XInternAtom_t real = NULL;
    if (!real) real = (XInternAtom_t) dlsym(RTLD_NEXT, "XInternAtom");
    if (real) return real(display, name, only_if_exists);
    return None;
}

int XGetWindowProperty(Display *display, Window w, Atom property,
                       long long_offset, long long_length, Bool delete,
                       Atom req_type, Atom *actual_type_return,
                       int *actual_format_return,
                       unsigned long *nitems_return,
                       unsigned long *bytes_after_return,
                       unsigned char **prop_return) {
    fprintf(stderr, "[X] XGetWindowProperty(atom=%lu) → blockiert\n", (unsigned long)property);
    fflush(stderr);
    /* Immer leer zurückgeben */
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

int XSync(Display *display, Bool discard) {
    fprintf(stderr, "[X] XSync(discard=%d)\n", discard);
    fflush(stderr);
    static XSync_t real = NULL;
    if (!real) real = (XSync_t) dlsym(RTLD_NEXT, "XSync");
    if (real) return real(display, discard);
    return 0;
}

int XFlush(Display *display) {
    fprintf(stderr, "[X] XFlush\n");
    fflush(stderr);
    static XFlush_t real = NULL;
    if (!real) real = (XFlush_t) dlsym(RTLD_NEXT, "XFlush");
    if (real) return real(display);
    return 0;
}

Bool XQueryExtension(Display *display, const char *name,
                     int *major_opcode_return,
                     int *first_event_return,
                     int *first_error_return) {
    fprintf(stderr, "[X] XQueryExtension(%s)\n", name ? name : "(null)");
    fflush(stderr);
    static XQueryExtension_t real = NULL;
    if (!real) real = (XQueryExtension_t) dlsym(RTLD_NEXT, "XQueryExtension");
    if (real) return real(display, name, major_opcode_return,
                          first_event_return, first_error_return);
    return False;
}

Status XGetWMProtocols(Display *display, Window w, Atom **protocols_return,
                       int *count_return) {
    fprintf(stderr, "[X] XGetWMProtocols(win=%lu)\n", (unsigned long)w);
    fflush(stderr);
    static XGetWMProtocols_t real = NULL;
    if (!real) real = (XGetWMProtocols_t) dlsym(RTLD_NEXT, "XGetWMProtocols");
    if (real) return real(display, w, protocols_return, count_return);
    return 0;
}

Window XCreateWindow(Display *display, Window parent, int x, int y,
                     unsigned int width, unsigned int height,
                     unsigned int border_width, int depth,
                     unsigned int class, Visual *visual,
                     unsigned long valuemask,
                     XSetWindowAttributes *attributes) {
    fprintf(stderr, "[X] XCreateWindow(%dx%d)\n", width, height);
    fflush(stderr);
    static XCreateWindow_t real = NULL;
    if (!real) real = (XCreateWindow_t) dlsym(RTLD_NEXT, "XCreateWindow");
    if (real) return real(display, parent, x, y, width, height, border_width,
                          depth, class, visual, valuemask, attributes);
    return 0;
}

int XMapWindow(Display *display, Window w) {
    fprintf(stderr, "[X] XMapWindow(win=%lu)\n", (unsigned long)w);
    fflush(stderr);
    static XMapWindow_t real = NULL;
    if (!real) real = (XMapWindow_t) dlsym(RTLD_NEXT, "XMapWindow");
    if (real) return real(display, w);
    return 0;
}

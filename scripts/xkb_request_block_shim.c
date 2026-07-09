/* xkb_request_block_shim.c — LD_PRELOAD-Shim (einfach & ressourcenschonend)
 *
 * Workaround für den Tk-8.6-Crash unter XWayland 24.1.x:
 *   "[xcb] Extra reply data still left in queue / broken X extension library"
 *
 * Ursache: libX11 sendet XKB-Requests (XkbGetMap minor=1, XkbGetNames
 * minor=8), liest die Replies aber nie ab.  XWayland liefert fehlerhafte
 * ~215 kB große Replies, die im XCB-Queue bleiben und beim nächsten Reply-
 * erwartenden Request zum Assertion-Crash führen.
 *
 * Lösung: writev() als globale Funktion überschreiben und XKB-Requests
 * mit Reply-erzeugendem Minor-Opcode abfangen, bevor sie an XWayland
 * gesendet werden.  Der Request wird verworfen (Erfolg vortäuscht), sodass
 * keine fehlerhafte Reply erzeugt wird.
 *
 * Das ist ressourcenschonend (kein Polling, keine Schleife) und blockiert
 * nur die wenigen XKB-Requests beim Start.
 *
 * Build: gcc -shared -fPIC -o libxkb_request_block_shim.so xkb_request_block_shim.c -ldl
 * Use:   LD_PRELOAD=./libxkb_request_block_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/uio.h>
#include <sys/types.h>
#include <sys/socket.h>

/* XKEYBOARD-Extension-Opcode.
   Auf diesem System (XWayland) ist es 135.  Wir versuchen ihn zur Laufzeit
   zu ermitteln, fallback auf 135. */
static int xkb_opcode = 135;

/* XKB-Minor-Opcodes, die Replies erzeugen, die von libX11/Tk nie abgeholt
   werden (und daher die fehlerhaften XWayland-Replies im Queue lassen).
   XkbUseExtension (minor=0) wird NICHT blockiert, da Tk ihre Reply erwartet. */
static int is_reply_producing_xkb_minor(int minor) {
    switch (minor) {
        case 1:  /* XkbGetMap ← verursacht 215 kB Reply! */
        case 8:  /* XkbGetNames ← verursacht große Reply */
        case 10: /* XkbGetGeometry ← verursacht SEHR große Reply */
        case 14: /* XkbGetKeyboardByName */
        case 4:  /* XkbGetCompatMap */
        case 6:  /* XkbGetIndicatorMap */
        case 11: /* XkbGetControls */
        case 17: /* XkbGetInfo */
        case 21: /* XkbGetMapChanges */
            return 1;
        default:
            return 0;
    }
}

/* --- writev überschreiben (libxcb nutzt writev!) --- */
typedef ssize_t (*writev_t)(int, const struct iovec *, int);

ssize_t writev(int fd, const struct iovec *iov, int iovcnt) {
    static writev_t real_writev = NULL;
    if (!real_writev) real_writev = (writev_t) dlsym(RTLD_NEXT, "writev");
    if (!real_writev) return -1;

    /* XKB-Request mit Reply-erzeugendem Minor-Opcode blockieren */
    if (xkb_opcode > 0 && iovcnt > 0 && iov && iov[0].iov_len >= 4) {
        unsigned char *data = (unsigned char *) iov[0].iov_base;
        int opcode = data[0];
        int minor = data[1];

        if (opcode == xkb_opcode && is_reply_producing_xkb_minor(minor)) {
            fprintf(stderr, "[shim] XKB-Request (minor=%d) blockiert\n", minor);
            int req_len = data[2] | (data[3] << 8);
            return req_len * 4;  /* Erfolg vortäuschen, nichts senden */
        }
    }

    return real_writev(fd, iov, iovcnt);
}

/* --- write überschreiben (manche Requests werden über write gesendet) --- */
typedef ssize_t (*write_t)(int, const void *, size_t);

ssize_t write(int fd, const void *buf, size_t count) {
    static write_t real_write = NULL;
    if (!real_write) real_write = (write_t) dlsym(RTLD_NEXT, "write");
    if (!real_write) return -1;

    if (xkb_opcode > 0 && count >= 4) {
        unsigned char *data = (unsigned char *) buf;
        int opcode = data[0];
        int minor = data[1];

        if (opcode == xkb_opcode && is_reply_producing_xkb_minor(minor)) {
            fprintf(stderr, "[shim] write: XKB-Request (minor=%d) blockiert\n", minor);
            int req_len = data[2] | (data[3] << 8);
            return req_len * 4;
        }
    }

    return real_write(fd, buf, count);
}

/* --- sendmsg überschreiben (XCB nutzt manchmal sendmsg) --- */
typedef ssize_t (*sendmsg_t)(int, const struct msghdr *, int);

ssize_t sendmsg(int fd, const struct msghdr *msg, int flags) {
    static sendmsg_t real_sendmsg = NULL;
    if (!real_sendmsg) real_sendmsg = (sendmsg_t) dlsym(RTLD_NEXT, "sendmsg");
    if (!real_sendmsg) return -1;

    if (xkb_opcode > 0 && msg && msg->msg_iovlen > 0 && msg->msg_iov
        && msg->msg_iov[0].iov_len >= 4) {
        unsigned char *data = (unsigned char *) msg->msg_iov[0].iov_base;
        int opcode = data[0];
        int minor = data[1];

        if (opcode == xkb_opcode && is_reply_producing_xkb_minor(minor)) {
            fprintf(stderr, "[shim] sendmsg: XKB-Request (minor=%d) blockiert\n", minor);
            int req_len = data[2] | (data[3] << 8);
            return req_len * 4;
        }
    }

    return real_sendmsg(fd, msg, flags);
}

/* xcb_reply_fix_shim.c — LD_PRELOAD-Shim
 *
 * Workaround für den Tk-8.6-Crash unter XWayland 24.1.x:
 *   "[xcb] Extra reply data still left in queue / broken X extension library"
 *
 * Ursache: XWayland sendet nach einer 32-Byte-Reply-Header (recvmsg) zwei
 * riesige recv-Blöcke (215 kB + 267 kB) als "Extra reply data", die den
 * XCB-Queue überlaufen lassen.
 *
 * Lösung: recv() abfangen (das ist die Funktion, die libxcb nutzt!) und
 * Antworten, die größer als ein Schwellwert sind, verwerfen.
 *
 * Build: gcc -shared -fPIC -o libxcb_reply_fix_shim.so xcb_reply_fix_shim.c -ldl
 * Use:   LD_PRELOAD=./libxcb_reply_fix_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/socket.h>

/* Schwellwert: Replies größer als 50 kB sind verdächtig
   (normale X-Replies sind selten > 8 kB; die fehlerhafte XWayland-
   XKB-Extra-Reply ist 215 kB + 219 kB + 48 kB) */
#define MAX_REPLY_SIZE 51200

/* --- recv abfangen (libxcb nutzt recv, nicht recvfrom!) --- */
typedef ssize_t (*recv_t)(int, void *, size_t, int);

ssize_t recv(int sockfd, void *buf, size_t len, int flags) {
    static recv_t real = NULL;
    if (!real) real = (recv_t) dlsym(RTLD_NEXT, "recv");
    if (!real) return -1;

    ssize_t n = real(sockfd, buf, len, flags);

    /* Große Replies verwerfen – das sind die fehlerhaften XWayland-XKB-
       Extra-Reply-Daten, die den XCB-Queue überlaufen lassen. */
    if (n > MAX_REPLY_SIZE) {
        fprintf(stderr, "[shim] recv(fd=%d): große Reply (%zd bytes) verworfen\n", sockfd, n);
        /* EAGAIN zurückgeben, damit XCB den Lese-Versuch wiederholt und
           dabei die Reply als beendet ansieht. */
        errno = EAGAIN;
        return -1;
    }
    return n;
}

/* --- recvfrom auch abfangen (falls andere Code-Pfade es nutzen) --- */
typedef ssize_t (*recvfrom_t)(int, void *, size_t, int,
                               struct sockaddr *, socklen_t *);

ssize_t recvfrom(int sockfd, void *buf, size_t len, int flags,
                 struct sockaddr *src_addr, socklen_t *addrlen) {
    static recvfrom_t real = NULL;
    if (!real) real = (recvfrom_t) dlsym(RTLD_NEXT, "recvfrom");
    if (!real) return -1;

    ssize_t n = real(sockfd, buf, len, flags, src_addr, addrlen);

    if (n > MAX_REPLY_SIZE) {
        fprintf(stderr, "[shim] recvfrom(fd=%d): große Reply (%zd bytes) verworfen\n", sockfd, n);
        errno = EAGAIN;
        return -1;
    }
    return n;
}

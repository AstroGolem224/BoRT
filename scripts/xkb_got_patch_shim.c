/* xkb_got_patch_shim.c — LD_PRELOAD-Shim mit GOT-Patching
 *
 * Workaround für den Tk-8.6-Crash unter XWayland 24.1.x:
 *   "[xcb] Extra reply data still left in queue / broken X extension library"
 *
 * libxcb nutzt writev() via GOT (R_X86_64_GLOB_DAT), was von LD_PRELOAD
 * nicht zuverlässig überschrieben wird.  Dieser Shim patcht zur Laufzeit
 * die GOT von libxcb, um writev durch unsere eigene Funktion zu ersetzen,
 * die XKB-Requests mit Reply-erzeugendem Minor-Opcode blockiert.
 *
 * Build: gcc -shared -fPIC -o libxkb_got_patch_shim.so xkb_got_patch_shim.c -ldl
 * Use:   LD_PRELOAD=./libxkb_got_patch_shim.so python3 script.py
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/uio.h>
#include <sys/socket.h>
#include <elf.h>
#include <link.h>
#include <stdlib.h>
#include <sys/mman.h>
/* XKEYBOARD-Extension-Opcode (135 auf diesem System) */
static int xkb_opcode = 135;

/* XKB-Minor-Opcodes, die Replies erzeugen */
static int is_reply_producing_xkb_minor(int minor) {
    switch (minor) {
        case 0:  /* XkbUseExtension */
        case 1:  /* XkbGetMap ← 215 kB Reply */
        case 4:  /* XkbGetCompatMap */
        case 6:  /* XkbGetIndicatorMap */
        case 8:  /* XkbGetNames ← große Reply */
        case 10: /* XkbGetGeometry */
        case 11: /* XkbGetControls */
        case 14: /* XkbGetKeyboardByName */
        case 17: /* XkbGetInfo */
        case 19: /* XkbGetState */
        case 21: /* XkbGetMapChanges */
            return 1;
        default:
            return 0;
    }
}

/* Original writev (wird via dlsym geholt) */
static ssize_t (*real_writev)(int, const struct iovec *, int) = NULL;

/* Unsere writev-Ersatzfunktion: filtert XKB-Requests heraus */
static ssize_t my_writev(int fd, const struct iovec *iov, int iovcnt) {
    if (!real_writev) {
        real_writev = dlsym(RTLD_NEXT, "writev");
    }
    if (!real_writev) return -1;

    if (xkb_opcode > 0 && iovcnt > 0 && iov && iov[0].iov_len >= 4) {
        unsigned char *data = (unsigned char *) iov[0].iov_base;
        int opcode = data[0];
        int minor = data[1];

        if (opcode == xkb_opcode && is_reply_producing_xkb_minor(minor)) {
            fprintf(stderr, "[shim] writev: XKB-Request (minor=%d) blockiert\n", minor);
            int req_len = data[2] | (data[3] << 8);
            return req_len * 4;  /* Erfolg vortäuschen */
        }
    }

    return real_writev(fd, iov, iovcnt);
}

/* Original sendmsg */
static ssize_t (*real_sendmsg)(int, const struct msghdr *, int) = NULL;

/* Unsere sendmsg-Ersatzfunktion */
static ssize_t my_sendmsg(int fd, const struct msghdr *msg, int flags) {
    if (!real_sendmsg) {
        real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
    }
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

/* GOT einer Bibliothek patchen: ersetzt alle Referenzen auf `symbol`
   durch `new_func`. */
static void patch_got(void *lib_handle, const char *symbol, void *new_func) {
    if (!lib_handle || !symbol || !new_func) return;

    struct link_map *lm = NULL;
    if (dlinfo(lib_handle, RTLD_DI_LINKMAP, &lm) != 0 || !lm) return;

    /* Über die Relokationstabelle iterieren */
    Elf64_Sym *symtab = NULL;
    const char *strtab = NULL;
    Elf64_Rela *rela = NULL;
    size_t relasz = 0;

    for (Elf64_Dyn *dyn = lm->l_ld; dyn->d_tag != DT_NULL; dyn++) {
        switch (dyn->d_tag) {
            case DT_SYMTAB:  symtab = (Elf64_Sym *) dyn->d_un.d_ptr; break;
            case DT_STRTAB:  strtab = (const char *) dyn->d_un.d_ptr; break;
            case DT_JMPREL:  rela = (Elf64_Rela *) dyn->d_un.d_ptr; break;
            case DT_PLTRELSZ: relasz = dyn->d_un.d_val; break;
            case DT_RELA:    rela = (Elf64_Rela *) dyn->d_un.d_ptr; break;
            case DT_RELASZ:  relasz = dyn->d_un.d_val; break;
        }
    }
    if (!symtab || !strtab || !rela || !relasz) return;

    size_t rela_count = relasz / sizeof(Elf64_Rela);
    for (size_t i = 0; i < rela_count; i++) {
        int symidx = ELF64_R_SYM(rela[i].r_info);
        if (symidx == 0) continue;
        const char *symname = strtab + symtab[symidx].st_name;
        if (strcmp(symname, symbol) != 0) continue;

        /* GOT-Eintrag finden */
        void **got_entry = (void **) (lm->l_addr + rela[i].r_offset);

        /* Seite beschreibbar machen */
        long pagesize = sysconf(_SC_PAGESIZE);
        void *page = (void *)((long)got_entry & ~(pagesize - 1));
        size_t page_len = (long)got_entry - (long)page + sizeof(void *);
        if (mprotect(page, page_len, PROT_READ | PROT_WRITE) != 0) continue;

        /* GOT-Eintrag überschreiben */
        *got_entry = new_func;

        /* Seite wieder schreibschützen (optional, sicherer ohne) */
        /* mprotect(page, page_len, PROT_READ); */

        fprintf(stderr, "[shim] GOT-Patch: %s in %s → %p\n",
                symbol, lm->l_name ? lm->l_name : "?", new_func);
    }
}

/* Konstruktor: wird beim Laden der Bibliothek ausgeführt */
__attribute__((constructor))
static void init(void) {
    fprintf(stderr, "[shim] Initialisiere XKB-Request-Blocker\n");

    /* writev aus libc holen */
    real_writev = dlsym(RTLD_NEXT, "writev");
    real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");

    /* GOT von libxcb patchen */
    void *libxcb = dlopen("libxcb.so.1", RTLD_NOW | RTLD_GLOBAL);
    if (libxcb) {
        patch_got(libxcb, "writev", (void *) my_writev);
        patch_got(libxcb, "sendmsg", (void *) my_sendmsg);
        /* libX11 nutzt auch writev */
        void *libX11 = dlopen("libX11.so.6", RTLD_NOW | RTLD_GLOBAL);
        if (libX11) {
            patch_got(libX11, "writev", (void *) my_writev);
            patch_got(libX11, "sendmsg", (void *) my_sendmsg);
        }
    } else {
        fprintf(stderr, "[shim] WARNUNG: libxcb.so.1 nicht gefunden: %s\n", dlerror());
    }
}

"""Moderne Dialog-Fenster im BoR-Card-Stil.

Ersetzt die altmodischen tkinter messageboxes durch gestylte
CustomTkinter-Toplevel-Fenster mit BoR-Farbtheme.
"""

from __future__ import annotations

import customtkinter as ctk

from .theme import COLORS


def show_info(
    parent: ctk.CTk | ctk.CTkToplevel | None,
    title: str,
    message: str,
) -> None:
    """Zeigt einen Info-Dialog im BoR-Stil."""
    _show_dialog(parent, title, message, kind="info")


def show_error(
    parent: ctk.CTk | ctk.CTkToplevel | None,
    title: str,
    message: str,
) -> None:
    """Zeigt einen Fehler-Dialog im BoR-Stil."""
    _show_dialog(parent, title, message, kind="error")


def _show_dialog(
    parent: ctk.CTk | ctk.CTkToplevel | None,
    title: str,
    message: str,
    kind: str = "info",
) -> None:
    """Baut einen modalen Dialog im BoR-Stil."""
    dlg = ctk.CTkToplevel(parent)
    dlg.title(title)
    dlg.geometry("520x300")
    dlg.minsize(440, 240)
    dlg.columnconfigure(0, weight=1)
    dlg.rowconfigure(1, weight=1)
    ctk.set_appearance_mode("dark")

    # Icon + Titel
    icon = "✓" if kind == "info" else "⚠"
    icon_color = COLORS["success"] if kind == "info" else COLORS["error"]

    header = ctk.CTkFrame(dlg, fg_color=COLORS["card_bg"], corner_radius=14)
    header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))
    header.columnconfigure(1, weight=1)

    ctk.CTkLabel(
        header, text=icon, font=ctk.CTkFont(size=32),
        text_color=icon_color,
    ).grid(row=0, column=0, padx=20, pady=14)

    ctk.CTkLabel(
        header, text=title,
        font=ctk.CTkFont(size=18, weight="bold"),
        text_color=COLORS["text"],
    ).grid(row=0, column=1, sticky="w", pady=14)

    # Nachricht (scrollbar falls lang)
    msg_frame = ctk.CTkFrame(dlg, fg_color=COLORS["card_bg"], corner_radius=14)
    msg_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=8)
    msg_frame.columnconfigure(0, weight=1)
    msg_frame.rowconfigure(0, weight=1)

    msg = ctk.CTkTextbox(
        msg_frame, wrap="word",
        fg_color=COLORS["input_bg"],
        border_color=COLORS["border"], border_width=1,
        corner_radius=10,
    )
    msg.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
    msg.insert("1.0", message)
    msg.configure(state="disabled")

    # OK-Button
    ctk.CTkButton(
        dlg, text="OK", width=140, height=42,
        font=ctk.CTkFont(size=14, weight="bold"),
        fg_color=COLORS["coral"],
        hover_color=COLORS["coral_hover"],
        command=dlg.destroy,
    ).grid(row=2, column=0, pady=(8, 20))

    dlg.transient(parent)
    dlg.grab_set()
    dlg.focus_set()
    dlg.bind("<Return>", lambda e: dlg.destroy())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    # Zentrieren relativ zum Parent
    dlg.update_idletasks()
    if parent is not None:
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - 520) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - 300) // 2
            dlg.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

"""Farb- und Theme-Definitionen für die Transkriptions-App.

Orientiert am BoR-Partner-App-Logo: schwarzer Hintergrund, Korallenrot-Akzent.
Modernes Card-basiertes Design mit klaren Hierarchien.
"""

import customtkinter as ctk

# --- Markenfarben (BoR-Stil) ---
CORAL = "#F97455"  # Korallenrot (BoR-Akzent)
CORAL_HOVER = "#E55F40"
CORAL_DIM = "#B8503A"
BG_DARK = "#0E0E10"  # fast schwarz (BoR-Hintergrund)
BG_CARD = "#1A1A1E"  # Card-Hintergrund (etwas heller)
BG_INPUT = "#242428"  # Eingabefelder
BORDER = "#2A2A30"
TEXT_PRIMARY = "#F5F5F5"
TEXT_MUTED = "#8A8A92"
SUCCESS = "#4ADE80"
ERROR = "#F87171"


def apply_theme() -> None:
    """Wendet das BoR-Farbschema global an."""
    ctk.set_appearance_mode("dark")

    # Eigenes Farb-Theme überschreibt das CTK-Default-Theme
    ctk.set_default_color_theme("dark-blue")  # Basis, wir überschreiben manuell


def theme_widget(widget: ctk.CTkBaseClass) -> None:
    """Wendet Markenfarben auf ein Widget an (optional, für Feintuning)."""
    # Generic helper – wird aktuell nicht zwingend gebraucht, da wir die
    # Farben direkt beim Erstellen der Widgets setzen.
    pass


# Farbkürzel für direkte Nutzung beim Widget-Bau
COLORS = {
    "coral": CORAL,
    "coral_hover": CORAL_HOVER,
    "card_bg": BG_CARD,
    "input_bg": BG_INPUT,
    "border": BORDER,
    "text": TEXT_PRIMARY,
    "muted": TEXT_MUTED,
    "success": SUCCESS,
    "error": ERROR,
}

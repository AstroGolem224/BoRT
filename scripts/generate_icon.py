"""Generate the desktop app logo (PNG) inspired by the BoR partner-app logo.

OBSOLET (2026-07-24): assets/icon*.png ist jetzt ein handgemachtes Neon-Icon
(Waveform + Playhead + "T"). Dieses Skript NICHT mehr ausführen — es würde
das Icon mit dem alten generierten Design überschreiben.

Style: black background, coral-red accent (~#F97455), audio waveform icon.
Produces assets/icon.png (1024x1024) and assets/icon-256.png.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = Path("/home/itiger013/Dokumente/Github/BoRT/assets")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 1024
BG = (0, 0, 0)            # black background (wie BoR-Logo)
ACCENT = (249, 116, 85)   # korallenrot (BoR-Akzentfarbe)
ACCENT_DIM = (180, 80, 55)
WHITE = (245, 245, 245)


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG + (255,))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2

    # --- Äußerer Ring (Korallenrot, dünn) ---
    ring_r = int(size * 0.42)
    ring_w = max(4, size // 110)
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=ACCENT + (255,),
        width=ring_w,
    )

    # --- Wellenform (zentrale Audio-Balken) ---
    # 7 Balken, mittige Symmetrie, Korallenrot mit Verlauf
    n_bars = 7
    bar_w = int(size * 0.045)
    gap = int(size * 0.022)
    total_w = n_bars * bar_w + (n_bars - 1) * gap
    start_x = cx - total_w // 2

    # Höhen: symmetric, center tallest
    heights = [0.18, 0.30, 0.52, 0.70, 0.52, 0.30, 0.18]
    max_h = int(size * 0.28)

    for i, h in enumerate(heights):
        bh = int(max_h * h)
        x0 = start_x + i * (bar_w + gap)
        y0 = cy - bh // 2
        x1 = x0 + bar_w
        y1 = cy + bh // 2
        # rounded bars
        draw.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=bar_w // 2,
            fill=ACCENT + (255,),
        )

    # --- "T" als kleinen Akzent unten (Transkription) ---
    # Subtiler Punkt im unteren Bereich
    dot_r = int(size * 0.012)
    draw.ellipse(
        [cx - dot_r, int(cy + size * 0.20) - dot_r,
         cx + dot_r, int(cy + size * 0.20) + dot_r],
        fill=ACCENT + (255,),
    )

    # --- Soft glow (subtle) ---
    glow = img.filter(ImageFilter.GaussianBlur(radius=size // 80))
    # Composite: glow underneath, sharp on top
    final = Image.new("RGBA", (size, size), BG + (255,))
    final = Image.alpha_composite(final, glow)
    final = Image.alpha_composite(final, img)

    return final


def main() -> None:
    # Haupt-Icon (1024)
    logo = draw_logo(SIZE)
    logo.save(OUT_DIR / "icon.png")
    # Kleinere Variante (256) für Window-Icon
    logo.resize((256, 256), Image.LANCZOS).save(OUT_DIR / "icon-256.png")
    # 48px für Taskleiste
    logo.resize((48, 48), Image.LANCZOS).save(OUT_DIR / "icon-48.png")
    print(f"Logos gespeichert in {OUT_DIR}/")


if __name__ == "__main__":
    main()

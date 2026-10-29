"""Generate a one-page diagnostic test page as a PDF (Pillow only)."""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DPI = 150
W, H = int(8.5 * DPI), int(11 * DPI)  # Letter; CUPS scales to other sizes


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_test_page(dest: Path, station: str, printer: str, reference: str, logo: Path | None = None) -> None:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    m = int(0.5 * DPI)
    d.rectangle([m, m, W - m, H - m], outline="black", width=3)
    y = m + 40
    if logo and logo.exists():
        with Image.open(logo) as wm:
            wm = wm.convert("RGBA")
            ratio = (W - 2 * m - 160) / wm.width
            wm = wm.resize((int(wm.width * ratio), int(wm.height * ratio)))
            img.paste(wm, (m + 80, y), wm)
            y += wm.height + 40
    d.text((m + 80, y), "PRINT HUB TEST PAGE", fill="black", font=_font(56))
    y += 90
    for label, value in (
        ("Station", station),
        ("Printer", printer),
        ("Reference", reference),
        ("Generated", time.strftime("%Y-%m-%d %H:%M:%S %Z")),
    ):
        d.text((m + 80, y), f"{label}:", fill="#555555", font=_font(32))
        d.text((m + 330, y), value, fill="black", font=_font(32))
        y += 52
    y += 30
    swatches = [("Black", "#000000"), ("Cyan", "#00FFFF"), ("Magenta", "#FF00FF"), ("Yellow", "#FFFF00"),
                ("Fruitstand orange", "#C2410C")]
    sw = (W - 2 * m - 160) // len(swatches)
    for i, (name, color) in enumerate(swatches):
        x = m + 80 + i * sw
        d.rectangle([x, y, x + sw - 20, y + 160], fill=color)
        d.text((x, y + 175), name, fill="black", font=_font(24))
    y += 250
    steps = 11
    gw = (W - 2 * m - 160) // steps
    for i in range(steps):
        v = int(255 * i / (steps - 1))
        x = m + 80 + i * gw
        d.rectangle([x, y, x + gw, y + 90], fill=(v, v, v), outline="black")
    d.text((m + 80, y + 105), "Gray steps 0% → 100%. Black-and-white jobs should show every step.", fill="black", font=_font(24))
    y += 190
    d.text((m + 80, y), "▲ TOP OF PAGE — this arrow should point to the top edge in portrait.", fill="black", font=_font(28))
    d.text((m + 80, H - m - 120), "The border is 0.5 in from every edge. Missing border = margins clipped by the printer.",
           fill="black", font=_font(24))
    d.text((m + 80, H - m - 80), "Seeing this page means the printer produced paper. The hub cannot detect that on its own.",
           fill="black", font=_font(24))
    img.save(dest, "PDF", resolution=DPI)

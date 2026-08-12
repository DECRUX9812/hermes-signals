from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "hermes-signals-discord.png"
W, H = 1800, 1013

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/lato"),
    Path("/usr/share/fonts/truetype/dejavu"),
]


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for name in names:
            path = directory / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


REG = font(["Lato-Regular.ttf", "DejaVuSans.ttf"], 24)
MED = font(["Lato-Medium.ttf", "DejaVuSans.ttf"], 24)
BOLD = font(["Lato-Bold.ttf", "DejaVuSans-Bold.ttf"], 24)
BLACK = font(["Lato-Black.ttf", "DejaVuSans-Bold.ttf"], 24)
MONO = font(["DejaVuSansMono.ttf"], 24)

WHITE = (239, 246, 255)
MUTED = (143, 165, 194)
SUBTLE = (74, 100, 135)
CYAN = (48, 224, 255)
PURPLE = (173, 108, 255)
RED = (255, 79, 112)
AMBER = (255, 181, 71)
GREEN = (91, 225, 157)
PANEL = (14, 28, 50)
PANEL_2 = (18, 36, 63)
LINE = (42, 69, 103)


def gradient_background() -> Image.Image:
    image = Image.new("RGB", (W, H))
    pixels = image.load()
    for y in range(H):
        for x in range(W):
            t = y / H
            r = int(5 + 5 * t)
            g = int(12 + 12 * t)
            b = int(27 + 22 * t)
            glow = max(0.0, 1.0 - math.hypot((x - 1450) / 650, (y - 120) / 430))
            r += int(13 * glow)
            g += int(7 * glow)
            b += int(24 * glow)
            pixels[x, y] = (min(r, 255), min(g, 255), min(b, 255))
    return image


def glow_dot(base: Image.Image, xy: tuple[int, int], color: tuple[int, int, int], radius: int) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = xy
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, 170))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    base.paste(layer, (0, 0), layer)


def rounded(draw: ImageDraw.ImageDraw, box, radius=18, fill=PANEL, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw, xy, value, fnt, fill=WHITE, anchor=None):
    draw.text(xy, value, font=fnt, fill=fill, anchor=anchor)


def pill(draw, x, y, label, fill, text_fill=WHITE, fnt=MONO, pad_x=14, height=30):
    box = draw.textbbox((0, 0), label, font=fnt)
    width = box[2] - box[0] + pad_x * 2
    rounded(draw, (x, y, x + width, y + height), radius=height // 2, fill=fill)
    text(draw, (x + width // 2, y + height // 2), label, fnt, text_fill, anchor="mm")
    return width


def draw_grid(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    for x in range(0, W, 80):
        draw.line((x, 0, x, H), fill=(13, 31, 54), width=1)
    for y in range(0, H, 80):
        draw.line((0, y, W, y), fill=(13, 31, 54), width=1)


def draw_trace_panel(draw: ImageDraw.ImageDraw) -> None:
    x, y, w, h = 1050, 92, 660, 335
    rounded(draw, (x, y, x + w, y + h), radius=24, fill=(10, 23, 43), outline=(38, 67, 103), width=2)
    text(draw, (x + 30, y + 28), "ONE TRACE. FULL STORY.", MONO.font_variant(size=17), CYAN)
    text(draw, (x + w - 30, y + 29), "SIGNAL / 001", MONO.font_variant(size=15), SUBTLE, anchor="ra")

    rows = [
        ("01", "update_record(id=42)", "TIMEOUT", RED),
        ("02", "update_record(id=42)", "TIMEOUT", RED),
        ("03", 'final: "successfully updated"', "CLAIM", AMBER),
    ]
    row_y = y + 90
    for index, (num, label, status, color) in enumerate(rows):
        cy = row_y + index * 78
        if index < 2:
            draw.line((x + 43, cy + 30, x + 43, cy + 78), fill=LINE, width=2)
        draw.ellipse((x + 30, cy + 18, x + 56, cy + 44), fill=color)
        text(draw, (x + 43, cy + 31), num, MONO.font_variant(size=11), (5, 14, 28), anchor="mm")
        text(draw, (x + 80, cy + 19), label, MONO.font_variant(size=20), WHITE)
        pill(draw, x + w - 146, cy + 14, status, (28, 47, 72), color, MONO.font_variant(size=13), pad_x=12, height=28)

    draw.line((x + 30, y + 295, x + w - 30, y + 295), fill=LINE, width=1)
    text(draw, (x + 30, y + 316), "The failure is the relationship between events.", MED.font_variant(size=17), MUTED)
    text(draw, (x + w - 30, y + 316), "→ false-success", MONO.font_variant(size=17), RED, anchor="ra")


def draw_signal_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    accent,
    number: str,
    title: str,
    severity: str,
    body: str,
    evidence: str,
) -> None:
    rounded(draw, (x, y, x + w, y + h), radius=22, fill=PANEL, outline=(35, 61, 94), width=2)
    draw.rectangle((x, y, x + 7, y + h), fill=accent)
    text(draw, (x + 28, y + 28), number, MONO.font_variant(size=17), accent)
    pill(draw, x + w - 118, y + 22, severity, (28, 47, 72), accent, MONO.font_variant(size=12), pad_x=10, height=25)
    text(draw, (x + 28, y + 67), title, BLACK.font_variant(size=28), WHITE)
    # Deliberately short lines for screenshot readability.
    lines = body.split("\n")
    for i, line in enumerate(lines):
        text(draw, (x + 28, y + 116 + i * 27), line, MED.font_variant(size=18), MUTED)
    draw.line((x + 28, y + h - 64, x + w - 28, y + h - 64), fill=LINE, width=1)
    text(draw, (x + 28, y + h - 42), evidence, MONO.font_variant(size=14), SUBTLE)


def main() -> None:
    image = gradient_background()
    glow_dot(image, (1540, 150), PURPLE, 260)
    glow_dot(image, (190, 860), CYAN, 210)
    draw = ImageDraw.Draw(image)
    draw_grid(image, draw)

    # Header.
    text(draw, (90, 58), "HERMES SIGNALS  /  OPEN SOURCE PLUGIN", MONO.font_variant(size=17), CYAN)
    pill(draw, 1395, 44, "NO GPU  ·  NO API KEY", (25, 54, 83), CYAN, MONO.font_variant(size=13), pad_x=14, height=30)

    text(draw, (90, 116), "Catch the failure", BLACK.font_variant(size=76), WHITE)
    text(draw, (90, 198), "before it becomes fact.", BLACK.font_variant(size=76), CYAN)
    text(draw, (95, 302), "A local-first quality layer for AI agents.", MED.font_variant(size=28), MUTED)
    text(
        draw,
        (95, 347),
        "Deterministic filters turn messy traces into reviewable signals.",
        REG.font_variant(size=22),
        MUTED,
    )

    draw_trace_panel(draw)

    # Architecture strip.
    x, y, w, h = 90, 450, 1620, 96
    rounded(draw, (x, y, x + w, y + h), radius=18, fill=(11, 25, 46), outline=(33, 63, 98), width=2)
    text(draw, (x + 30, y + 18), "THE LOOP", MONO.font_variant(size=14), SUBTLE)
    steps = [
        ("01", "cheap deterministic filter", CYAN),
        ("02", "compact evidence", PURPLE),
        ("03", "human review", GREEN),
    ]
    sx = x + 205
    for i, (num, label, color) in enumerate(steps):
        text(draw, (sx, y + 48), num, MONO.font_variant(size=15), color, anchor="lm")
        text(draw, (sx + 39, y + 48), label, MED.font_variant(size=21), WHITE, anchor="lm")
        if i < len(steps) - 1:
            draw.line((sx + 300, y + 48, sx + 347, y + 48), fill=LINE, width=2)
            draw.polygon([(sx + 347, y + 48), (sx + 336, y + 41), (sx + 336, y + 55)], fill=LINE)
        sx += 470

    # Signal cards.
    card_y = 578
    card_w = 375
    gap = 40
    draw_signal_card(
        draw,
        90,
        card_y,
        card_w,
        286,
        RED,
        "01",
        "FALSE SUCCESS",
        "HIGH",
        "Claims completion\nafter tool failure.",
        "failed result + success claim",
    )
    draw_signal_card(
        draw,
        90 + card_w + gap,
        card_y,
        card_w,
        286,
        AMBER,
        "02",
        "RETRY LOOP",
        "MEDIUM",
        "Repeats the same\nfailing strategy.",
        "same tool + same args",
    )
    draw_signal_card(
        draw,
        90 + 2 * (card_w + gap),
        card_y,
        card_w,
        286,
        PURPLE,
        "03",
        "UNVERIFIED CHANGE",
        "MEDIUM",
        "Reports a change\nwithout verification.",
        "mutation − test/readback",
    )
    draw_signal_card(
        draw,
        90 + 3 * (card_w + gap),
        card_y,
        card_w,
        286,
        GREEN,
        "04",
        "SECRET RISK",
        "CRITICAL",
        "Finds credential-like\nmaterial. Redacts output.",
        "local signal · no raw secret",
    )

    # Footer / CTA.
    draw.line((90, 905, 1710, 905), fill=(35, 61, 94), width=2)
    text(draw, (90, 930), "TEST IT  ·  BREAK IT  ·  TELL US WHAT'S WRONG", MONO.font_variant(size=16), CYAN)
    text(draw, (1710, 930), "github.com/DECRUX9812/hermes-signals", MONO.font_variant(size=16), MUTED, anchor="ra")
    text(
        draw,
        (90, 970),
        "hermes plugins install DECRUX9812/hermes-signals --enable",
        MONO.font_variant(size=18),
        WHITE,
    )
    text(draw, (1710, 970), "MIT  ·  LOCAL-FIRST  ·  v0.1", MONO.font_variant(size=14), SUBTLE, anchor="ra")

    image.save(OUT, format="PNG", optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()

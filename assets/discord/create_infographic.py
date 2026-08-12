from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "hermes-signals-discord.png"
W, H = 1600, 1200

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/lato"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/noto"),
]

PAPER = (226, 198, 146)
PAPER_LIGHT = (239, 216, 171)
INK = (12, 25, 36)
NAVY = (17, 39, 58)
BLUE = (34, 67, 84)
RUST = (177, 66, 32)
ORANGE = (209, 82, 30)
CREAM = (246, 224, 179)
MUTED = (181, 154, 105)
OLIVE = (94, 111, 63)
RED = (199, 48, 39)


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for name in names:
            path = directory / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


TITLE = font(["Lato-Heavy.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 100)
TITLE_SMALL = font(["Lato-Heavy.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 54)
HEAD = font(["Lato-Heavy.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 46)
HEAD_SMALL = font(["Lato-Bold.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 32)
BODY = font(["Lato-Regular.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf"], 28)
BODY_BOLD = font(["Lato-Bold.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 29)
MONO = font(["DejaVuSansMono.ttf"], 27)
MONO_SMALL = font(["DejaVuSansMono.ttf"], 21)


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fnt, fill):
    draw.text(xy, value, font=fnt, fill=fill, anchor="mm")


def fit_font(text: str, names: list[str], max_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(max_size, 14, -2):
        fnt = font(names, size)
        if fnt.getbbox(text)[2] <= max_width:
            return fnt
    return font(names, 14)


def add_texture(image: Image.Image) -> None:
    random.seed(20260811)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(10500):
        x = random.randrange(W)
        y = random.randrange(H)
        shade = random.choice([(25, 21, 13, 16), (255, 243, 201, 18), (74, 42, 21, 10)])
        radius = random.choice([1, 1, 1, 2])
        draw.ellipse((x, y, x + radius, y + radius), fill=shade)
    for _ in range(80):
        x = random.randrange(W)
        y = random.randrange(H)
        draw.line((x, y, x + random.randrange(14, 80), y + random.randrange(-3, 4)), fill=(45, 30, 15, 13), width=1)
    image.alpha_composite(layer)


def draw_outer_frame(draw: ImageDraw.ImageDraw) -> None:
    rounded(draw, (22, 22, W - 22, H - 22), 27, fill=PAPER, outline=INK, width=11)
    rounded(draw, (39, 39, W - 39, H - 39), 18, fill=None, outline=(91, 55, 28), width=3)
    rounded(draw, (48, 48, W - 48, H - 48), 15, fill=None, outline=(246, 218, 167), width=2)


def draw_agent_illustration(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    # A deliberately simple screen-print style agent silhouette, not a detailed UI.
    draw.ellipse((1110, 53, 1512, 455), fill=ORANGE, outline=(232, 131, 66), width=3)
    draw.arc((1150, 95, 1470, 410), 205, 337, fill=(236, 155, 82), width=5)
    # Hair / head.
    draw.polygon(
        [(1250, 122), (1282, 93), (1340, 87), (1382, 111), (1415, 145), (1390, 196), (1265, 202), (1225, 168)],
        fill=INK,
    )
    draw.ellipse((1260, 132, 1398, 255), fill=CREAM)
    draw.polygon(
        [(1265, 148), (1237, 118), (1285, 109), (1330, 103), (1388, 120), (1407, 157),
         (1377, 148), (1357, 130), (1304, 139)],
        fill=INK,
    )
    # Face profile and neck.
    draw.polygon([(1375, 179), (1412, 194), (1390, 210), (1373, 205)], fill=CREAM)
    draw.rectangle((1320, 229, 1375, 274), fill=CREAM)
    # Coat and collar.
    draw.polygon([(1245, 270), (1326, 244), (1384, 264), (1480, 338), (1450, 455), (1168, 455), (1194, 340)], fill=NAVY)
    draw.polygon([(1325, 248), (1270, 290), (1328, 379), (1372, 271)], fill=CREAM)
    draw.polygon([(1380, 265), (1330, 380), (1375, 455), (1490, 455), (1460, 335)], fill=(8, 23, 35))
    # Magnifier / signal lens.
    draw.ellipse((1150, 316, 1234, 400), outline=CREAM, width=10)
    draw.line((1220, 386, 1264, 430), fill=CREAM, width=11)
    draw.ellipse((1167, 333, 1217, 383), outline=RUST, width=3)
    draw.line((1177, 358, 1207, 358), fill=RUST, width=4)
    # Tiny signal ticks.
    draw.line((1118, 269, 1141, 269), fill=CREAM, width=5)
    draw.line((1112, 285, 1141, 285), fill=CREAM, width=5)
    draw.line((1460, 238, 1488, 238), fill=CREAM, width=5)
    draw.line((1460, 254, 1498, 254), fill=CREAM, width=5)


def draw_header(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    rounded(draw, (58, 58, W - 58, 310), 12, fill=NAVY)
    draw.rectangle((58, 58, 1040, 310), fill=NAVY)
    text_x = 92
    draw.text((text_x, 85), "HERMES", font=TITLE, fill=CREAM, stroke_width=2, stroke_fill=INK)
    draw.text((text_x, 177), "SIGNALS", font=TITLE, fill=ORANGE, stroke_width=2, stroke_fill=INK)
    draw.text((text_x + 7, 274), "LOCAL-FIRST BEHAVIOR QUALITY FOR AI AGENTS", font=HEAD_SMALL, fill=CREAM)
    draw_agent_illustration(image, draw)


def draw_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], kind: str, color, dark=INK) -> None:
    cx, cy = center
    draw.ellipse((cx - 68, cy - 68, cx + 68, cy + 68), fill=color, outline=CREAM, width=4)
    if kind == "false":
        draw.line((cx - 30, cy - 26, cx + 28, cy + 30), fill=dark, width=13)
        draw.line((cx + 28, cy - 26, cx - 30, cy + 30), fill=dark, width=13)
        draw.line((cx - 27, cy - 44, cx + 34, cy - 44), fill=dark, width=9)
    elif kind == "retry":
        draw.arc((cx - 37, cy - 36, cx + 38, cy + 38), 205, 530, fill=dark, width=12)
        draw.polygon([(cx + 30, cy - 38), (cx + 51, cy - 13), (cx + 15, cy - 14)], fill=dark)
        draw.arc((cx - 38, cy - 38, cx + 37, cy + 38), 25, 170, fill=CREAM, width=5)
    elif kind == "change":
        draw.line((cx - 39, cy + 22, cx - 5, cy - 12), fill=dark, width=12)
        draw.line((cx - 5, cy - 12, cx + 36, cy - 36), fill=dark, width=12)
        draw.polygon([(cx + 30, cy - 52), (cx + 52, cy - 38), (cx + 34, cy - 18)], fill=dark)
        draw.line((cx - 40, cy + 42, cx + 41, cy + 42), fill=dark, width=7)
    elif kind == "secret":
        draw.rounded_rectangle((cx - 39, cy - 20, cx + 40, cy + 29), radius=7, outline=dark, width=8)
        draw.arc((cx - 20, cy - 49, cx + 20, cy - 2), 180, 360, fill=dark, width=8)
        draw.line((cx - 24, cy + 5, cx + 24, cy + 5), fill=RED, width=9)
        draw.line((cx - 31, cy + 15, cx + 31, cy + 15), fill=RED, width=9)


def draw_panel(
    draw: ImageDraw.ImageDraw,
    box,
    fill,
    accent,
    title: str,
    subtitle: str,
    icon_kind: str,
    title_fill=CREAM,
    body_fill=CREAM,
) -> None:
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill=fill, outline=CREAM, width=5)
    draw_icon(draw, (x1 + 106, y1 + 94), icon_kind, accent)
    title_font = fit_font(
        title,
        ["Lato-Heavy.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"],
        47,
        x2 - x1 - 250,
    )
    draw.text((x1 + 195, y1 + 48), title, font=title_font, fill=title_fill)
    draw.line((x1 + 195, y1 + 116, x2 - 42, y1 + 116), fill=accent, width=7)
    body_font = fit_font(
        subtitle,
        ["Lato-Bold.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"],
        31,
        x2 - x1 - 242,
    )
    draw.text((x1 + 195, y1 + 143), subtitle, font=body_font, fill=body_fill)


def draw_footer(draw: ImageDraw.ImageDraw) -> None:
    y1, y2 = 960, 1140
    draw.rectangle((58, y1, W - 58, y2), fill=NAVY, outline=CREAM, width=5)
    draw.text((92, y1 + 27), "TRY IT ON YOUR MESSIEST TRACE", font=HEAD_SMALL, fill=ORANGE)
    command = "hermes plugins install DECRUX9812/hermes-signals --enable"
    command_font = fit_font(command, ["DejaVuSansMono.ttf"], 29, 1060)
    draw.text((92, y1 + 78), command, font=command_font, fill=CREAM)
    center_text(draw, (1340, y1 + 48), "TEST IT  ·  BREAK IT", HEAD_SMALL, CREAM)
    center_text(draw, (1340, y1 + 92), "TELL US WHAT'S WRONG", HEAD_SMALL, ORANGE)
    draw.text((92, y2 - 24), "github.com/DECRUX9812/hermes-signals", font=MONO_SMALL, fill=MUTED)
    draw.text(
        (W - 92, y2 - 24),
        "MIT  ·  NO GPU  ·  NO API KEY  ·  NO TELEMETRY",
        font=MONO_SMALL,
        fill=MUTED,
        anchor="ra",
    )


def main() -> None:
    image = Image.new("RGBA", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw_outer_frame(draw)
    draw_header(image, draw)

    grid_left, grid_top = 58, 330
    grid_right, grid_bottom = W - 58, 930
    mid_x = (grid_left + grid_right) // 2
    mid_y = (grid_top + grid_bottom) // 2
    draw_panel(
        draw,
        (grid_left, grid_top, mid_x, mid_y),
        BLUE,
        RED,
        "FALSE SUCCESS",
        "tool failed  →  agent says DONE",
        "false",
    )
    draw_panel(
        draw,
        (mid_x, grid_top, grid_right, mid_y),
        RUST,
        CREAM,
        "RETRY LOOP",
        "same action  →  same failure",
        "retry",
        title_fill=CREAM,
        body_fill=CREAM,
    )
    draw_panel(
        draw,
        (grid_left, mid_y, mid_x, grid_bottom),
        NAVY,
        ORANGE,
        "UNVERIFIED CHANGE",
        "changed  ≠  verified",
        "change",
    )
    draw_panel(
        draw,
        (mid_x, mid_y, grid_right, grid_bottom),
        OLIVE,
        CREAM,
        "SECRET RISK",
        "finds it  +  redacts it",
        "secret",
        title_fill=CREAM,
        body_fill=CREAM,
    )

    draw_footer(draw)
    add_texture(image)

    # Slightly soften the printed edges like the supplied poster references.
    image = image.convert("RGB").filter(ImageFilter.GaussianBlur(0.18))
    image.save(OUT, format="PNG", optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()

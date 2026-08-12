"""Deterministic retro-poster renderer for Hermes Signals launch assets.

Two posters, warm-paper retro style (chunky type, big low-density panels):

- ``hermes-signals-how.png``      — the narrative: agent says done → signals
                                    checks the trace → you get the truth.
- ``hermes-signals-install.png``  — the how-to: two commands, then done.

Self-contained: system fonts only, no remote assets. Regenerate with:
    python3 assets/discord/create_infographic.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT_HOW = ROOT / "hermes-signals-how.png"
OUT_INSTALL = ROOT / "hermes-signals-install.png"
W, H = 1600, 1200

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/lato"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/noto"),
]

PAPER = (226, 198, 146)
INK = (12, 25, 36)
NAVY = (17, 39, 58)
BLUE = (34, 67, 84)
RUST = (177, 66, 32)
ORANGE = (209, 82, 30)
CREAM = (246, 224, 179)
MUTED = (181, 154, 105)
OLIVE = (94, 111, 63)
RED = (199, 48, 39)
WHITE = (255, 250, 240)


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for name in names:
            path = directory / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


TITLE = font(["Lato-Heavy.ttf", "NotoSans-Bold.ttf", "DejaVuSansCondensed-Bold.ttf"], 104)
HEAD = font(["Lato-Heavy.ttf", "NotoSans-Bold.ttf", "DejaVuSansCondensed-Bold.ttf"], 52)
HEAD_SMALL = font(["Lato-Bold.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 34)
BODY = font(["Lato-Regular.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf"], 30)
BODY_BOLD = font(["Lato-Bold.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-Bold.ttf"], 30)
MONO = font(["DejaVuSansMono.ttf"], 34)
MONO_SMALL = font(["DejaVuSansMono.ttf"], 22)
STEP_NUM = font(["Lato-Heavy.ttf", "NotoSans-Bold.ttf", "DejaVuSansCondensed-Bold.ttf"], 120)


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fnt, fill):
    draw.text(xy, value, font=fnt, fill=fill, anchor="mm")


def fit_font(text: str, names: list[str], max_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(max_size, 12, -2):
        fnt = font(names, size)
        if fnt.getbbox(text)[2] <= max_width:
            return fnt
    return font(names, 12)


def add_texture(image: Image.Image) -> None:
    import random

    random.seed(20260812)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(9500):
        x = random.randrange(W)
        y = random.randrange(H)
        shade = random.choice([(25, 21, 13, 16), (255, 243, 201, 18), (74, 42, 21, 10)])
        radius = random.choice([1, 1, 1, 2])
        draw.ellipse((x, y, x + radius, y + radius), fill=shade)
    for _ in range(70):
        x = random.randrange(W)
        y = random.randrange(H)
        draw.line((x, y, x + random.randrange(14, 80), y + random.randrange(-3, 4)), fill=(45, 30, 15, 13), width=1)
    image.alpha_composite(layer)


def draw_outer_frame(draw: ImageDraw.ImageDraw) -> None:
    rounded(draw, (22, 22, W - 22, H - 22), 27, fill=PAPER, outline=INK, width=11)
    rounded(draw, (39, 39, W - 39, H - 39), 18, fill=None, outline=(91, 55, 28), width=3)
    rounded(draw, (48, 48, W - 48, H - 48), 15, fill=None, outline=(246, 218, 167), width=2)


def down_arrow(draw: ImageDraw.ImageDraw, cy: int) -> None:
    cx = W // 2
    draw.line((cx, cy - 12, cx, cy + 22), fill=INK, width=8)
    draw.polygon([(cx, cy + 38), (cx - 26, cy + 8), (cx + 26, cy + 8)], fill=INK)


def speech_bubble(draw: ImageDraw.ImageDraw, box, fill) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, 34, fill=fill, outline=CREAM, width=6)
    tail = (x1 + 120, y2 - 8)
    draw.polygon(
        [(tail[0] - 30, y2 - 4), (tail[0] + 30, y2 - 4), (tail[0], y2 + 34)],
        fill=fill,
    )


# ---------------------------------------------------------------------------
# Poster 1 — HOW IT WORKS (the narrative)
# ---------------------------------------------------------------------------


def poster_how() -> None:
    image = Image.new("RGBA", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw_outer_frame(draw)

    # Header.
    draw.text((92, 92), "CATCH THE LIE", font=TITLE, fill=INK, stroke_width=2, stroke_fill=CREAM)
    draw.text((94, 216), "your agent says done. the trace says otherwise.", font=HEAD_SMALL, fill=NAVY)

    # Panel 1 — the claim.
    speech_bubble(draw, (90, 330, 1510, 520), BLUE)
    center_text(draw, (800, 388), "DONE — DEPLOYED", HEAD, CREAM)
    # Drawn checkmark (no emoji font dependency).
    draw.line((736, 472, 766, 502), fill=CREAM, width=10)
    draw.line((766, 502, 830, 428), fill=CREAM, width=10)
    draw.text((94, 552), "1 · the agent claims it's done", font=BODY, fill=NAVY)
    down_arrow(draw, 620)

    # Panel 2 — the trace.
    rounded(draw, (90, 668, 1510, 872), 26, fill=NAVY, outline=CREAM, width=5)
    draw.text((140, 718), "deploy → exit 1", font=MONO, fill=RED)
    draw.text((140, 782), "deploy → exit 1", font=MONO, fill=RED)
    draw.text((94, 902), "2 · the trace shows what really happened", font=BODY, fill=NAVY)
    down_arrow(draw, 968)

    # Panel 3 — the truth (clear of the inner frame: bottom < 1139).
    rounded(draw, (90, 996, 1510, 1130), 26, fill=RUST, outline=CREAM, width=5)
    draw.text((140, 1022), "FALSE SUCCESS", font=HEAD, fill=CREAM)
    draw.text((140, 1082), "tool failed · the agent claimed success · now you know", font=BODY, fill=CREAM)

    add_texture(image)
    image = image.convert("RGB").filter(ImageFilter.GaussianBlur(0.18))
    image.save(OUT_HOW, format="PNG", optimize=True)
    print(OUT_HOW)


# ---------------------------------------------------------------------------
# Poster 2 — INSTALL (the how-to)
# ---------------------------------------------------------------------------


def poster_install() -> None:
    image = Image.new("RGBA", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw_outer_frame(draw)

    # Header.
    draw.text((92, 88), "INSTALL. SET. FORGET.", font=TITLE, fill=INK, stroke_width=2, stroke_fill=CREAM)
    draw.text((94, 212), "two commands. then it watches for you.", font=HEAD_SMALL, fill=NAVY)

    # Step 1.
    rounded(draw, (90, 300, 1510, 470), 26, fill=BLUE, outline=CREAM, width=5)
    draw.ellipse((140, 330, 250, 440), fill=CREAM)
    center_text(draw, (195, 385), "1", STEP_NUM, BLUE)
    command_1 = "hermes plugins install DECRUX9812/hermes-signals --enable"
    cmd_font = fit_font(command_1, ["DejaVuSansMono.ttf"], 34, 1180)
    draw.text((310, 340), command_1, font=cmd_font, fill=CREAM)
    draw.text((312, 402), "adds the plugin to Hermes", font=BODY, fill=CREAM)

    # Step 2.
    rounded(draw, (90, 510, 1510, 680), 26, fill=NAVY, outline=CREAM, width=5)
    draw.ellipse((140, 540, 250, 650), fill=CREAM)
    center_text(draw, (195, 595), "2", STEP_NUM, NAVY)
    command_2 = "hermes signals setup"
    cmd_font = fit_font(command_2, ["DejaVuSansMono.ttf"], 34, 1180)
    draw.text((310, 550), command_2, font=cmd_font, fill=CREAM)
    draw.text(
        (312, 612),
        "backfills your history · arms monitoring · installs the weekly digest",
        font=BODY,
        fill=CREAM,
    )

    # Step 3 — done.
    rounded(draw, (90, 720, 1510, 890), 26, fill=OLIVE, outline=CREAM, width=5)
    draw.ellipse((140, 750, 250, 860), fill=CREAM)
    center_text(draw, (195, 805), "3", STEP_NUM, OLIVE)
    draw.text((310, 760), "DONE", font=HEAD, fill=CREAM)
    draw.text((312, 824), "you never touch it again", font=BODY, fill=CREAM)

    # What happens next strip.
    rounded(draw, (90, 930, 1510, 1090), 26, fill=PAPER, outline=INK, width=4)
    draw.text((140, 956), "WHAT HAPPENS NEXT", font=HEAD_SMALL, fill=NAVY)
    draw.text((140, 1014), "every turn scanned locally", font=BODY, fill=INK)
    draw.text((560, 1014), "weekly digest on its own", font=BODY, fill=INK)
    draw.text((1030, 1014), "hermes signals doctor", font=BODY, fill=INK)

    draw.text((92, 1128), "remove anytime:  hermes plugins disable hermes-signals", font=MONO_SMALL, fill=NAVY)
    draw.text((1508, 1128), "github.com/DECRUX9812/hermes-signals", font=MONO_SMALL, fill=NAVY, anchor="ra")

    add_texture(image)
    image = image.convert("RGB").filter(ImageFilter.GaussianBlur(0.18))
    image.save(OUT_INSTALL, format="PNG", optimize=True)
    print(OUT_INSTALL)


def main() -> None:
    poster_how()
    poster_install()


if __name__ == "__main__":
    main()

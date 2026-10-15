"""Render the Bus Monitor brand images (icon + logo, light and dark).

Writes Home Assistant brand files into custom_components/bus_monitor/brand/:
icon.png (256), icon@2x.png (512), logo.png (256 high), logo@2x.png (512 high)
and dark_ variants. HACS and the HA UI read these.

    .venv/bin/python scripts/make_brand.py [--font-dir /Library/Fonts]

Fonts: Nunito Sans (SIL Open Font License), Black + Bold weights.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "bus_monitor" / "brand"

NAVY = (30, 41, 59, 255)  # outlines and dark parts
YELLOW = (255, 183, 0, 255)  # school-bus yellow
YELLOW_SHADE = (240, 152, 0, 255)
GLASS = (186, 230, 253, 255)
GLASS_GLARE = (240, 249, 255, 255)
LAMP = (255, 247, 214, 255)
RED = (229, 57, 53, 255)
WHITE = (255, 255, 255, 255)
SLATE = (100, 116, 139, 255)  # dark-mode tint for parts that sit outside the body

UNIT = 1000  # design grid
SS = 4096  # supersampled render size


def _s(v: float) -> int:
    return round(v * SS / UNIT)


def _box(x0, y0, x1, y1):
    return (_s(x0), _s(y0), _s(x1), _s(y1))


def _pin(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, tip: float, fill, grow: float = 0):
    """Map-pin teardrop: a circle plus a triangle down to the tip."""
    r2 = r + grow
    d.ellipse(_box(cx - r2, cy - r2, cx + r2, cy + r2), fill=fill)
    half = r2 * 0.80
    d.polygon(
        [(_s(cx - half), _s(cy + r2 * 0.58)), (_s(cx + half), _s(cy + r2 * 0.58)), (_s(cx), _s(tip + grow * 1.2))],
        fill=fill,
    )


def draw_icon(dark: bool = False) -> Image.Image:
    """The bus front with a location pin. `dark` lightens the parts outside the body
    (mirrors, wheels, bumper) so they stay visible on dark backgrounds."""
    rim = SLATE if dark else NAVY
    bus = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(bus)
    ow = _s(34)  # outline width

    # side mirrors (behind the body)
    for x_arm, x0, x1 in ((150, 52, 112), (850, 888, 948)):
        d.line([(_s(x_arm), _s(430)), (_s((x0 + x1) / 2), _s(430))], fill=rim, width=_s(26))
        d.rounded_rectangle(_box(x0, 380, x1, 540), radius=_s(26), fill=rim)

    # wheels (peek out under the bumper)
    for x0 in (205, 665):
        d.rounded_rectangle(_box(x0, 840, x0 + 130, 965), radius=_s(34), fill=rim)

    # body with a darker lower skirt
    d.rounded_rectangle(_box(150, 150, 850, 850), radius=_s(120), fill=YELLOW, outline=NAVY, width=ow)
    d.rounded_rectangle(_box(150 + 17, 600, 850 - 17, 850 - 17), radius=_s(100), fill=YELLOW_SHADE)
    d.rectangle(_box(150 + 17, 600, 850 - 17, 650), fill=YELLOW_SHADE)

    # roof sign with red flashers
    d.rounded_rectangle(_box(270, 192, 730, 262), radius=_s(30), fill=NAVY)
    for cx in (318, 682):
        d.ellipse(_box(cx - 24, 203, cx + 24, 251), fill=RED)
    for i in range(5):  # amber "lettering" dots
        cx = 410 + i * 45
        d.ellipse(_box(cx - 11, 216, cx + 11, 238), fill=YELLOW)

    # windshield, split in two with a glare stripe
    d.rounded_rectangle(_box(215, 300, 785, 560), radius=_s(46), fill=GLASS, outline=NAVY, width=_s(26))
    d.polygon([(_s(262), _s(540)), (_s(330), _s(318)), (_s(385), _s(318)), (_s(317), _s(540))], fill=GLASS_GLARE)
    d.line([(_s(500), _s(305)), (_s(500), _s(555))], fill=NAVY, width=_s(24))

    # headlights and grille
    for cx in (285, 715):
        d.ellipse(_box(cx - 56, 640, cx + 56, 752), fill=LAMP, outline=NAVY, width=_s(24))
    d.rounded_rectangle(_box(392, 652, 608, 742), radius=_s(26), fill=NAVY)
    for y in (675, 697, 719):
        d.line([(_s(420), _s(y)), (_s(580), _s(y))], fill=YELLOW, width=_s(9))

    # bumper
    d.rounded_rectangle(_box(128, 790, 872, 870), radius=_s(40), fill=rim)

    # Location pin, knocked out of the bus with a transparent gap so it reads at small sizes.
    pcx, pcy, pr, ptip = 845, 168, 112, 372
    knock = Image.new("L", (SS, SS), 0)
    _pin(ImageDraw.Draw(knock), pcx, pcy, pr, ptip, 255, grow=46)
    bus.putalpha(ImageChops.subtract(bus.getchannel("A"), knock))

    pin = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pin)
    _pin(pd, pcx, pcy, pr, ptip, NAVY, grow=17)
    _pin(pd, pcx, pcy, pr, ptip, RED)
    pd.ellipse(_box(pcx - 44, pcy - 44, pcx + 44, pcy + 44), fill=WHITE)

    return Image.alpha_composite(bus, pin)


def trim_square(img: Image.Image, pad_frac: float = 0.02) -> Image.Image:
    """Crop to content, then centre it on a square transparent canvas."""
    content = img.crop(img.getchannel("A").getbbox())
    side = round(max(content.size) * (1 + 2 * pad_frac))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(content, ((side - content.width) // 2, (side - content.height) // 2), content)
    return sq


def draw_logo(icon: Image.Image, height: int, font_dir: Path, dark: bool) -> Image.Image:
    """Icon on the left, 'Bus Monitor' plus a tagline on the right; trimmed."""
    k = 4  # supersample
    h = height * k
    title = ImageFont.truetype(str(font_dir / "NunitoSans-Black.ttf"), round(h * 0.40))
    tag = ImageFont.truetype(str(font_dir / "NunitoSans-Bold.ttf"), round(h * 0.125))
    title_color = (248, 250, 252, 255) if dark else NAVY
    tag_color = (203, 213, 225, 255) if dark else (71, 85, 105, 255)

    title_text, tag_text = "Bus Monitor", "School-bus alerts for Home Assistant"
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tb = probe.textbbox((0, 0), title_text, font=title, anchor="ls")
    gb = probe.textbbox((0, 0), tag_text, font=tag, anchor="ls")
    gap = round(h * 0.09)
    text_w = max(tb[2] - tb[0], gb[2] - gb[0])

    canvas = Image.new("RGBA", (h + gap + text_w + h // 10, h), (0, 0, 0, 0))
    canvas.paste(icon.resize((h, h), Image.LANCZOS), (0, 0))
    d = ImageDraw.Draw(canvas)
    x = h + gap
    title_h = -tb[1]  # cap height above the baseline
    tag_h = -gb[1]
    line_gap = round(h * 0.07)
    block = title_h + line_gap + tag_h
    base1 = (h - block) // 2 + title_h
    d.text((x - tb[0], base1), title_text, font=title, fill=title_color, anchor="ls")
    d.text((x - gb[0] + round(h * 0.006), base1 + line_gap + tag_h), tag_text, font=tag, fill=tag_color, anchor="ls")

    canvas = canvas.crop(canvas.getchannel("A").getbbox())
    scale = height / canvas.height
    return canvas.resize((round(canvas.width * scale), height), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-dir", type=Path, default=Path("/Library/Fonts"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    for dark in (False, True):
        prefix = "dark_" if dark else ""
        icon = trim_square(draw_icon(dark))
        for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
            icon.resize((size, size), Image.LANCZOS).save(OUT / f"{prefix}{name}", optimize=True)
        for name, height in (("logo.png", 256), ("logo@2x.png", 512)):
            draw_logo(icon, height, args.font_dir, dark).save(OUT / f"{prefix}{name}", optimize=True)
    for f in sorted(OUT.iterdir()):
        with Image.open(f) as im:
            print(f"{f.name:20} {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()

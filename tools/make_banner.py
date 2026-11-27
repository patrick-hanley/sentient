"""README banner: the toys' photo on a rounded white card with the name and one line -> docs/img/banner.png

  python tools/make_banner.py        (macOS fonts; falls back to PIL's default elsewhere)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, R = 1600, 600, 36
INK, SOFT, LINE, CHIP, CHIP_INK = "#17181a", "#55585e", "#e3e1dc", "#f3f1ec", "#33363b"


def font(size, index=0, name="/System/Library/Fonts/Avenir Next.ttc"):
    try:
        return ImageFont.truetype(name, size, index=index)
    except OSError:
        return ImageFont.load_default(size)


def main():
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((1, 1, W - 2, H - 2), R, fill="white", outline=LINE, width=2)
    photo = Image.open(ROOT / "deck/img/ref_image1.jpg").convert("RGB")
    ph = H - 60
    photo = photo.resize((round(photo.width * ph / photo.height), ph), Image.LANCZOS)
    card.paste(photo, (W - photo.width - 70, 30))
    x = 84
    d.text((x, 96), "Sentient Toys", font=font(104, 0), fill=INK)                 # Avenir Next Bold
    d.text((x, 236), "Three plush toys that listen, see", font=font(44, 7), fill=SOFT)   # Regular
    d.text((x, 292), "and talk with a child.", font=font(44, 7), fill=SOFT)
    d.text((x, 372), "Everything runs in the house.", font=font(44, 2), fill=INK)        # Demi Bold
    cx, f = x, font(27, 5)                                                         # Medium
    for chip in ("No cloud", "Gemma 4 E2B", "Jetson Orin Nano", "ESP32 toys"):
        w = d.textlength(chip, font=f)
        d.rounded_rectangle((cx, 470, cx + w + 40, 522), 26, fill=CHIP)
        d.text((cx + 20, 480), chip, font=f, fill=CHIP_INK)
        cx += w + 54
    out = ROOT / "docs/img/banner.png"
    card.save(out, optimize=True)
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()

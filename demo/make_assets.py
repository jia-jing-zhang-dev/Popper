"""Render the "scanned page" image used in the demo's screenshot (OCR) step."""

import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "quote.png")

LINES = ["“Vanity and pride are different things,",
         "though the words are often used",
         "synonymously.”"]


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    w, h = 1400, 330
    img = Image.new("RGB", (w, h), (236, 226, 204))
    rnd = random.Random(7)
    px = img.load()
    for _ in range(26000):  # paper grain
        x, y = rnd.randrange(w), rnd.randrange(h)
        d = rnd.randint(-14, 8)
        r, g, b = px[x, y]
        px[x, y] = (r + d, g + d, b + d)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("georgiai.ttf", 64)
    y = 38
    for line in LINES:
        draw.text((70, y), line, font=font, fill=(52, 44, 36))
        y += 88
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    img.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()

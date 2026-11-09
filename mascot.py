"""The bubble face on the card (shown when the desktop cats are off): drawn in code so it stays sharp at any size, with a face per mood.

Moods: happy (default), blink, thinking, talking, worried, celebrate, sleepy.
"""

import math

from PIL import Image, ImageDraw, ImageTk

INK = (31, 36, 48, 255)
CHEEK = (255, 150, 170, 150)
SPARK = (255, 214, 102, 255)
OVERSAMPLE = 4  # draw big, then shrink: smooth edges without Tk anti-aliasing


def draw(mood, size):
    """An RGBA picture of the bubble, `size` pixels square."""
    S = size * OVERSAMPLE
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = S * 0.08
    cx, cy, r = S / 2, S / 2 + S * 0.02, S / 2 - pad

    # body: a soft radial gradient from a light upper-left to a deeper blue rim
    for i in range(40, 0, -1):
        k = i / 40
        rr = r * k
        ox, oy = -r * 0.18 * (1 - k), -r * 0.22 * (1 - k)
        c = (int(70 + 110 * (1 - k)), int(160 + 70 * (1 - k)), 255, 255)
        d.ellipse((cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr), fill=c)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(40, 120, 220, 255), width=int(S * 0.03))
    # shine
    d.ellipse((cx - r * 0.62, cy - r * 0.70, cx - r * 0.22, cy - r * 0.38), fill=(255, 255, 255, 190))
    d.ellipse((cx + r * 0.30, cy - r * 0.62, cx + r * 0.42, cy - r * 0.50), fill=(255, 255, 255, 150))

    ex, ey, er = r * 0.32, cy + r * 0.02, r * 0.11
    lw = max(2, int(S * 0.035))

    def eyes_dots(dx=0.0, dy=0.0):
        for sx in (-1, 1):
            x, y = cx + sx * ex + dx * r, ey + dy * r
            d.ellipse((x - er, y - er * 1.25, x + er, y + er * 1.25), fill=INK)
            d.ellipse((x - er * 0.15, y - er * 0.9, x + er * 0.45, y - er * 0.3), fill=(255, 255, 255, 230))

    def eyes_arcs(up=True):
        for sx in (-1, 1):
            x = cx + sx * ex
            box = (x - er * 1.4, ey - er * 1.2, x + er * 1.4, ey + er * 1.6)
            d.arc(box, 200 if up else 20, 340 if up else 160, fill=INK, width=lw)

    def cheeks():
        for sx in (-1, 1):
            x, y = cx + sx * r * 0.55, ey + r * 0.28
            d.ellipse((x - r * 0.13, y - r * 0.07, x + r * 0.13, y + r * 0.07), fill=CHEEK)

    my = cy + r * 0.36
    if mood in ("happy", "blink"):
        if mood == "blink":
            for sx in (-1, 1):
                x = cx + sx * ex
                d.line((x - er, ey, x + er, ey), fill=INK, width=lw)
        else:
            eyes_dots()
        cheeks()
        d.arc((cx - r * 0.22, my - r * 0.16, cx + r * 0.22, my + r * 0.12), 20, 160, fill=INK, width=lw)
    elif mood == "thinking":
        eyes_dots(0.07, -0.08)
        d.ellipse((cx + r * 0.02, my - r * 0.02, cx + r * 0.14, my + r * 0.07), fill=INK)
        for i, k in enumerate((0.0, 0.16, 0.32)):  # little thought dots
            rr = r * (0.05 + 0.025 * i)
            x, y = cx + r * (0.72 + k * 0.4), cy - r * (0.55 + k)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(230, 240, 255, 230))
    elif mood == "talking":
        eyes_dots()
        cheeks()
        d.ellipse((cx - r * 0.12, my - r * 0.10, cx + r * 0.12, my + r * 0.14), fill=INK)
        d.ellipse((cx - r * 0.07, my + r * 0.02, cx + r * 0.07, my + r * 0.12), fill=(255, 120, 140, 255))
    elif mood == "worried":
        eyes_dots(0, 0.03)
        for sx in (-1, 1):  # brows tilted up toward the middle
            x = cx + sx * ex
            d.line((x - sx * er * 1.3, ey - er * 3.0, x + sx * er * 1.1, ey - er * 2.3), fill=INK, width=lw)
        d.arc((cx - r * 0.18, my - r * 0.02, cx + r * 0.18, my + r * 0.22), 200, 340, fill=INK, width=lw)
        x, y = cx + r * 0.78, cy - r * 0.15  # a drop of sweat
        d.ellipse((x - r * 0.08, y, x + r * 0.08, y + r * 0.2), fill=(170, 220, 255, 230))
    elif mood == "celebrate":
        eyes_arcs(up=True)
        cheeks()
        d.chord((cx - r * 0.26, my - r * 0.14, cx + r * 0.26, my + r * 0.26), 0, 180, fill=INK)
        for ang, k in ((-40, 1.08), (210, 1.05), (-120, 1.12)):  # sparkles around the bubble
            a = math.radians(ang)
            x, y, rr = cx + math.cos(a) * r * k, cy + math.sin(a) * r * k, r * 0.16
            d.polygon([(x, y - rr), (x + rr * 0.3, y - rr * 0.3), (x + rr, y), (x + rr * 0.3, y + rr * 0.3),
                       (x, y + rr), (x - rr * 0.3, y + rr * 0.3), (x - rr, y), (x - rr * 0.3, y - rr * 0.3)],
                      fill=SPARK)
    elif mood == "sleepy":
        for sx in (-1, 1):
            x = cx + sx * ex
            d.arc((x - er * 1.2, ey - er * 1.4, x + er * 1.2, ey + er), 20, 160, fill=INK, width=lw)
        d.ellipse((cx - r * 0.06, my - r * 0.02, cx + r * 0.06, my + r * 0.08), fill=INK)
        x, y = cx + r * 0.62, cy - r * 0.78
        z = r * 0.2
        d.line((x, y, x + z, y, x, y + z, x + z, y + z), fill=(230, 240, 255, 255), width=lw)
    return img.resize((size, size), Image.LANCZOS)


class Mascot:
    """Keeps the Tk images alive (Tk drops images nothing refers to) and hands them out by mood."""

    def __init__(self):
        self.cache = {}

    def image(self, mood, size):
        key = (mood, size)
        if key not in self.cache:
            self.cache[key] = ImageTk.PhotoImage(draw(mood, size))
        return self.cache[key]

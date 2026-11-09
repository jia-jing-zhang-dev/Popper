"""The app icon: a cat's paw (cream fur, pink toe beans), drawn in code so it's sharp at every size."""

from PIL import Image, ImageDraw, ImageFilter

FUR = (252, 238, 222, 255)
FUR_SHADE = (236, 214, 192, 255)
LINE = (122, 88, 72, 255)
BEAN = (255, 150, 172, 255)
BEAN_LIGHT = (255, 206, 216, 255)
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
OVERSAMPLE = 4

# (centre x, centre y, radius) on a 256 canvas
PALM = (128, 156, 76)
TOES = [(56, 100, 33), (98, 62, 35), (158, 62, 35), (200, 100, 33)]


def _circle(d, c, r, fill):
    x, y = c
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def paw(size=256):
    """An RGBA picture of the paw, `size` pixels square."""
    k = size * OVERSAMPLE / 256
    S = size * OVERSAMPLE
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    blobs = [PALM] + TOES
    # a soft drop shadow, then the outline, then the fur
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x, y, r in blobs:
        _circle(sd, (x * k, (y + 6) * k), (r + 6) * k, (0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6 * k)))
    for x, y, r in blobs:
        _circle(d, (x * k, y * k), (r + 7) * k, LINE)
    for x, y, r in blobs:
        _circle(d, (x * k, y * k), r * k, FUR)
    for x, y, r in blobs:   # a little shading at the bottom of each toe and the palm
        _circle(d, (x * k, (y + r * 0.35) * k), r * 0.75 * k, FUR_SHADE)
        _circle(d, (x * k, (y + r * 0.10) * k), r * 0.78 * k, FUR)
    # the big pad: a rounded triangle made of three blobs
    px, py, _ = PALM
    for cx, cy, r in ((px, py + 18, 40), (px - 26, py - 6, 26), (px + 26, py - 6, 26), (px, py - 14, 28)):
        _circle(d, (cx * k, cy * k), r * k, BEAN)
    _circle(d, ((px - 22) * k, (py - 12) * k), 9 * k, BEAN_LIGHT)
    # toe beans
    for x, y, r in TOES:
        bx, by = x, y + r * 0.12
        d.ellipse(((bx - r * 0.55) * k, (by - r * 0.62) * k, (bx + r * 0.55) * k, (by + r * 0.62) * k), fill=BEAN)
        _circle(d, ((bx - r * 0.2) * k, (by - r * 0.28) * k), r * 0.17 * k, BEAN_LIGHT)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path):
    """Write the paw as a multi-size .ico."""
    paw(256).save(path, sizes=SIZES)
    return path

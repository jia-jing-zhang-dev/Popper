"""A believable Windows desktop for the demo: the system's own default wallpaper with the usual icons on it.

Everything comes from this machine's Windows install at recording time (nothing is copied into the repo):
the wallpaper from C:\\Windows\\Web\\Wallpaper, the icons from imageres.dll through the shell, so they look
exactly like a real desktop. `desktop_image(size, icons)` returns a PIL image.
"""

import ctypes
import os
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WALLPAPER = r"C:\Windows\Web\Wallpaper\Windows\img0.jpg"
IMAGERES = r"C:\Windows\System32\imageres.dll"
# (label, (dll, resource id)) as they sit in a fresh Windows desktop's first column
FOLDER, DOC = (IMAGERES, -3), (IMAGERES, -102)
ICONS = [("Recycle Bin", (IMAGERES, -55)), ("This PC", (IMAGERES, -109)), ("Coursework", FOLDER),
         ("Papers to read", FOLDER), ("Lecture notes", FOLDER), ("Lab report draft.docx", DOC),
         ("Screenshots", FOLDER), ("Reading list.txt", DOC), ("Desktop Study Cats", None)]

shell32, user32, gdi32 = ctypes.windll.shell32, ctypes.windll.user32, ctypes.windll.gdi32
shell32.SHDefExtractIconW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.HICON),
                                      ctypes.POINTER(wintypes.HICON), wintypes.UINT]
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
user32.DestroyIcon.argtypes = [wintypes.HICON]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def shell_icon(dll, res_id, size):
    """The icon as an RGBA image, drawn by Windows itself at `size` px."""
    large = wintypes.HICON()
    if shell32.SHDefExtractIconW(dll, res_id, 0, ctypes.byref(large), None, size) != 0 or not large:
        return None
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    dc = gdi32.CreateCompatibleDC(None)
    bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(dc, bmp)
    user32.DrawIconEx(dc, 0, 0, large, size, size, 0, None, 3)   # DI_NORMAL
    raw = ctypes.string_at(bits, size * size * 4)
    gdi32.SelectObject(dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(dc)
    user32.DestroyIcon(large)
    return Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1)


def cover(im, size):
    w, h = size
    k = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def desktop_image(size, icon_x, icon_top, scale=1.5, app_icon=None):
    """Wallpaper plus a column of desktop icons starting at (icon_x, icon_top), like Windows lays them out."""
    wall = cover(Image.open(WALLPAPER).convert("RGB"), size).convert("RGBA")
    px = round(32 * scale)                      # Windows' "medium icons" at this display scale
    cell_w, cell_h = round(76 * scale), round(70 * scale)
    font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf"), round(12 * scale))
    for i, (label, src) in enumerate(ICONS):
        icon = shell_icon(*src, px) if src else (Image.open(app_icon).convert("RGBA").resize((px, px), Image.LANCZOS)
                                                 if app_icon and os.path.exists(app_icon) else None)
        if icon is None:
            continue
        cx, top = icon_x + cell_w // 2, icon_top + i * cell_h
        wall.alpha_composite(icon, (cx - px // 2, top + round(4 * scale)))
        lines = wrap(label, font, cell_w - 6)
        text = Image.new("RGBA", wall.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(text)
        y = top + px + round(8 * scale)
        for line in lines:
            w = d.textlength(line, font=font)
            d.text((cx - w / 2, y), line, font=font, fill=(0, 0, 0, 200))
            y += round(16 * scale)
        shadow = text.filter(ImageFilter.GaussianBlur(1.6))
        wall.alpha_composite(shadow)
        wall.alpha_composite(shadow)
        d2 = ImageDraw.Draw(wall)
        y = top + px + round(8 * scale)
        for line in lines:
            w = d2.textlength(line, font=font)
            d2.text((cx - w / 2, y), line, font=font, fill=(255, 255, 255, 255))
            y += round(16 * scale)
    return wall.convert("RGB")


def wrap(text, font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if font.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line]


if __name__ == "__main__":   # a quick look: demo/_work/desktop.png
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "_work"), exist_ok=True)
    desktop_image((1600, 820), 10, 20).save(os.path.join(here, "_work", "desktop.png"))

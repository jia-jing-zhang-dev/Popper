"""The cats' things on the desktop floor: a food bowl, a water bowl, a scratching post and a bed.

Each is a borderless window with a see-through background, standing on the same floor as the cats; drag one
along the floor to move it (where you put it is remembered). The bed has a second window for the front of its
rim, kept above a cat lying in it, so the cat looks like it's in the bed rather than on top of it. Frames are in
assets/props/ at the cats' scale.
"""

import json
import os
import sys
import tkinter as tk

from PIL import Image, ImageTk

ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "props")
KEY = "#010203"
KEY_RGB = (1, 2, 3)
# name -> (picture(s), drawn this much bigger than true scale, offset from the first cat's spot in cat widths)
ITEMS = {
    "food": (("foodfull", "foodempty"), 1.4, -1.35),
    "water": (("water",), 1.4, -0.85),
    "post": (("post",), 1.0, 1.05),
    "bed": (("bedback",), 1.0, -2.5),
}
FRONT_SHOWN = 0.55   # how much of the rim's front (from the floor up) covers a cat in the bed
CUSHION = 0.42     # how high a cat lying in the bed rests, as a share of the bed picture's height (on the cushion, above the rim's front)


def load_meta():
    try:
        with open(os.path.join(ASSETS, "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def picture(name, scale):
    im = Image.open(os.path.join(ASSETS, f"{name}_0.webp")).convert("RGBA")
    if name == "bedfront":   # only the low near edge goes in front of a cat lying in the bed
        im = im.crop((0, round(im.height * (1 - FRONT_SHOWN)), im.width, im.height))
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    base = Image.new("RGB", im.size, KEY_RGB)
    base.paste(im.convert("RGB"), mask=im.getchannel("A").point(lambda a: 255 if a > 110 else 0))
    return ImageTk.PhotoImage(base)


class Layer:
    """One see-through window showing one picture."""

    def __init__(self, item, names):
        self.item, self.app = item, item.app
        self.images = {n: picture(n, item.scale) for n in names}
        top = self.top = tk.Toplevel(self.app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=KEY)
        top.attributes("-transparentcolor", KEY)
        self.label = tk.Label(top, bg=KEY, bd=0, cursor="fleur")
        self.label.pack()
        self.label.bind("<ButtonPress-1>", item.on_press)
        self.label.bind("<B1-Motion>", item.on_motion)
        self.label.bind("<ButtonRelease-1>", item.on_release)
        self.label.bind("<Button-3>", self.app.show_menu)
        self.show(names[0])

    def show(self, name):
        self.current = name
        img = self.images[name]
        self.w, self.h = img.width(), img.height()
        self.label.configure(image=img)


class Item:
    def __init__(self, pets, name, x, ground, base_scale):
        self.pets, self.app, self.name = pets, pets.app, name
        names, size, _ = ITEMS[name]
        self.scale = base_scale * size
        self.ground = ground
        self.x = float(x)
        self.layers = [Layer(self, names)]
        self.front = Layer(self, ("bedfront",)) if name == "bed" else None
        self.press = None
        self.place()

    @property
    def w(self):
        return self.layers[0].w

    @property
    def h(self):
        return self.layers[0].h

    def cx(self):
        return self.x + self.w / 2

    def show(self, picture_name):
        if self.layers[0].current != picture_name:
            self.layers[0].show(picture_name)

    def place(self):
        for layer in self.layers:
            layer.top.geometry(f"{layer.w}x{layer.h}+{int(self.x)}+{int(self.ground - layer.h)}")
        if self.front:
            f = self.front
            f.top.geometry(f"{f.w}x{f.h}+{int(self.cx() - f.w / 2)}+{int(self.ground - f.h)}")

    def cushion(self):
        """How far above the floor a cat lying in the bed rests (screen px)."""
        return self.h * CUSHION

    def keep_front_on_top(self):
        if self.front:
            self.front.top.lift()
            self.app.root.lift()   # ...but never above the card

    def destroy(self):
        for layer in self.layers + ([self.front] if self.front else []):
            layer.top.destroy()

    # ---------- dragging along the floor

    def on_press(self, e):
        self.press = (e.x_root, self.x)

    def on_motion(self, e):
        if self.press:
            sw = self.layers[0].top.winfo_screenwidth()
            self.x = max(0, min(self.press[1] + e.x_root - self.press[0], sw - self.w))
            self.place()

    def on_release(self, e):
        if self.press:
            self.press = None
            spots = dict(self.app.settings.get("pet_items") or {})
            spots[self.name] = int(self.x)
            self.app.settings["pet_items"] = spots
            self.app.save()

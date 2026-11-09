"""Choosing the cats: a coat and a body type for 泡泡 and for the second cat, and whether there is a second cat."""

import os
import sys
import tkinter as tk

from PIL import Image, ImageTk

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, PANEL

COAT_KEYS = "ABCDEFGH"
TYPE_KEYS = ("adult", "kitten", "slim", "fluffy")


def tile_image(skin, size, bg):
    from features.pet import ASSETS
    im = Image.open(os.path.join(ASSETS, skin, "sit.webp")).convert("RGBA")
    im = im.crop(im.getbbox())
    im.thumbnail((size, size), Image.LANCZOS)
    base = Image.new("RGBA", (size, size), bg)
    base.alpha_composite(im, ((size - im.width) // 2, size - im.height))
    return ImageTk.PhotoImage(base.convert("RGB"))


def hex_rgba(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


class SkinWindow:
    def __init__(self, feature):
        self.feature, self.app = feature, feature.app
        s = self.app.scale
        top = self.top = tk.Toplevel(self.app.root)
        top.title(t("cats_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.bind("<Escape>", lambda e: top.destroy())
        self.body = tk.Frame(top, bg=BG)
        self.body.pack(fill="both", expand=True, padx=int(18 * s), pady=int(14 * s))
        self.images = []
        self.refresh()

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.images = []
        app, s = self.app, self.app.scale
        f = lambda size: app.font("Microsoft YaHei UI", size)
        skins = self.feature.skins()
        two = self.feature.two()
        tk.Label(self.body, text=t("cats_hint"), bg=BG, fg=FG_DIM, font=f(9), justify="left",
                 wraplength=int(560 * s)).pack(anchor="w", pady=(0, 8))
        for i in (0, 1):
            head = tk.Frame(self.body, bg=BG)
            head.pack(fill="x", pady=(int(10 * s), 4))
            tk.Label(head, text=t("cats_first" if i == 0 else "cats_second"), bg=BG, fg=FG, font=f(12)).pack(side="left")
            if i == 1:
                box = tk.Label(head, text=("☑ " if two else "☐ ") + t("cats_two"), bg=BG, fg=ACCENT, cursor="hand2", font=f(10))
                box.pack(side="left", padx=(12, 0))
                box.bind("<Button-1>", lambda e: (self.feature.set_two(not two), self.refresh()))
                if not two:
                    continue
            coat, ty = skins[i].split("_", 1)
            self.row(t("cats_coat"), [(c, f"{c}_{ty}", t(f"coat_{c}")) for c in COAT_KEYS], coat,
                     lambda c, i=i, ty=ty: self.pick(i, f"{c}_{ty}"))
            self.row(t("cats_type"), [(k, f"{coat}_{k}", t(f"type_{k}")) for k in TYPE_KEYS], ty,
                     lambda k, i=i, coat=coat: self.pick(i, f"{coat}_{k}"))

    def row(self, label, items, current, on_pick):
        app, s = self.app, self.app.scale
        tk.Label(self.body, text=label, bg=BG, fg=FG_DIM, font=app.font("Microsoft YaHei UI", 9)).pack(anchor="w")
        shelf = tk.Frame(self.body, bg=BG)
        shelf.pack(anchor="w", pady=(2, 6))
        for key, skin, name in items:
            cell = tk.Frame(shelf, bg=ACCENT if key == current else PANEL, padx=2, pady=2, cursor="hand2")
            cell.pack(side="left", padx=(0, int(5 * s)))
            pic = tile_image(skin, int(58 * s), hex_rgba(PANEL))
            self.images.append(pic)
            img = tk.Label(cell, image=pic, bg=PANEL)
            img.pack()
            cap = tk.Label(cell, text=name, bg=PANEL, fg=FG, font=app.font("Microsoft YaHei UI", 8))
            cap.pack(fill="x")
            for w in (cell, img, cap):
                w.bind("<Button-1>", lambda e, k=key: on_pick(k))

    def pick(self, i, skin):
        self.feature.set_skin(i, skin)
        if i == 0:   # the desktop icon shows 泡泡's face; the running app is __main__, don't import it again
            make_icon = getattr(sys.modules.get("__main__"), "make_desktop_icon", None)
            if make_icon:
                make_icon(self.app.settings)
        self.refresh()

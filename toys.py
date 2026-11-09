"""Cat toys on the desktop: a yarn ball and a ball with a bell. They fall, bounce and roll; the cats bat them about,
and you can drag one around (and let go to throw it) to tease the cats.

Each toy is a borderless window with a see-through background, like the cats. The frames (assets/toys/) are the
toy at 8 rolling angles, rendered at the cats' scale; the yarn's loose end trails to the right as rendered, so the
picture is mirrored while it rolls right.
"""

import json
import math
import os
import sys
import time
import tkinter as tk

from PIL import Image, ImageOps, ImageTk

ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "toys")
KINDS = ("yarn", "ball")
KEY = "#010203"
KEY_RGB = (1, 2, 3)
GRAVITY = 2600.0        # px/s², before display scaling
FRICTION = {"yarn": 520.0, "ball": 260.0}   # px/s² of rolling slow-down: the ball rolls further
BOUNCE = {"yarn": 0.25, "ball": 0.55}


def load_meta():
    try:
        with open(os.path.join(ASSETS, "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Toy:
    def __init__(self, pets, kind, x, ground, scale, drop=True):
        self.pets, self.app, self.kind = pets, pets.app, kind
        meta = pets.toy_meta[kind]
        self.n = meta["frames"]
        self.scale = scale
        self.w, self.h = round(meta["size"][0] * scale), round(meta["size"][1] * scale)
        self.r = meta["radius"] * scale
        self.images = {}
        top = self.top = tk.Toplevel(self.app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=KEY)
        top.attributes("-transparentcolor", KEY)
        self.label = tk.Label(top, bg=KEY, bd=0, cursor="hand2")
        self.label.pack()
        self.x = float(x)            # left edge of the window
        self.ground = ground
        self.y = ground - (420 * self.app.scale if drop else 0)   # bottom edge; dropped in from above
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.mirror = False
        self.last_hit = time.time()
        self.drag = None
        self.label.bind("<ButtonPress-1>", self.on_press)
        self.label.bind("<B1-Motion>", self.on_motion)
        self.label.bind("<ButtonRelease-1>", self.on_release)
        self.label.bind("<Button-3>", self.app.show_menu)
        self.show()
        self.place()

    # ---------- looks and place

    def image(self, i, mirror):
        key = (i, mirror)
        if key not in self.images:
            im = Image.open(os.path.join(ASSETS, f"{self.kind}_{i}.webp")).convert("RGBA").resize((self.w, self.h), Image.LANCZOS)
            if mirror:
                im = ImageOps.mirror(im)
            base = Image.new("RGB", im.size, KEY_RGB)
            base.paste(im.convert("RGB"), mask=im.getchannel("A").point(lambda a: 255 if a > 110 else 0))
            self.images[key] = ImageTk.PhotoImage(base)
        return self.images[key]

    def show(self):
        i = int((self.angle / (2 * math.pi)) * self.n) % self.n
        self.label.configure(image=self.image(i, self.mirror))

    def place(self):
        self.top.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y - self.h)}")

    def cx(self):
        """Where the ball itself is (the yarn's loose end sticks out to one side)."""
        if self.kind == "yarn":
            return self.x + (self.w - self.r if self.mirror else self.r)
        return self.x + self.w / 2

    def moving(self):
        return abs(self.vx) > 5 or self.y < self.ground - 1 or self.drag is not None

    def recently_moved(self, seconds=4):
        return self.moving() or time.time() - self.last_hit < seconds

    # ---------- physics

    def kick(self, vx, vy=0.0):
        self.vx, self.vy = vx, vy
        self.last_hit = time.time()

    def speed_to_travel(self, distance):
        """The push that makes the toy roll about `distance` px before it stops (constant rolling friction)."""
        return math.sqrt(2 * FRICTION[self.kind] * self.app.scale * max(0.0, distance))

    def tick(self, dt):
        if self.drag:
            return
        s = self.app.scale
        airborne = self.y < self.ground - 0.5 or self.vy < 0
        if airborne:
            self.vy += GRAVITY * s * dt
            self.y += self.vy * dt
            if self.y >= self.ground:
                self.y = self.ground
                self.vy = -self.vy * BOUNCE[self.kind] if abs(self.vy) > 220 * s else 0.0
        if not airborne or self.y >= self.ground:
            slow = FRICTION[self.kind] * s * dt
            self.vx = 0.0 if abs(self.vx) <= slow else self.vx - math.copysign(slow, self.vx)
        self.x += self.vx * dt
        sw = self.top.winfo_screenwidth()
        if self.x < 0 or self.x > sw - self.w:          # bounce off the screen's sides
            self.x = max(0, min(self.x, sw - self.w))
            self.vx = -self.vx * 0.5
        if abs(self.vx) > 1:
            self.angle -= self.vx * dt / max(self.r, 1)
            if self.kind == "yarn":
                self.mirror = self.vx > 0
        self.show()
        self.place()

    # ---------- dragging (and throwing) with the mouse

    def on_press(self, e):
        self.drag = [e.x_root, e.y_root, self.x, self.y, [(time.time(), e.x_root, e.y_root)], False]
        self.vx = self.vy = 0.0

    def on_motion(self, e):
        sx, sy, x0, y0, trail, moved = self.drag
        self.drag[5] = moved or abs(e.x_root - sx) + abs(e.y_root - sy) > 3
        self.x = x0 + e.x_root - sx
        self.y = min(self.ground, y0 + e.y_root - sy)
        trail.append((time.time(), e.x_root, e.y_root))
        del trail[:-6]
        self.last_hit = time.time()
        self.place()

    def on_release(self, e):
        trail = self.drag[4] if self.drag else []
        self.drag = None
        if len(trail) >= 2 and trail[-1][0] > trail[0][0]:
            dt = trail[-1][0] - trail[0][0]
            self.kick((trail[-1][1] - trail[0][1]) / dt * 0.8, (trail[-1][2] - trail[0][2]) / dt * 0.8)
        else:
            self.kick(0.0, 0.0)
        if self.y >= self.ground and self.vy > 0:
            self.vy = 0.0

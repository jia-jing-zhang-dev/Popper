"""Desktop pet: 泡泡 stands on the desktop, breathes, blinks, hops and wanders, and the card is its speech bubble.

The pet is a borderless window whose background colour is made transparent, so only the bubble shows.
It bobs gently, hops when clicked or when a word is looked up, and now and then walks a little way
along the screen. Dragging it (or the card) moves both; a click does what a click on the card does.
"""

import math
import os
import random
import sys
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .base import Feature

# Frames of FluffyBlob by Jaqueline Martin (CC0), see assets/pet/CREDITS.md
ASSETS = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "assets", "pet")
MOODS = {                     # mood -> (frame numbers, ms per frame)
    "happy": ([0, 1, 0, 3], 700),
    "blink": ([2], 160),
    "thinking": ([4, 11], 600),
    "talking": ([10, 13], 300),
    "worried": ([14, 16], 700),
    "celebrate": ([2, 5, 6, 5], 220),
    "sleepy": ([15], 1000),
}
HOP = [7, 8, 10, 13, 9, 7]    # squash, rise, stretch, airborne, fall, land
MARKS = {"thinking": "?", "talking": "!", "sleepy": "Zz"}

KEY = "#010203"           # this colour is see-through in the pet window
KEY_RGB = (1, 2, 3)
FRAME_MS = 60
WANDER_MS = (3 * 60_000, 8 * 60_000)


def pet_image(frame, size, mark=None, hat=None):
    """One frame on the see-through colour. Only nearly opaque pixels are kept: soft edges and the
    painted shadow would blend with the see-through colour into a dark fringe. `hat` is what it wears
    (bond.py); then the pet is drawn a little smaller to leave room on top."""
    rgba = Image.open(os.path.join(ASSETS, f"frame_{frame:02d}.png")).convert("RGBA")
    inner = round(size * 0.80) if hat else size
    rgba.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(rgba, ((size - rgba.width) // 2, size - rgba.height))
    if hat:
        from bond import wear
        wear(canvas, hat)
    if mark:
        d = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(r"C:\Windows\Fonts\seguisb.ttf", max(12, size // 4))
        d.text((size * 0.70, size * 0.02), mark, font=font, fill=(255, 255, 255, 255),
               stroke_width=max(2, size // 40), stroke_fill=(31, 36, 48, 255))
    base = Image.new("RGB", canvas.size, KEY_RGB)
    mask = canvas.getchannel("A").point(lambda a: 255 if a > 200 else 0)
    base.paste(canvas.convert("RGB"), mask=mask)
    return ImageTk.PhotoImage(base)


class PetFeature(Feature):
    id = "pet"
    name_key = "feat_pet"

    def start(self):
        self.win = None
        self.every_frame = None
        self.app.root.after(300, self.sync)
        self.app.root.after(1000, self.sync_loop)

    # ---------- on / off

    def sync_loop(self):
        self.sync()
        if self.win and self.win.style != self.win.wanted_style():
            self.win.restyle()
        self.app.root.after(1000, self.sync_loop)

    def sync(self):
        if self.on and not self.win:
            self.win = PetWindow(self.app)
        elif not self.on and self.win:
            self.win.close()
            self.win = None


class PetWindow:
    def __init__(self, app):
        self.app = app
        self.style = self.wanted_style()
        self.size = self.pet_size()
        self.frame = None
        self.images = {}
        self.mood = "happy"
        top = self.top = tk.Toplevel(app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=KEY)
        top.attributes("-transparentcolor", KEY)
        self.label = tk.Label(top, bg=KEY, bd=0, cursor="hand2")
        self.label.pack()

        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        s = app.settings
        self.x = s.get("pet_x") if s.get("pet_x") is not None else sw - self.size - 60
        self.y = s.get("pet_y") if s.get("pet_y") is not None else sh - self.size - 70
        self.clamp()
        self.phase = 0.0
        self.hop_frames = 0       # frames left in a hop
        self.walk_to = None
        self.drag = None

        self.label.bind("<ButtonPress-1>", self.on_press)
        self.label.bind("<B1-Motion>", self.on_motion)
        self.label.bind("<ButtonRelease-1>", self.on_release)
        self.label.bind("<Button-3>", app.show_menu)

        app.anchor = self.card_anchor
        app.card_drag = self.drag_from_card
        app.mood_listeners.append(self.set_mood)
        app.hop_listeners.append(self.hop)
        app.avatar.pack_forget()  # the pet is the face now; no second one inside the card
        self.set_mood(app.mood())
        self.tick()
        self.schedule_wander()
        app.place_window()

    def close(self):
        app = self.app
        app.anchor = app.card_drag = None
        app.mood_listeners.remove(self.set_mood)
        app.hop_listeners.remove(self.hop)
        app.avatar.pack(side="left", padx=(0, 8), before=app.word_lbl)
        self.top.destroy()
        app.place_window()

    # ---------- looks

    def wanted_style(self):
        """(accessory, size factor) from 泡泡's bond: it grows a little and wears what it unlocked."""
        try:
            return self.app.feature("bond").pet_style()
        except StopIteration:
            return None, 1.0

    def pet_size(self):
        return round(84 * self.app.scale * self.style[1] / (0.80 if self.style[0] else 1))

    def restyle(self):
        """Redraw with a new accessory or size, keeping the feet where they were."""
        bottom = self.y + self.size
        self.style = self.wanted_style()
        self.size = self.pet_size()
        self.y = bottom - self.size
        self.images, self.frame = {}, None
        self.clamp()
        self.show_frame()
        self.app.place_window()

    def set_mood(self, mood):
        self.mood = mood
        self.show_frame()

    def show_frame(self):
        """Pick the frame for the current mood (or the hop in progress) and show it if it changed."""
        if self.hop_frames:
            frame, mark = HOP[min(len(HOP) - 1, (12 - self.hop_frames) // 2)], None
        else:
            frames, ms = MOODS.get(self.mood, MOODS["happy"])
            frame, mark = frames[int(time.time() * 1000 / ms) % len(frames)], MARKS.get(self.mood)
        if (frame, mark) == self.frame:
            return
        self.frame = (frame, mark)
        if self.frame not in self.images:
            self.images[self.frame] = pet_image(frame, self.size, mark, self.style[0])
        self.label.configure(image=self.images[self.frame])

    def clamp(self):
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        self.x = max(0, min(self.x, sw - self.size))
        self.y = max(40, min(self.y, sh - self.size))

    def tick(self):
        """One animation frame: breathe, hop, walk."""
        if not self.top.winfo_exists():
            return
        self.phase += 0.12 if self.mood != "sleepy" else 0.05
        lift = 0
        if self.hop_frames:
            k = self.hop_frames / 12
            lift = round(math.sin(math.pi * k) * self.size * 0.3)
            self.hop_frames -= 1
        if self.walk_to is not None and not self.drag:
            step = max(-4, min(4, self.walk_to - self.x))
            self.x += step
            if not self.hop_frames:
                self.hop_frames = 12
            if abs(self.walk_to - self.x) < 1:
                self.walk_to = None
                self.save()
            self.app.place_window()
        self.show_frame()
        bob = round(math.sin(self.phase) * self.size * 0.03)
        self.top.geometry(f"+{int(self.x)}+{int(self.y + bob - lift)}")
        self.top.after(FRAME_MS, self.tick)

    def hop(self):
        if not self.hop_frames:
            self.hop_frames = 12

    def schedule_wander(self):
        self.top.after(random.randint(*WANDER_MS), self.wander)

    def wander(self):
        if not self.top.winfo_exists():
            return
        if not self.drag and self.mood in ("happy", "blink"):
            self.walk_to = self.x + random.choice((-1, 1)) * random.randint(60, 220)
            sw = self.top.winfo_screenwidth()
            self.walk_to = max(0, min(self.walk_to, sw - self.size))
        self.schedule_wander()

    # ---------- the card rides along

    def card_anchor(self):
        """The card's bottom-left corner: just above the pet's head."""
        return int(self.x - self.size * 0.2), int(self.y - self.size * 0.12)

    def drag_from_card(self, dx, dy, done):
        if done:
            self.drag = None
            self.save()
            return
        if not self.drag:
            self.drag = (self.x, self.y)
        self.x, self.y = self.drag[0] + dx, self.drag[1] + dy
        self.clamp()
        self.walk_to = None
        self.app.place_window()

    # ---------- mouse on the pet

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.x, self.y, False)

    def on_motion(self, e):
        sx, sy, x0, y0, moved = self.press
        dx, dy = e.x_root - sx, e.y_root - sy
        if moved or abs(dx) + abs(dy) > 4:
            self.press = (sx, sy, x0, y0, True)
            self.drag = (x0, y0)
            self.x, self.y = x0 + dx, y0 + dy
            self.clamp()
            self.walk_to = None
            self.app.place_window()

    def on_release(self, e):
        moved = self.press[4]
        self.drag = None
        if moved:
            self.save()
        else:
            self.hop()
            self.app.card_clicked()

    def save(self):
        self.app.settings["pet_x"], self.app.settings["pet_y"] = int(self.x), int(self.y)
        self.app.save()

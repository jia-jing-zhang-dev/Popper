"""Desktop pets: two realistic cats live along the bottom of the screen; the first one carries the card.

Each cat is a borderless window whose background colour is made transparent. The frames are renders of a
rigged 3D cat (assets/cats, see CREDITS.md there): 8 coats x 4 body types, 29 poses each. Front-facing poses
are for sitting about and showing the first cat's moods; side-facing ones (they face left, and are mirrored to face
right) are for walking, running and the two cats' interactions.

How they behave: each cat runs one action at a time (sit, groom itself, yawn, nap, look around, walk, run).
When an action ends it picks the next at random, weighted by what's going on: while you're working they stay
calm and close to home; when you've left the keyboard for a while they wander, play and get together (touch
noses, groom each other, chase, nap cuddled up). The first cat also shows the card's mood (thinking, talking,
worried, celebrating, sleepy) and stays near its spot so the card doesn't run away from you.
"""

import json
import math
import os
import random
import sys
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

from focus import idle_seconds
from i18n import CAT, t

from .base import Feature

ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets", "cats")
COATS = "ABCDEFGH"
TYPES = ("adult", "kitten", "slim", "fluffy")
DEFAULT_SKINS = ["A_adult", "D_kitten"]
# each coat's default name (Chinese, English); either cat can be renamed in the Cats window
COAT_NAMES = {"A": ("虎子", "Tiger"), "B": ("橘子", "Mandarin"), "C": ("银宝", "Silver"), "D": ("蓝莓", "Blueberry"),
              "E": ("芝麻", "Sesame"), "F": ("奥利奥", "Oreo"), "G": ("花花", "Callie"), "H": ("雪球", "Snowball")}

KEY = "#010203"           # this colour is see-through in the pet windows
KEY_RGB = (1, 2, 3)
FRAME_MS = 60
SIT_HEIGHT = 92           # an adult sitting cat is about this tall on screen, before display scaling
CALM_IDLE = 45            # seconds without input before the cats feel unobserved
AWAY_IDLE = 4 * 60        # ... and before they settle down for a long nap together
HAT_WIDTH = 3.2         # an accessory's width, in ear-base spacings
MARKS = {"thinking": "?", "talking": "!", "sleepy": "Zz"}

WALK = [f"walk{i}" for i in range(6)]
RUN = [f"run{i}" for i in range(4)]


def load_meta():
    try:
        with open(os.path.join(ASSETS, "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def skin_type(skin):
    return skin.split("_", 1)[1]


def frame_image(skin, frame, scale, mirror=False, hat=None, anchor=None, mark=None):
    """One frame as a Tk image on the see-through colour, `scale` times the stored size."""
    rgba = Image.open(os.path.join(ASSETS, skin, frame + ".webp")).convert("RGBA")
    w, h = round(rgba.width * scale), round(rgba.height * scale)
    rgba = rgba.resize((w, h), Image.LANCZOS)
    if hat and anchor:
        from bond import wear_at
        (hx, hy), (lx, _), (rx, _) = anchor["head"], anchor["ear_l"], anchor["ear_r"]
        width = max(abs(lx - rx), 1) * scale * HAT_WIDTH   # the anchors are the ear bases: the head is wider
        wear_at(rgba, hat, hx * scale, hy * scale + width * 0.04, width)
    if mirror:
        rgba = ImageOps.mirror(rgba)
    if mark:
        d = ImageDraw.Draw(rgba)
        font = ImageFont.truetype(r"C:\Windows\Fonts\seguisb.ttf", max(12, h // 7))
        x = w * (0.30 if mirror else 0.62) if anchor is None else (anchor["head"][0] * scale + h * 0.12)
        d.text((x, h * 0.02), mark, font=font, fill=(255, 255, 255, 255),
               stroke_width=max(2, h // 70), stroke_fill=(31, 36, 48, 255))
    # keep fairly opaque pixels only: soft fur edges would blend with the see-through colour into a fringe
    base = Image.new("RGB", rgba.size, KEY_RGB)
    base.paste(rgba.convert("RGB"), mask=rgba.getchannel("A").point(lambda a: 255 if a > 110 else 0))
    return ImageTk.PhotoImage(base)


class PetFeature(Feature):
    id = "pet"
    name_key = "feat_pet"

    def start(self):
        self.cats = []
        self.meta = load_meta()
        self.director = None
        self.update_name()
        self.app.root.after(300, self.sync)
        self.app.root.after(1000, self.sync_loop)

    def menu_items(self, menu):
        menu.add_command(label=t("menu_cats"), command=self.open_skins)

    def open_skins(self):
        from cat_skins import SkinWindow
        self.show("skins", lambda: SkinWindow(self))

    # ---------- settings

    def skins(self):
        s = list(self.app.settings.get("pet_skins") or DEFAULT_SKINS)
        s += DEFAULT_SKINS[len(s):]
        return s[:2]

    def names(self):
        """Each cat's name: the one the owner gave it, else its coat's; the two are never the same."""
        zh = self.app.settings.get("ui_lang") == "zh"
        custom = list(self.app.settings.get("pet_names") or []) + [None, None]
        out = []
        for i, skin in enumerate(self.skins()):
            name = (custom[i] or "").strip()
            if not name:
                name = COAT_NAMES[skin[0]][0 if zh else 1]
                if out and name == out[0]:
                    name = ("小" + name) if zh else (name + " Jr.")
            out.append(name)
        return out

    def set_name(self, i, name):
        """Rename cat i; refused (False) when the other cat already has that name."""
        name = name.strip()[:16]
        if name and name == self.names()[1 - i]:
            return False
        names = list(self.app.settings.get("pet_names") or []) + [None, None]
        names[i] = name or None
        self.app.settings["pet_names"] = names[:2]
        self.app.save()
        self.update_name()
        return True

    def update_name(self):
        """Strings that say {cat} use the first cat's name (i18n.CAT)."""
        name = self.names()[0]
        if CAT["name"] != name:
            CAT["name"] = name
            if hasattr(self.app, "word_lbl"):
                self.app.update_status()

    def two(self):
        return self.app.settings.get("pet_two", True)

    def set_skin(self, i, skin):
        skins = self.skins()
        skins[i] = skin
        self.app.settings["pet_skins"] = skins
        self.app.save()
        self.update_name()
        self.rebuild()

    def set_two(self, on):
        self.app.settings["pet_two"] = bool(on)
        self.app.save()
        self.rebuild()

    # ---------- on / off

    def sync_loop(self):
        self.update_name()     # also follows a change of interface language
        self.sync()
        if self.cats and self.cats[0].style != self.cats[0].wanted_style():
            self.cats[0].restyle()
        self.app.root.after(1000, self.sync_loop)

    def sync(self):
        want = self.on and self.meta is not None
        if want and not self.cats:
            self.build()
        elif not want and self.cats:
            self.teardown()

    def build(self):
        skins = self.skins()
        self.cats = [Cat(self, 0, skins[0])]
        if self.two():
            self.cats.append(Cat(self, 1, skins[1]))
        self.director = Director(self)
        self.cats[0].attach_card()
        self.tick()

    def teardown(self):
        self.cats[0].detach_card()
        for c in self.cats:
            c.top.destroy()
        self.cats = []
        self.director = None

    def rebuild(self):
        if self.cats:
            self.teardown()
        self.sync()

    def tick(self):
        if not self.cats:
            return
        now = time.time()
        self.director.tick(now)
        for c in self.cats:
            c.tick(now)
        self.app.root.after(FRAME_MS, self.tick)

    # ---------- what's going on around the cats

    def idle(self):
        try:
            return idle_seconds()
        except OSError:
            return 0

    def drowsy(self):
        """Late at night, or the app paused: the cats would rather sleep."""
        hour = time.localtime().tm_hour
        return hour >= 23 or hour < 7 or not self.app.settings.get("listening", True)


class Cat:
    """One cat: its window, where it is, which way it faces, and what it's doing."""

    def __init__(self, pets, index, skin):
        self.pets, self.app, self.index, self.skin = pets, pets.app, index, skin
        self.anchors = pets.meta["anchors"][skin_type(skin)]
        cw, ch = pets.meta["canvas"]
        self.style = self.wanted_style()
        self.images = {}
        self.scale = self.compute_scale()
        self.w, self.h = round(cw * self.scale), round(ch * self.scale)
        top = self.top = tk.Toplevel(self.app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=KEY)
        top.attributes("-transparentcolor", KEY)
        self.label = tk.Label(top, bg=KEY, bd=0, cursor="hand2")
        self.label.pack()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        s = self.app.settings
        key = "pet_x" if index == 0 else "pet2_x"
        self.home = s.get(key) if s.get(key) is not None else sw - self.w - 60 - index * self.w
        self.x = float(self.home)
        self.ground = (s.get("pet_ground") if s.get("pet_ground") is not None else sh - 50)
        self.facing = -1          # -1 faces left (as rendered), +1 faces right (mirrored)
        self.frame = None
        self.shown = None
        self.action = None
        self.hop_t = 0
        self.drag = None
        self.press = None
        self.clamp()
        self.label.bind("<ButtonPress-1>", self.on_press)
        self.label.bind("<B1-Motion>", self.on_motion)
        self.label.bind("<ButtonRelease-1>", self.on_release)
        self.label.bind("<Button-3>", self.app.show_menu)
        base = {"sit": 38, "groom": 14, "yawn": 6, "look": 10, "nap": 8, "walk": 24}
        self.personality = {k: v * random.uniform(0.6, 1.5) for k, v in base.items()}
        self.sit(random.uniform(2, 5) + index * random.uniform(2, 6))   # and they don't start in step
        self.place()

    # ---------- looks

    def wanted_style(self):
        """(accessory, size factor): only the first cat wears what it unlocked with the bond, and grows a little."""
        if self.index:
            return None, 1.0
        try:
            return self.app.feature("bond").pet_style()
        except StopIteration:
            return None, 1.0

    def compute_scale(self):
        ch = self.pets.meta["canvas"][1]
        sit = self.pets.meta["anchors"]["adult"]["sit"]
        adult_sit_h = ch - sit["head"][1] + abs(sit["ear_l"][0] - sit["ear_r"][0]) * 0.6
        return SIT_HEIGHT * self.app.scale * self.style[1] / max(adult_sit_h, 1)

    def restyle(self):
        self.style = self.wanted_style()
        self.scale = self.compute_scale()
        cw, ch = self.pets.meta["canvas"]
        self.w, self.h = round(cw * self.scale), round(ch * self.scale)
        self.images = {}
        self.shown = None
        self.place()
        self.app.place_window()

    def image(self, frame, mirror, mark):
        key = (frame, mirror, mark)
        if key not in self.images:
            self.images[key] = frame_image(self.skin, frame, self.scale, mirror, self.style[0],
                                           self.anchors.get(frame), mark)
        return self.images[key]

    def show(self, frame, mark=None):
        side = self.anchors.get(frame, {}).get("side", False)
        mirror = side and self.facing > 0
        key = (frame, mirror, mark)
        if key != self.shown:
            self.shown = key
            self.label.configure(image=self.image(frame, mirror, mark))

    # ---------- position

    def clamp(self):
        sw = self.top.winfo_screenwidth()
        self.x = max(-self.w * 0.25, min(self.x, sw - self.w * 0.75))

    def place(self):
        lift = 0
        if self.hop_t:
            k = self.hop_t / 12
            lift = round(math.sin(math.pi * k) * self.h * 0.12)
        self.top.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.ground - self.h - lift)}")

    def centre(self):
        return self.x + self.w / 2

    def head_xy(self, frame="sit"):
        a = self.anchors[frame]["head"]
        return self.x + a[0] * self.scale, self.ground - self.h + a[1] * self.scale

    # ---------- actions: (frames, ms per frame, seconds) and optional movement

    def do(self, kind, frames, ms, seconds=None, target=None, speed=0.0, facing=None, mark=None, then=None):
        self.action = {"kind": kind, "frames": frames, "ms": ms, "start": time.time(),
                       "until": time.time() + seconds if seconds else None, "target": target,
                       "speed": speed, "mark": mark, "then": then}
        if facing:
            self.facing = facing
        elif target is not None:
            self.facing = 1 if target > self.x else -1

    def busy(self):
        a = self.action
        return a and a["kind"] in ("together", "mood", "drag")

    def sit(self, seconds):
        self.do("sit", ["sit"], 1000, seconds)

    def walk_to(self, x, then=None, run=False):
        sw = self.top.winfo_screenwidth()
        x = max(0, min(x, sw - self.w))
        speed = (150 if run else 48) * self.app.scale * (0.8 if skin_type(self.skin) == "kitten" else 1.0)
        self.do("move", RUN if run else WALK, 80 if run else 120, target=x, speed=speed, then=then)

    def hop(self):
        if not self.hop_t:
            self.hop_t = 12

    def tick(self, now):
        a = self.action
        if a is None:
            self.choose()
            a = self.action
        frames = a["frames"]
        i = int((now - a["start"]) * 1000 / a["ms"]) % len(frames)
        frame = frames[i]
        # blink now and then while sitting about
        if a["kind"] == "sit" and frame == "sit" and (now % 5.3) < 0.18:
            frame = "blink"
        if a["kind"] == "sit" and frame == "sit_s" and (now % 4.7) < 0.18:
            frame = "blink_s"
        self.show(frame, a.get("mark"))
        moved = False
        if a["target"] is not None and not self.drag:
            step = a["speed"] * FRAME_MS / 1000
            d = a["target"] - self.x
            if abs(d) <= step:
                self.x = a["target"]
                a["target"] = None
                self.finish()
            else:
                self.x += step if d > 0 else -step
            moved = True
        elif a["until"] and now >= a["until"]:
            self.finish()
        if self.hop_t:
            self.hop_t -= 1
            moved = True
        if moved:
            self.place()
            if self.index == 0:
                self.app.place_window()

    def finish(self):
        then = self.action.get("then") if self.action else None
        self.action = None
        if then:
            then()

    def choose(self):
        """Pick what to do next, on its own."""
        if self.index == 0:
            mood = self.app.mood()
            if mood in ("thinking", "talking", "worried", "celebrate"):
                self.show_mood(mood)
                return
        pets = self.pets
        idle = pets.idle()
        unobserved = idle > CALM_IDLE
        roam = 600 if unobserved else 160
        if self.index == 0:
            roam = 260 if unobserved else 60    # the first cat carries the card: stay near where you put it
        sleepy = pets.drowsy() or idle > AWAY_IDLE
        w = dict(self.personality)
        if sleepy:
            w["nap"] *= 8
        elif not unobserved:
            w["nap"] *= 0.3
            w["walk"] *= 0.6
        # never mirror the other cat: whatever it's doing now is much less likely here
        other = self.other()
        if other and other.action:
            kind = other.action["kind"]
            for k in w:
                if k == kind or (k == "walk" and kind == "move"):
                    w[k] *= 0.08
        kind = random.choices(list(w), list(w.values()))[0]
        if kind == "sit":
            self.sit(random.uniform(4, 12))
        elif kind == "groom":
            self.do("groom", ["lick1", "lick2"], random.choice((380, 420, 470)), random.uniform(3, 7))
        elif kind == "yawn":
            self.do("yawn", ["yawn"], 1000, random.uniform(1.2, 2.0))
        elif kind == "look":
            self.facing = random.choice((-1, 1))
            self.do("look", ["sit_s"], 1000, random.uniform(3, 7))
        elif kind == "nap":
            self.do("nap", ["sleep"], 1000, random.uniform(60, 240) if sleepy else random.uniform(20, 90))
        else:
            x = self.home + random.uniform(-roam, roam)
            self.walk_to(x, run=unobserved and random.random() < 0.15)

    def other(self):
        cats = self.pets.cats
        return next((c for c in cats if c is not self), None)

    def show_mood(self, mood):
        frames = {"thinking": ["think"], "talking": ["talk", "talk2"], "worried": ["worried"],
                  "celebrate": ["wave1", "wave2"]}[mood]
        self.do("mood", frames, 260 if mood != "thinking" else 1000, 1.2, mark=MARKS.get(mood))

    def mood_changed(self, mood):
        if self.busy() and self.action["kind"] != "mood":
            return
        if mood in ("thinking", "talking", "worried", "celebrate"):
            self.show_mood(mood)
        elif self.action and self.action["kind"] == "mood":
            self.sit(random.uniform(2, 5))

    # ---------- the card rides along with the first cat

    def attach_card(self):
        app = self.app
        app.anchor = self.card_anchor
        app.card_drag = self.drag_from_card
        app.mood_listeners.append(self.mood_changed)
        app.hop_listeners.append(self.hop)
        app.avatar.pack_forget()  # the cat is the face now; no second one inside the card
        app.place_window()

    def detach_card(self):
        app = self.app
        app.anchor = app.card_drag = None
        if self.mood_changed in app.mood_listeners:
            app.mood_listeners.remove(self.mood_changed)
        if self.hop in app.hop_listeners:
            app.hop_listeners.remove(self.hop)
        app.avatar.pack(side="left", padx=(0, 8), before=app.word_lbl)
        app.place_window()

    def card_anchor(self):
        """The card's bottom-left corner: just above the sitting cat's head, so it doesn't jump with each pose."""
        hx, hy = self.head_xy("sit")
        return int(hx - 40 * self.app.scale), int(hy - 18 * self.app.scale)

    def drag_from_card(self, dx, dy, done):
        if done:
            self.drag = None
            self.save()
            return
        if not self.drag:
            self.drag = (self.x, self.ground)
            self.do("drag", ["sit"], 1000)
        self.x, self.ground = self.drag[0] + dx, self.drag[1] + dy
        self.clamp()
        self.place()
        self.app.place_window()

    # ---------- mouse on the cat

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.x, self.ground, False)

    def on_motion(self, e):
        sx, sy, x0, g0, moved = self.press
        dx, dy = e.x_root - sx, e.y_root - sy
        if moved or abs(dx) + abs(dy) > 4:
            if not moved:
                self.do("drag", ["sit"], 1000)
            self.press = (sx, sy, x0, g0, True)
            self.drag = (x0, g0)
            self.x, self.ground = x0 + dx, g0 + dy
            self.clamp()
            self.place()
            if self.index == 0:
                self.app.place_window()

    def on_release(self, e):
        moved = self.press and self.press[4]
        self.drag = None
        if moved:
            self.save()
            self.sit(random.uniform(2, 4))
        elif self.index == 0:
            self.hop()
            self.app.card_clicked()
        else:
            self.hop()
            self.pets.director.come_over()   # the other cat goes to say hello

    def save(self):
        s = self.app.settings
        self.home = self.x
        s["pet_x" if self.index == 0 else "pet2_x"] = int(self.x)
        s["pet_ground"] = int(self.ground)
        for c in self.pets.cats:      # both cats live on the same floor
            c.ground = self.ground
            c.place()
        self.app.save()


class Director:
    """Now and then, brings the two cats together: touching noses, grooming, a chase, a nap side by side."""

    def __init__(self, pets):
        self.pets = pets
        self.next_time = time.time() + random.uniform(40, 90)
        self.running = None
        self.token = 0

    def begin(self, kind):
        self.running = kind
        self.token += 1

    def later(self, ms, fn):
        """Run fn after ms, unless another interaction (or none) has taken over by then."""
        token = self.token
        self.pets.app.root.after(int(ms), lambda: self.running and token == self.token and self.pets.director is self and fn())

    def pair(self):
        cats = self.pets.cats
        return (cats[0], cats[1]) if len(cats) == 2 else None

    def tick(self, now):
        p = self.pair()
        if not p or self.running or now < self.next_time:
            return
        a, b = p
        if a.busy() or b.busy():
            return
        idle = self.pets.idle()
        unobserved = idle > CALM_IDLE
        self.next_time = now + (random.uniform(25, 70) if unobserved else random.uniform(120, 300))
        if self.pets.drowsy() or idle > AWAY_IDLE:
            self.cuddle(a, b)
            return
        if not unobserved and random.random() < 0.6:
            return   # while you're working they mostly leave each other alone
        choice = random.choices(["boop", "groom", "chase", "cuddle"], [4, 3, 2 if unobserved else 0, 1])[0]
        getattr(self, choice)(a, b) if choice != "groom" else self.groom(*random.sample((a, b), 2))

    def end(self, *cats):
        self.running = None
        self.token += 1
        first = random.choice(cats)
        for c in cats:
            if c is first:
                c.sit(random.uniform(2, 6))
            else:
                c.action = None      # picks something else on the next frame

    def meet(self, mover, other, then, gap=0.62, run=False):
        """Walk `mover` up beside `other`, on whichever side it already is."""
        side = -1 if mover.centre() < other.centre() else 1
        target = other.x + side * other.w * gap
        other.do("together", ["sit_s"], 1000, facing=side)
        mover.walk_to(target, then=then, run=run)
        mover.action["kind"] = "together"

    def boop(self, a, b):
        self.begin("boop")
        mover, still = random.sample((a, b), 2)

        def touch():
            mover.facing = -still.facing
            mover.do("together", ["sit_s", "boop"], 900, facing=mover.facing)
            still.do("together", ["sit_s", "boop"], 900, facing=still.facing)
            self.later(2700, lambda: self.end(a, b))
        self.meet(mover, still, touch)

    def groom(self, giver, receiver):
        self.begin("groom")

        def lick():
            giver.do("together", ["groom1", "groom2"], 450, facing=-receiver.facing)
            receiver.do("together", ["groomed"], 1000, facing=receiver.facing)
            self.later(int(random.uniform(4, 8) * 1000), lambda: self.end(giver, receiver))
        self.meet(giver, receiver, lick)

    def chase(self, a, b):
        self.begin("chase")
        runner, chaser = random.sample((a, b), 2)
        sw = runner.top.winfo_screenwidth()
        far = random.uniform(0.1, 0.9) * sw
        if runner.index == 0:   # the first cat carries the card: a short dash only
            far = runner.home + random.choice((-1, 1)) * 220 * runner.app.scale
        runner.walk_to(far, run=True, then=lambda: self.caught(runner, chaser))
        runner.action["kind"] = "together"
        self.follow(chaser, runner)

    def follow(self, chaser, runner):
        if self.running != "chase":
            return
        gap = runner.w * 0.7 * (-1 if runner.facing > 0 else 1)
        chaser.walk_to(runner.x + gap, run=True)
        chaser.action["kind"] = "together"
        self.later(400, lambda: self.follow(chaser, runner))

    def caught(self, runner, chaser):
        self.running = "boop"
        self.later(600, lambda: self.meet(chaser, runner, lambda: self.touch_after_chase(runner, chaser)))

    def touch_after_chase(self, runner, chaser):
        chaser.facing = -runner.facing
        chaser.do("together", ["sit_s", "boop"], 900, facing=chaser.facing)
        runner.do("together", ["sit_s", "boop"], 900, facing=runner.facing)
        self.later(2700, lambda: self.end(runner, chaser))

    def cuddle(self, a, b):
        self.begin("cuddle")
        mover, still = (b, a)   # the second cat comes to the first

        def settle():
            mover.facing = still.facing = random.choice((-1, 1))
            still.do("together", ["sleep_s"], 1000)
            r = random.random()
            if r < 0.45:
                mover.do("together", ["sleep_s"], 1000)
            elif r < 0.75:
                mover.do("together", ["sit_s"], 1000)                 # keeps watch beside it
            else:
                mover.do("together", ["lick1", "lick2"], 450)         # washes while the other sleeps
                self.later(random.uniform(8, 20) * 1000, lambda: mover.do("together", ["sleep_s"], 1000))
            self.later(int(random.uniform(90, 300) * 1000), lambda: self.end(a, b))
        still.do("together", ["sleep_s"], 1000)
        self.meet(mover, still, settle, gap=0.48)

    def come_over(self):
        p = self.pair()
        if p and not self.running and not p[0].busy():
            self.boop(*p)

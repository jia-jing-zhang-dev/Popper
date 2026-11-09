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

import furniture
import toys
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
TOY_SIZE = 1.6         # toys drawn this much bigger than true scale, so they read next to the cats
MARKS = {"thinking": "?", "talking": "!", "sleepy": "Zz"}

PLAY_FRAMES = ("crouch", "pounce", "bat1", "bat2", "stretch", "roll1", "roll2")
LIFE_FRAMES = ("eat1", "eat2", "drink1", "drink2", "scratch1", "scratch2", "arch", "tail1", "tail2", "rub1", "rub2")
HUNGER_HOURS = 4.0      # an empty stomach after this long
THIRST_HOURS = 1.5
MEAL = 0.25             # a meal takes this much of a full bowl
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
        self.toys = []
        self.meta = load_meta()
        self.toy_meta = toys.load_meta()
        self.prop_meta = furniture.load_meta()
        self.items = {}
        self.director = None
        CAT["name"] = self.names()[0]   # no card refresh yet: other features are still starting
        self.app.root.after(300, self.sync)
        self.app.root.after(1000, self.sync_loop)

    def menu_items(self, menu):
        menu.add_command(label=t("menu_cats"), command=self.open_skins)
        if self.cats and self.toy_meta and self.can_play():
            have = {toy.kind for toy in self.toys}
            for kind in toys.KINDS:
                if kind not in have:
                    menu.add_command(label=t(f"menu_toy_{kind}"), command=lambda k=kind: self.drop_toy(k))
            if self.toys:
                menu.add_command(label=t("menu_toys_away"), command=self.put_toys_away)
        if self.items:
            full = self.needs()["food"] >= 0.99
            menu.add_command(label=t("menu_feed_full") if full else t("menu_feed"), command=self.feed,
                             state="disabled" if full else "normal")

    def can_live(self):
        """The renders with eating, drinking, scratching... and the bowls, post and bed are there."""
        return self.prop_meta is not None and all(f in self.meta["anchors"]["adult"] for f in LIFE_FRAMES)

    # ---------- food, water, and what the cats need

    def needs(self):
        """{"food": bowl 0..1, "hunger": [per cat], "thirst": [per cat]}, brought up to date."""
        n = self.app.settings.get("pet_needs") or {"food": 1.0, "hunger": [0.3, 0.5], "thirst": [0.2, 0.4], "t": time.time()}
        now = time.time()
        dt = max(0.0, now - n.get("t", now)) / 3600
        n["hunger"] = [min(1.0, h + dt / HUNGER_HOURS) for h in n["hunger"]]
        n["thirst"] = [min(1.0, h + dt / THIRST_HOURS) for h in n["thirst"]]
        n["t"] = now
        self.app.settings["pet_needs"] = n
        return n

    def feed(self):
        """Fill the bowl; the cats come running and eat from either side."""
        n = self.needs()
        n["food"] = 1.0
        n["hunger"] = [max(h, 0.6) for h in n["hunger"]]   # nobody turns down a freshly filled bowl
        self.app.save()
        bowl = self.items.get("food")
        if not bowl:
            return
        bowl.show("foodfull")
        if self.director and self.director.running:
            self.director.end(*self.cats)
        cats = sorted(self.cats, key=lambda c: c.centre())
        sides = [-1, 1] if len(cats) == 2 else [-1 if cats[0].centre() < bowl.cx() else 1]
        for cat, side in zip(cats, sides):
            if not (cat.action and cat.action["kind"] in ("drag",)):
                cat.go_eat(bowl, side)

    def build_items(self):
        spots = self.app.settings.get("pet_items") or {}
        c = self.cats[0]
        sw = c.top.winfo_screenwidth()
        for name, (_, _, offset) in furniture.ITEMS.items():
            x = spots.get(name)
            item = furniture.Item(self, name, 0, c.ground - self.floor_gap(), self.base_scale())
            if x is None:
                x = c.x + c.w * 0.5 + offset * c.w - item.w / 2
            item.x = max(0, min(x, sw - item.w))
            item.place()
            self.items[name] = item
        self.items["food"].show("foodfull" if self.needs()["food"] > 0.01 else "foodempty")

    def can_play(self):
        """The renders with the play poses are there (older asset sets don't have them)."""
        return all(f in self.meta["anchors"]["adult"] for f in PLAY_FRAMES)

    # ---------- toys

    def base_scale(self):
        """Screen pixels per stored pixel for an adult cat (toys use it too, so they're cat-sized)."""
        ch = self.meta["canvas"][1]
        sit = self.meta["anchors"]["adult"]["sit"]
        adult_sit_h = ch - sit["head"][1] + abs(sit["ear_l"][0] - sit["ear_r"][0]) * 0.6
        return SIT_HEIGHT * self.app.scale / max(adult_sit_h, 1)

    def floor_gap(self):
        """Empty pixels under a standing cat's paws in the frames (screen px): toys sit on the paws' floor."""
        if not hasattr(self, "_floor_gap"):
            im = Image.open(os.path.join(ASSETS, "A_adult", "sit.webp"))
            self._floor_gap = im.height - im.getchannel("A").point(lambda a: 255 if a > 110 else 0).getbbox()[3]
        return self._floor_gap * self.base_scale()

    def drop_toy(self, kind, drop=True, x=None):
        if not self.cats or any(t_.kind == kind for t_ in self.toys):
            return
        c = self.cats[0]
        x = x if x is not None else c.centre() + random.choice((-1, 1)) * random.uniform(80, 220) * self.app.scale
        toy = toys.Toy(self, kind, x, c.ground - self.floor_gap(), self.base_scale() * TOY_SIZE, drop=drop)
        toy.kick(random.uniform(-120, 120) * self.app.scale)
        self.toys.append(toy)
        self.app.settings["pet_toys"] = [t_.kind for t_ in self.toys]
        self.app.save()

    def put_toys_away(self):
        for toy in self.toys:
            toy.top.destroy()
        self.toys = []
        self.app.settings["pet_toys"] = []
        self.app.save()

    def startle(self, toy):
        """A toy flying past fast makes a cat jump into an arch."""
        if not self.can_live() or abs(toy.vx) < 900 * self.app.scale:
            return
        for c in self.cats:
            busy = c.action and c.action["kind"] in ("together", "mood", "drag", "play", "arch")
            if not busy and abs(toy.cx() - c.centre()) < c.w * 0.35:
                c.do("arch", ["arch"], 1000, 1.2, facing=1 if toy.cx() > c.centre() else -1)
                c.hop(0.08)

    def answer_tease(self, toy):
        """You're playing with a toy: the nearest cat drops what it's doing (naps included) and goes for it;
        the other turns to watch, or joins in."""
        hunters = [c for c in self.cats if c.action and c.action.get("toy") is toy]
        if hunters:
            return
        free = [c for c in self.cats if not (c.action and c.action["kind"] in ("together", "mood", "drag"))]
        if not free:
            return
        if self.director and self.director.running:
            self.director.end(*self.cats)
        free.sort(key=lambda c: abs(c.centre() - toy.cx()))
        free[0].play(toy, rounds=2, chase=True)
        if len(free) > 1:
            other = free[1]
            if random.random() < 0.4:
                other.play(toy, rounds=1, chase=True)
            else:
                other.do("look", ["sit_s"], 1000, random.uniform(2, 4), facing=1 if toy.cx() > other.centre() else -1)

    def toy(self, kind=None):
        return next((t_ for t_ in self.toys if kind in (None, t_.kind)), None)

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
        if self.toy_meta and self.can_play():   # toys left out last time are still lying about
            for kind in self.app.settings.get("pet_toys") or []:
                if kind in toys.KINDS:
                    self.drop_toy(kind, drop=False, x=self.cats[0].centre() + random.uniform(-260, 260) * self.app.scale)
        if self.can_live():
            self.build_items()
        self.last_tick = time.time()
        self.last_save = time.time()
        self.tick()

    def teardown(self):
        for toy in self.toys:
            toy.top.destroy()
        self.toys = []
        for item in self.items.values():
            item.destroy()
        self.items = {}
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
        dt = min(0.1, now - self.last_tick)
        self.last_tick = now
        floor = self.cats[0].ground - self.floor_gap()
        for item in self.items.values():
            if item.ground != floor:
                item.ground = floor
                item.place()
        for toy in self.toys:
            toy.ground = floor
            toy.tick(dt)
            if toy.being_teased():
                self.answer_tease(toy)
            self.startle(toy)
        if self.items and now - self.last_save > 60:   # hunger and thirst carry on while the app is closed
            self.needs()
            self.app.save()
            self.last_save = now
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
        self.hop_size = 0.12
        self.hop_dx = 0.0
        self.last_kind = None
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
            lift = round(math.sin(math.pi * k) * self.h * self.hop_size)
        elev = self.action.get("elev", 0) if self.action else 0     # lying in the bed rests on its cushion
        self.top.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.ground - self.h - lift - elev)}")

    def centre(self):
        return self.x + self.w / 2

    def head_xy(self, frame="sit"):
        a = self.anchors[frame]["head"]
        return self.x + a[0] * self.scale, self.ground - self.h + a[1] * self.scale

    # ---------- actions: (frames, ms per frame, seconds) and optional movement

    def do(self, kind, frames, ms, seconds=None, target=None, speed=0.0, facing=None, mark=None, then=None, elev=0.0):
        self.action = {"kind": kind, "frames": frames, "ms": ms, "start": time.time(),
                       "until": time.time() + seconds if seconds else None, "target": target,
                       "speed": speed, "mark": mark, "then": then, "elev": elev}
        if facing:
            self.facing = facing
        elif target is not None:
            self.facing = 1 if target > self.x else -1

    def busy(self):
        a = self.action
        return a and a["kind"] in ("together", "mood", "drag", "eat", "drink")

    def sit(self, seconds):
        self.do("sit", ["sit"], 1000, seconds)

    def walk_to(self, x, then=None, run=False):
        sw = self.top.winfo_screenwidth()
        x = max(0, min(x, sw - self.w))
        speed = (150 if run else 48) * self.app.scale * (0.8 if skin_type(self.skin) == "kitten" else 1.0)
        self.do("move", RUN if run else WALK, 80 if run else 120, target=x, speed=speed, then=then)

    def hop(self, size=0.12, dx=0.0):
        if not self.hop_t:
            self.hop_t, self.hop_size, self.hop_dx = 12, size, dx / 12

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
            self.x += self.hop_dx
            moved = True
        if moved:
            self.place()
            if self.index == 0:
                self.app.place_window()

    def finish(self):
        then = self.action.get("then") if self.action else None
        self.last_kind = self.action["kind"] if self.action else None
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
        playful = pets.can_play()
        living = pets.can_live() and pets.items
        if living and self.look_after_itself():
            return
        if playful and self.last_kind == "nap" and random.random() < 0.75:
            self.last_kind = None
            if living and random.random() < 0.4:
                self.go_scratch(pets.items["post"])
            else:
                self.do("stretch", ["stretch"], 1000, random.uniform(1.4, 2.4), facing=random.choice((-1, 1)))
            return
        w = dict(self.personality)
        toy = self.reachable_toy() if playful else None
        if toy and not sleepy:
            w["play"] = (30 if unobserved else 6) * (4 if toy.recently_moved() else 1)
        if playful and unobserved and not sleepy:
            w["roll"] = 3
        if living:
            w["scratch"] = 5 if unobserved else 2
            w["arch"] = 0.6 if unobserved else 0
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
            if living and random.random() < 0.4:   # sitting with a slow swish of the tail
                self.do("sit", ["tail1", "sit", "tail2", "sit"], random.choice((700, 900)), random.uniform(4, 10))
            else:
                self.sit(random.uniform(4, 12))
        elif kind == "groom":
            self.do("groom", ["lick1", "lick2"], random.choice((380, 420, 470)), random.uniform(3, 7))
        elif kind == "yawn":
            self.do("yawn", ["yawn"], 1000, random.uniform(1.2, 2.0))
        elif kind == "look":
            self.facing = random.choice((-1, 1))
            self.do("look", ["sit_s"], 1000, random.uniform(3, 7))
        elif kind == "nap":
            seconds = random.uniform(60, 240) if sleepy else random.uniform(20, 90)
            if living and random.random() < 0.7:
                self.nap_in_bed(pets.items["bed"], seconds)
            else:
                self.do("nap", ["sleep"], 1000, seconds)
        elif kind == "scratch":
            self.go_scratch(pets.items["post"])
        elif kind == "arch":
            self.do("arch", ["arch"], 1000, 1.2, facing=random.choice((-1, 1)))
        elif kind == "play":
            self.play(toy, rounds=random.randint(1, 3))
        elif kind == "roll":
            self.do("roll", ["roll1", "roll2", "roll1", "roll2"], 450, random.uniform(2.0, 3.5))
        else:
            x = self.home + random.uniform(-roam, roam)
            self.walk_to(x, run=unobserved and random.random() < 0.15)

    def other(self):
        cats = self.pets.cats
        return next((c for c in cats if c is not self), None)

    # ---------- daily life: food, water, the post, the bed

    def look_after_itself(self):
        """Thirsty: a drink. Hungry: a meal, or with an empty bowl, sit by it and ask. True if it went."""
        n = self.pets.needs()
        i = min(self.index, len(n["hunger"]) - 1)
        items = self.pets.items
        if n["thirst"][i] > 0.6 and random.random() < 0.7:
            self.go_drink(items["water"])
            return True
        if n["hunger"][i] > 0.55:
            if n["food"] > 0.01:
                self.go_eat(items["food"])
                return True
            if n["hunger"][i] > 0.75 and random.random() < 0.5:
                self.beg(items["food"])
                return True
        return False

    def go_to(self, x, then, run=False):
        if abs(x - self.x) < 4:
            then()
        else:
            self.walk_to(x, then=then, run=run)

    def side_of(self, item):
        return -1 if self.centre() < item.cx() else 1

    def go_eat(self, bowl, side=None):
        """Walk to the bowl (from `side`: -1 left, +1 right) and eat; the meal comes out of the bowl."""
        side = side or self.side_of(bowl)
        facing = -side
        nose = bowl.cx() + side * bowl.w * 0.14
        x = self.x_for_nose(nose, facing, "eat1")

        def eat():
            if self.pets.needs()["food"] <= 0.01:
                return self.beg(bowl)
            self.do("eat", ["eat1", "eat2"], random.choice((380, 430, 480)), random.uniform(6, 11), facing=facing, then=done)

        def done():
            n = self.pets.needs()
            n["food"] = max(0.0, n["food"] - MEAL)
            n["hunger"][min(self.index, len(n["hunger"]) - 1)] = 0.0
            bowl.show("foodfull" if n["food"] > 0.01 else "foodempty")
            self.app.save()
            self.do("groom", ["lick1", "lick2"], 420, random.uniform(2, 4))   # a wash after a meal
        self.go_to(x, eat, run=True)
        if self.action and self.action["kind"] == "move":
            self.action["kind"] = "eat"

    def beg(self, bowl):
        """Sit by the empty bowl, look at you and meow now and then."""
        side = self.side_of(bowl)
        x = bowl.cx() + side * (bowl.w * 0.5 + self.w * 0.25) - self.w / 2

        def wait():
            self.do("beg", ["sit", "sit", "talk", "talk2", "sit", "sit", "sit"], 600, random.uniform(6, 12))
        self.go_to(x, wait)

    def go_drink(self, bowl):
        side = self.side_of(bowl)
        facing = -side
        x = self.x_for_nose(bowl.cx() + side * bowl.w * 0.10, facing, "drink1")

        def drink():
            self.do("drink", ["drink1", "drink2"], 340, random.uniform(3, 6), facing=facing, then=done)

        def done():
            n = self.pets.needs()
            n["thirst"][min(self.index, len(n["thirst"]) - 1)] = 0.0
            self.app.save()
        self.go_to(x, drink)
        if self.action and self.action["kind"] == "move":
            self.action["kind"] = "drink"

    def go_scratch(self, post):
        side = self.side_of(post)
        facing = -side
        x = self.x_for_nose(post.cx() + side * post.w * 0.22, facing, "scratch1")

        def scratch():
            self.do("scratch", ["scratch1", "scratch2"], 300, random.uniform(3, 5.5), facing=facing)
        self.go_to(x, scratch)

    def nap_in_bed(self, bed, seconds, offset=0.0, then=None, kind="nap"):
        """Curl up in the bed: lifted onto its cushion, with the front of the rim in front of the cat."""
        x = bed.cx() + offset - self.w / 2

        def lie():
            self.facing = random.choice((-1, 1)) if not offset else (1 if offset < 0 else -1)
            self.do(kind, ["sleep_s"], 1000, seconds, facing=self.facing, elev=bed.cushion(), then=then)
            self.place()
            bed.keep_front_on_top()
        self.go_to(x, lie)

    # ---------- playing with a toy

    def nose_x(self, frame):
        """Screen x of the cat's nose in a side frame, for the way it faces now."""
        hx = self.anchors[frame]["head"][0] * self.scale
        return self.x + (self.w - hx if self.facing > 0 else hx)

    def x_for_nose(self, nose, facing, frame="crouch"):
        """Where the window goes so the nose is at `nose` when facing that way."""
        hx = self.anchors[frame]["head"][0] * self.scale
        return nose - (self.w - hx if facing > 0 else hx)

    def reachable_toy(self):
        """A toy this cat may go after: the first cat carries the card, so only toys near its spot."""
        for toy in self.pets.toys:
            if self.index == 0 and abs(toy.cx() - (self.home + self.w / 2)) > 320 * self.app.scale:
                continue
            return toy
        return None

    def play(self, toy, rounds=1, then=None, chase=False):
        """Go up to the toy, crouch, maybe pounce, swat it away; again for a few rounds if it rolled off.
        While it's still moving (rolling, or in your hand) the cat runs after it and looks again."""
        if toy not in self.pets.toys:
            return then() if then else None
        if toy.moving():
            facing = 1 if toy.cx() > self.centre() else -1
            near = self.x_for_nose(toy.cx() - facing * (toy.r + 20 * self.app.scale), facing, "run0")
            if abs(near - self.x) > 12 * self.app.scale:
                self.walk_to(near, run=True, then=lambda: self.play(toy, rounds, then, chase))
            elif toy.drag is not None and random.random() < 0.35:   # dangled right above it: swipe at it
                self.do("play", ["bat1", "bat2"], 160, 0.32, facing=facing, then=lambda: self.play(toy, rounds, then, chase))
            else:   # right by it but it's still moving: watch it, crouched, then look again
                self.do("play", ["crouch"], 1000, 0.35, facing=facing, then=lambda: self.play(toy, rounds, then, chase))
            self.action["kind"] = "play"
            self.action["toy"] = toy
            return
        facing = -1 if self.centre() > toy.cx() else 1
        gap = toy.r + 10 * self.app.scale
        stand = self.x_for_nose(toy.cx() + (gap if facing < 0 else -gap), facing)
        far = abs(stand - self.x) > 260 * self.app.scale
        pounce = random.random() < 0.45
        if pounce:   # stop a leap short of it
            stand = self.x_for_nose(toy.cx() + (gap + 60 * self.app.scale) * (1 if facing < 0 else -1), facing)

        def at_toy():
            self.facing = 1 if toy.cx() > self.centre() else -1
            self.do("play", ["crouch"], 1000, random.uniform(0.6, 1.6) if not chase else random.uniform(0.3, 0.8),
                    facing=self.facing, then=leap if pounce else swat)
            self.action["toy"] = toy

        def leap():
            self.hop(0.22, 60 * self.app.scale * self.facing)
            self.do("play", ["pounce"], 1000, 0.75, facing=self.facing, then=swat)
            self.action["toy"] = toy

        def swat():
            self.do("play", ["bat1", "bat2"], 160, 0.32, facing=self.facing, then=hit)
            self.action["toy"] = toy

        def hit():
            if toy in self.pets.toys and abs(toy.cx() - self.nose_x("bat2")) < toy.r + 40 * self.app.scale:
                toy.kick(self.facing * random.uniform(260, 560) * self.app.scale, -random.uniform(0, 260) * self.app.scale)
            if rounds > 1 and toy in self.pets.toys:
                self.do("play", ["crouch"], 1000, random.uniform(0.3, 0.8), facing=self.facing,
                        then=lambda: self.play(toy, rounds - 1, then, chase))
                self.action["toy"] = toy
            elif then:
                then()
            else:
                self.do("look", ["sit_s"], 1000, random.uniform(1.5, 3), facing=self.facing)

        if abs(stand - self.x) < 4:
            at_toy()
        else:
            self.walk_to(stand, then=at_toy, run=far or chase)
            self.action["kind"] = "play"
        if self.action:
            self.action["toy"] = toy

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
        ball, yarn = self.pets.toy("ball"), self.pets.toy("yarn")
        games = {"boop": 4, "groom": 3, "chase": 2 if unobserved else 0, "cuddle": 1,
                 "rub": 3 if self.pets.can_live() else 0,
                 "pingpong": 5 if ball and unobserved else 0, "yarn_race": 4 if yarn and unobserved else 0}
        choice = random.choices(list(games), list(games.values()))[0]
        if choice == "groom":
            self.groom(*random.sample((a, b), 2))
        elif choice == "pingpong":
            self.pingpong(a, b, ball)
        elif choice == "yarn_race":
            self.yarn_race(a, b, yarn)
        elif choice == "rub":
            self.rub(*random.sample((a, b), 2))
        else:
            getattr(self, choice)(a, b)

    @staticmethod
    def face_each_other(a, b):
        """Turn the two cats toward each other (side frames face left; +1 mirrors them to face right)."""
        a.facing = 1 if b.centre() > a.centre() else -1
        b.facing = -a.facing

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
            self.face_each_other(mover, still)
            mover.do("together", ["sit_s", "boop"], 900, facing=mover.facing)
            still.do("together", ["sit_s", "boop"], 900, facing=still.facing)
            self.later(2700, lambda: self.end(a, b))
        self.meet(mover, still, touch)

    def groom(self, giver, receiver):
        self.begin("groom")

        def lick():
            self.face_each_other(giver, receiver)
            giver.do("together", ["groom1", "groom2"], 450, facing=giver.facing)
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
        self.face_each_other(chaser, runner)
        chaser.do("together", ["sit_s", "boop"], 900, facing=chaser.facing)
        runner.do("together", ["sit_s", "boop"], 900, facing=runner.facing)
        self.later(2700, lambda: self.end(runner, chaser))

    def rub(self, rubber, other):
        """One walks up and rubs its cheek against the other's, eyes closed."""
        self.begin("rub")

        def go():
            self.face_each_other(rubber, other)
            rubber.do("together", ["rub1", "rub2"], 520, facing=rubber.facing)
            other.do("together", ["groomed"], 1000, facing=other.facing)
            self.later(random.uniform(2500, 4500), lambda: self.end(rubber, other))
        self.meet(rubber, other, go, gap=0.52)

    def cuddle(self, a, b):
        bed = self.pets.items.get("bed") if self.pets.can_live() else None
        if bed:   # both curl up in the bed
            self.begin("cuddle")
            seconds = random.uniform(90, 300)
            for cat, off in ((a, -bed.w * 0.16), (b, bed.w * 0.16)):
                cat.nap_in_bed(bed, seconds, offset=off, kind="together")
                if cat.action:
                    cat.action["kind"] = "together"
            self.later(seconds * 1000, lambda: self.end(a, b))
            return
        self.begin("cuddle")
        mover, still = (b, a)   # the second cat comes to the first

        def settle():
            self.face_each_other(mover, still)        # curled up nose to nose
            still.do("together", ["sleep_s"], 1000, facing=still.facing)
            r = random.random()
            if r < 0.45:
                mover.do("together", ["sleep_s"], 1000, facing=mover.facing)
            elif r < 0.75:
                mover.do("together", ["sit_s"], 1000, facing=mover.facing)                 # keeps watch beside it
            else:
                mover.do("together", ["lick1", "lick2"], 450)         # washes while the other sleeps
                self.later(random.uniform(8, 20) * 1000, lambda: mover.do("together", ["sleep_s"], 1000, facing=mover.facing))
            self.later(int(random.uniform(90, 300) * 1000), lambda: self.end(a, b))
        still.do("together", ["sleep_s"], 1000)
        self.meet(mover, still, settle, gap=0.74)   # facing each other: room for both heads, nose to nose

    def pingpong(self, a, b, ball):
        """The two sit either side of the ball and swat it back and forth."""
        self.begin("pingpong")
        s = a.app.scale
        half = 150 * s
        mid = min(max(ball.cx(), half + 40), a.top.winfo_screenwidth() - half - 40)
        if a.index == 0:   # keep it near the first cat's spot, where the card is
            mid = min(max(mid, a.home + a.w / 2 - 200 * s), a.home + a.w / 2 + 200 * s)
        left, right = (a, b) if a.centre() < b.centre() else (b, a)
        gap = ball.r + 10 * s
        spots = {left: left.x_for_nose(mid - half + gap, 1), right: right.x_for_nose(mid + half - gap, -1)}
        ready = []

        def arrived(cat):
            cat.do("together", ["crouch"], 1000, facing=1 if cat is left else -1)
            ready.append(cat)
            if len(ready) == 2:
                ball.x = mid - ball.w / 2
                ball.kick(0)
                self.later(700, lambda: rally(random.choice((left, right)), random.randint(4, 8)))
        for cat in (left, right):
            cat.walk_to(spots[cat], then=lambda c=cat: arrived(c))
            cat.action["kind"] = "together"

        def rally(hitter, left_shots):
            if ball not in self.pets.toys:
                return self.end(a, b)
            receiver = right if hitter is left else left
            nose = hitter.nose_x("bat2")
            if abs(ball.cx() - nose) > ball.r + 60 * s:   # it stopped short: go and get it
                hitter.walk_to(hitter.x_for_nose(ball.cx() - hitter.facing * gap, hitter.facing),
                               then=lambda: rally(hitter, left_shots))
                hitter.action["kind"] = "together"
                return
            hitter.do("together", ["bat1", "bat2"], 160, facing=hitter.facing)
            dist = abs(receiver.nose_x("bat2") - ball.cx()) - ball.r
            ball.kick(hitter.facing * ball.speed_to_travel(dist * random.uniform(0.85, 1.1)))
            self.later(330, lambda: hitter.do("together", ["crouch"], 1000, facing=hitter.facing))
            if left_shots <= 1:
                self.later(2500, lambda: self.end(a, b))
            else:
                self.later(450, lambda: wait(receiver, left_shots - 1))

        def wait(cat, left_shots):
            if ball not in self.pets.toys:
                return self.end(a, b)
            if not ball.moving() or abs(ball.cx() - cat.nose_x("bat2")) < ball.r + 30 * s:
                rally(cat, left_shots)
            else:
                self.later(80, lambda: wait(cat, left_shots))

    def yarn_race(self, a, b, yarn):
        """One bats the yarn away and both chase it; whoever gets there first bats it again."""
        self.begin("yarn_race")
        rounds = [random.randint(2, 4)]

        def go():
            if yarn not in self.pets.toys or rounds[0] <= 0:
                return self.end(a, b)
            rounds[0] -= 1
            first, second = sorted((a, b), key=lambda c: abs(c.centre() - yarn.cx()))
            first.play(yarn, 1, then=after)
            if first.action:
                first.action["kind"] = "together"
            second.walk_to(second.x_for_nose(yarn.cx(), 1 if yarn.cx() > second.centre() else -1, "walk0"), run=True)
            second.action["kind"] = "together"

        def after():
            self.later(random.uniform(500, 1200), go)
        go()

    def come_over(self):
        p = self.pair()
        if p and not self.running and not p[0].busy():
            self.boop(*p)

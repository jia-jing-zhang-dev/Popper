"""泡泡's bond: studying brings you closer to 泡泡, who grows a little and unlocks things to wear.

How it is meant to motivate (self-determination theory and the research on rewards and learning):
- Points come from effortful learning: reviewing words (a forgotten word still earns: retrieval practice
  helps even when you miss), finishing tasks and goals, library visits. Time on its own earns little and is
  capped per day, so the bond says "you did the work" rather than "you sat there" (rewards tied to
  competence keep, not crowd out, interest).
- The bond never goes down and there is no streak to lose. Loss-framed streaks make a missed day feel like
  failure; a rest day here costs nothing.
- Unlocks are about 泡泡 (a nickname, things it wears, a little growth), which is about relatedness, and they
  are never required for anything.

Points are worked out from what the other features already store (finished tasks and goals, library
visits, study time), so history before this feature counts too. Word reviews have no log of their own, so `Vocab.grade` calls `award` directly.
"""

import datetime as dt
import math
import os
import sqlite3
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, GOOD, PANEL

GOLD = "#ffd166"
HEART = "#ff8fab"

TASK_POINTS = 5
GOAL_POINTS = 30
LIBRARY_POINTS = 5       # a library visit of at least LIBRARY_MIN
LIBRARY_MIN = 15 * 60
WORD_POINTS = {True: 2, False: 1}
FOCUS_SECONDS_PER_POINT = 10 * 60   # an hour of study = 6, about one finished task
DAILY_CAP = {"word": 30, "focus": 30}   # time and quick flash cards can't outweigh real practice

SOURCES = ("word", "task", "goal", "library", "focus")

# Something to wear, and the level that unlocks it. The nickname unlocks at NICKNAME_LEVEL.
ACCESSORIES = [("sprout", 2), ("bow", 4), ("cap", 6), ("star", 9), ("crown", 12)]
NICKNAME_LEVEL = 3
TITLES = [(1, "bond_t1"), (3, "bond_t2"), (5, "bond_t3"), (8, "bond_t4"), (12, "bond_t5"), (16, "bond_t6")]
GROWTH_PER_LEVEL = 0.02
MAX_GROWTH = 1.24


def level_start(level):
    """Points needed to reach `level`: each level takes 20 more than the one before (30, 50, 70...)."""
    n = level - 1
    return 30 * n + 10 * n * (n - 1)


def level_of(points):
    """(level, points into this level, points this level takes)."""
    level = 1
    while points >= level_start(level + 1):
        level += 1
    start = level_start(level)
    return level, points - start, level_start(level + 1) - start


def title_key(level):
    return [key for at, key in TITLES if level >= at][-1]


def growth(level):
    return min(MAX_GROWTH, 1 + GROWTH_PER_LEVEL * (level - 1))


def unlocked(level):
    return [name for name, at in ACCESSORIES if level >= at]


def unlocks_between(old, new):
    """What reaching `new` from `old` unlocks, as i18n keys."""
    keys = [f"bond_acc_{name}" for name, at in ACCESSORIES if old < at <= new]
    if old < NICKNAME_LEVEL <= new:
        keys.insert(0, "bond_unlock_nick")
    return keys


def day_start(day):
    return time.mktime(day.timetuple())


def award(db, source, ref, points, ts=None):
    """Record points once per (source, ref), within the source's daily cap. Returns the points given."""
    ts = ts or time.time()
    try:
        cap = DAILY_CAP.get(source)
        if cap is not None:
            day = dt.date.fromtimestamp(ts)
            (got,) = db.execute("SELECT COALESCE(SUM(points), 0) FROM bond_points WHERE source=? AND ts >= ? AND ts < ?",
                                (source, day_start(day), day_start(day + dt.timedelta(days=1)))).fetchone()
            points = min(points, cap - got)
        if points <= 0:
            return 0
        cur = db.execute("INSERT OR IGNORE INTO bond_points (source, ref, ts, points) VALUES (?, ?, ?, ?)",
                         (source, ref, ts, points))
        db.commit()
        return points if cur.rowcount else 0
    except sqlite3.OperationalError:  # the table isn't there yet (bond never started)
        return 0


class BondStore:
    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS bond_points (
                          source TEXT NOT NULL,   -- word / task / goal / library / focus
                          ref    TEXT NOT NULL,   -- what earned it (row id, or the day for study time)
                          ts     REAL NOT NULL,
                          points INTEGER NOT NULL,
                          PRIMARY KEY (source, ref))""")
        db.commit()
        self.focus_synced = None  # days before this one have their study-time points final

    # ---------- collecting points from the other features' data

    def _copy(self, sql, args=()):
        """INSERT OR IGNORE rows (source, ref, ts, points) chosen by a SELECT on another feature's table."""
        try:
            self.db.execute("INSERT OR IGNORE INTO bond_points (source, ref, ts, points) " + sql, args)
        except sqlite3.OperationalError:  # that feature's table doesn't exist yet
            pass

    def sync(self, focus_log=None, now=None):
        """Pick up everything earned since last time. Returns the points added."""
        now = now or time.time()
        before = self.total()
        self._copy("SELECT 'task', id, done_at, ? FROM todos WHERE done=1 AND done_at IS NOT NULL", (TASK_POINTS,))
        self._copy("SELECT 'goal', id, done_at, ? FROM goals WHERE done=1 AND done_at IS NOT NULL", (GOAL_POINTS,))
        self._copy("SELECT 'library', id, \"end\", ? FROM library_sessions WHERE \"end\" - start >= ?",
                   (LIBRARY_POINTS, LIBRARY_MIN))
        if focus_log is not None:
            self.sync_focus(focus_log, now)
        self.db.commit()
        return self.total() - before

    def sync_focus(self, log, now):
        """Study time: a point per 10 minutes, up to the daily cap. Past days once, then today and yesterday."""
        today = dt.date.fromtimestamp(now)
        first = self.focus_synced
        if first is None:
            row = self.db.execute("SELECT MIN(minute) FROM focus_activity").fetchone() if self._has("focus_activity") else None
            first = dt.date.fromtimestamp(row[0] * 60) if row and row[0] else today
        day = min(first, today - dt.timedelta(days=1))
        while day <= today:
            start, end = day_start(day), day_start(day + dt.timedelta(days=1))
            study, _ = log.split(log.by_key(start, end))
            points = min(DAILY_CAP["focus"], int(study // FOCUS_SECONDS_PER_POINT))
            if points:
                # only ever up: the day's points grow as the day goes on
                self.db.execute("INSERT INTO bond_points (source, ref, ts, points) VALUES ('focus', ?, ?, ?) "
                                "ON CONFLICT (source, ref) DO UPDATE SET points = MAX(points, excluded.points)",
                                (day.isoformat(), min(end - 1, now), points))
            day += dt.timedelta(days=1)
        self.focus_synced = today

    def _has(self, table):
        return bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())

    # ---------- reading

    def total(self):
        return self.db.execute("SELECT COALESCE(SUM(points), 0) FROM bond_points").fetchone()[0]

    def between(self, start, end):
        """{source: points} earned in a time range."""
        return {r[0]: r[1] for r in self.db.execute(
            "SELECT source, SUM(points) FROM bond_points WHERE ts >= ? AND ts < ? GROUP BY source", (start, end))}

    def recent(self, n=8):
        return self.db.execute("SELECT * FROM bond_points ORDER BY ts DESC LIMIT ?", (n,)).fetchall()


# ---------- what 泡泡 wears

def wear(img, kind):
    """Draw an accessory on 泡泡 (an RGBA image with the pet near the bottom), sitting on top of its head."""
    if not kind:
        return img
    box = img.getchannel("A").point(lambda a: 255 if a > 200 else 0).getbbox()
    if not box:
        return img
    x0, y0, x1, y1 = box
    w = x1 - x0
    cx = (x0 + x1) / 2
    # the ears stick up above the head, so find where the head itself starts in the middle columns
    mask = img.getchannel("A").crop((int(cx - w * 0.08), y0, int(cx + w * 0.08), y1)).point(lambda a: 255 if a > 200 else 0)
    head = mask.getbbox()
    top = y0 + (head[1] if head else (y1 - y0) * 0.10) + w * 0.03  # sink in a little so it sits, not floats
    d = ImageDraw.Draw(img)
    lw = max(2, round(w * 0.03))
    ink = (31, 36, 48, 255)
    if kind == "sprout":
        green, dark = (110, 200, 110, 255), (50, 130, 60, 255)
        d.line((cx, top + w * 0.02, cx, top - w * 0.16), fill=dark, width=lw)
        for sx in (-1, 1):
            lx = cx + sx * w * 0.10
            d.ellipse((lx - w * 0.10, top - w * 0.24, lx + w * 0.10, top - w * 0.13), fill=green, outline=dark,
                      width=max(1, lw // 2))
    elif kind == "bow":
        pink, deep = (255, 140, 170, 255), (210, 80, 120, 255)
        bx, by, s = cx + w * 0.22, top + w * 0.02, w * 0.13
        d.polygon([(bx, by), (bx - s * 1.4, by - s), (bx - s * 1.4, by + s)], fill=pink, outline=deep)
        d.polygon([(bx, by), (bx + s * 1.4, by - s), (bx + s * 1.4, by + s)], fill=pink, outline=deep)
        d.ellipse((bx - s * 0.4, by - s * 0.4, bx + s * 0.4, by + s * 0.4), fill=deep)
    elif kind == "cap":  # graduation cap: a board on a band, with a tassel
        hw, gold = w * 0.30, (255, 209, 102, 255)
        d.rectangle((cx - hw * 0.55, top - w * 0.06, cx + hw * 0.55, top + w * 0.05), fill=ink)
        d.polygon([(cx - hw, top - w * 0.10), (cx, top - w * 0.20), (cx + hw, top - w * 0.10), (cx, top - w * 0.01)],
                  fill=(45, 52, 70, 255), outline=ink)
        d.line((cx, top - w * 0.10, cx + hw * 0.85, top - w * 0.06, cx + hw * 0.85, top + w * 0.10), fill=gold, width=lw)
        d.ellipse((cx + hw * 0.85 - lw * 1.5, top + w * 0.08, cx + hw * 0.85 + lw * 1.5, top + w * 0.08 + lw * 3),
                  fill=gold)
    elif kind == "star":
        r, sx, sy = w * 0.11, cx + w * 0.20, top - w * 0.02
        pts = []
        for i in range(10):
            a = math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((sx + rr * math.cos(a), sy - rr * math.sin(a)))
        d.polygon(pts, fill=(255, 214, 102, 255), outline=(220, 160, 40, 255))
    elif kind == "crown":
        hw, gold, edge = w * 0.22, (255, 209, 102, 255), (200, 140, 30, 255)
        base, peak = top + w * 0.03, top - w * 0.17
        d.polygon([(cx - hw, base), (cx - hw, peak + w * 0.05), (cx - hw * 0.5, base - w * 0.08), (cx, peak),
                   (cx + hw * 0.5, base - w * 0.08), (cx + hw, peak + w * 0.05), (cx + hw, base)],
                  fill=gold, outline=edge)
        for gx, col in ((cx - hw * 0.55, (120, 200, 255, 255)), (cx, (255, 120, 150, 255)), (cx + hw * 0.55, (120, 200, 255, 255))):
            rr = w * 0.025
            d.ellipse((gx - rr, base - w * 0.05 - rr, gx + rr, base - w * 0.05 + rr), fill=col)
    return img


def preview(kind, size, frame=0):
    """泡泡 wearing `kind`, on a transparent background, for the bond window."""
    from features.pet import ASSETS
    rgba = Image.open(os.path.join(ASSETS, f"frame_{frame:02d}.png")).convert("RGBA")
    inner = round(size * 0.80)  # leave headroom for what it wears
    rgba.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(rgba, ((size - rgba.width) // 2, size - rgba.height))
    return wear(canvas, kind)


def tk_preview(kind, size, bg):
    img = preview(kind, size)
    base = Image.new("RGBA", img.size, bg)
    base.alpha_composite(img)
    return ImageTk.PhotoImage(base.convert("RGB"))


def hex_rgba(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


# ---------- windows

class BondWindow:
    """Level, progress, what earned bond this week, the nickname and the wardrobe."""

    def __init__(self, feature):
        self.app = app = feature.app
        self.feat = feature
        s = app.scale
        top = self.top = tk.Toplevel(app.root)
        top.title(t("bond_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.geometry(f"{int(500 * s)}x{int(560 * s)}")
        top.bind("<Escape>", lambda e: top.destroy())
        self.images = []
        self.body = tk.Frame(top, bg=BG)
        self.body.pack(fill="both", expand=True, padx=int(20 * s), pady=int(16 * s))
        self.refresh()

    def refresh(self):
        app, s, feat = self.app, self.app.scale, self.feat
        for w in self.body.winfo_children():
            w.destroy()
        self.images = []
        total = feat.store.total()
        level, into, need = level_of(total)
        f = lambda size: app.font("Microsoft YaHei UI", size)

        head = tk.Frame(self.body, bg=BG)
        head.pack(fill="x")
        img = tk_preview(feat.hat(), int(110 * s), hex_rgba(BG))
        self.images.append(img)
        tk.Label(head, image=img, bg=BG).pack(side="left")
        right = tk.Frame(head, bg=BG)
        right.pack(side="left", fill="x", expand=True, padx=(int(14 * s), 0))
        tk.Label(right, text=t("bond_level", level=level), bg=BG, fg=HEART, font=app.font("Segoe UI Semibold", 22)).pack(anchor="w")
        tk.Label(right, text=t(title_key(level)), bg=BG, fg=FG, font=f(13)).pack(anchor="w")
        bar = tk.Canvas(right, height=int(12 * s), bg=PANEL, highlightthickness=0)
        bar.pack(fill="x", pady=(int(8 * s), int(2 * s)))
        # its width is only known once laid out, so fill it on every resize
        bar.bind("<Configure>", lambda e: (bar.delete("all"),
                                           bar.create_rectangle(0, 0, int(e.width * into / need), e.height,
                                                                fill=HEART, width=0)))
        tk.Label(right, text=t("bond_progress", into=into, need=need, next=level + 1, total=total), bg=BG, fg=FG_DIM,
                 font=f(9)).pack(anchor="w")

        today = dt.date.today()
        week0 = today - dt.timedelta(days=today.weekday())
        week = feat.store.between(day_start(week0), time.time() + 1)
        day = feat.store.between(day_start(today), time.time() + 1)
        tk.Label(self.body, text=t("bond_week", week=sum(week.values()), today=sum(day.values())), bg=BG, fg=GOOD,
                 font=f(11)).pack(anchor="w", pady=(int(14 * s), int(4 * s)))

        # the nickname sits above the lists that change size (Entry pitfall in CLAUDE.md)
        nick = tk.Frame(self.body, bg=BG)
        nick.pack(fill="x", pady=(int(4 * s), int(6 * s)))
        tk.Label(nick, text=t("bond_nick"), bg=BG, fg=FG, font=f(10)).pack(side="left")
        if level >= NICKNAME_LEVEL:
            var = tk.StringVar(value=app.settings.get("bond_nick", ""))
            entry = tk.Entry(nick, textvariable=var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=f(10),
                             width=16)
            entry.pack(side="left", padx=(int(8 * s), 0), ipady=2)
            save = lambda e=None: feat.set_nick(var.get())
            entry.bind("<Return>", save)
            entry.bind("<FocusOut>", save)
            tk.Label(nick, text=t("bond_nick_hint"), bg=BG, fg=FG_DIM, font=f(8)).pack(side="left", padx=(8, 0))
        else:
            tk.Label(nick, text=t("bond_locked", level=NICKNAME_LEVEL), bg=BG, fg=FG_DIM, font=f(10)).pack(
                side="left", padx=(8, 0))

        tk.Label(self.body, text=t("bond_wardrobe"), bg=BG, fg=FG, font=f(11)).pack(anchor="w", pady=(int(8 * s), 4))
        shelf = tk.Frame(self.body, bg=BG)
        shelf.pack(fill="x")
        worn = feat.hat()
        for name, at in [(None, 1)] + ACCESSORIES:
            open_ = level >= at
            cell = tk.Frame(shelf, bg=PANEL if name != worn else ACCENT, padx=2, pady=2)
            cell.pack(side="left", padx=(0, int(6 * s)))
            inner = tk.Frame(cell, bg=PANEL)
            inner.pack()
            pic = tk_preview(name if open_ else None, int(56 * s), hex_rgba(PANEL))
            self.images.append(pic)
            label = tk.Label(inner, image=pic, bg=PANEL, cursor="hand2" if open_ else "")
            label.pack()
            text = t(f"bond_acc_{name}" if name else "bond_acc_none") if open_ else t("bond_locked", level=at)
            cap = tk.Label(inner, text=text, bg=PANEL, fg=FG if open_ else FG_DIM, font=f(8))
            cap.pack(pady=(0, 2))
            if open_:
                for w in (label, cap, inner):
                    w.bind("<Button-1>", lambda e, n=name: feat.set_hat(n))

        tk.Label(self.body, text=t("bond_this_week"), bg=BG, fg=FG, font=f(11)).pack(anchor="w", pady=(int(14 * s), 4))
        box = tk.Frame(self.body, bg=PANEL, padx=10, pady=6)
        box.pack(fill="x")
        rows = [(src, week[src]) for src in SOURCES if week.get(src)]
        for src, pts in rows:
            line = tk.Frame(box, bg=PANEL)
            line.pack(fill="x")
            tk.Label(line, text=t(f"bond_src_{src}"), bg=PANEL, fg=FG, font=f(10)).pack(side="left")
            tk.Label(line, text=f"+{pts} ♥", bg=PANEL, fg=HEART, font=f(10)).pack(side="right")
        if not rows:
            tk.Label(box, text=t("bond_none_yet"), bg=PANEL, fg=FG_DIM, font=f(10)).pack(anchor="w")
        tk.Label(self.body, text=t("bond_how"), bg=BG, fg=FG_DIM, font=f(8), justify="left",
                 wraplength=int(450 * s)).pack(anchor="w", pady=(int(12 * s), 0))


class LevelUp:
    """泡泡 levelled up: a small card with what it unlocked."""

    def __init__(self, app, level, old, first=False):
        app.set_mood("celebrate", 8)
        app.hop()
        s = app.scale
        top = self.top = tk.Toplevel(app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=PANEL, highlightthickness=2, highlightbackground=HEART)
        body = tk.Frame(top, bg=PANEL, padx=int(36 * s), pady=int(20 * s))
        body.pack()
        f = lambda size: app.font("Microsoft YaHei UI", size)
        hat = app.feature("bond").hat()
        pic = tk.Label(body, bg=PANEL)
        pic.img = tk_preview(hat, int(100 * s), hex_rgba(PANEL))  # nothing else keeps this card object alive
        pic.configure(image=pic.img)
        pic.pack()
        tk.Label(body, text=t("bond_welcome" if first else "bond_levelup", level=level), bg=PANEL, fg=HEART,
                 font=f(18)).pack(pady=(6, 2))
        tk.Label(body, text=t(title_key(level)), bg=PANEL, fg=FG, font=f(12)).pack()
        for key in unlocks_between(old, level):
            tk.Label(body, text="✦ " + t("bond_unlocked", what=t(key)), bg=PANEL, fg=GOLD, font=f(11)).pack(pady=(6, 0))
        ok = tk.Button(body, text=t("cheer_ok"), command=top.destroy, bg=HEART, fg=BG, activebackground=HEART,
                       activeforeground=BG, relief="flat", bd=0, padx=int(28 * s), pady=int(6 * s), cursor="hand2",
                       font=f(12))
        ok.pack(pady=(16, 0))
        for key in ("<Return>", "<space>", "<Escape>"):
            top.bind(key, lambda e: top.destroy())
        top.update_idletasks()
        x = (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2
        y = (top.winfo_screenheight() - top.winfo_reqheight()) // 3
        top.geometry(f"+{x}+{y}")
        top.after(30_000, lambda: top.winfo_exists() and top.destroy())

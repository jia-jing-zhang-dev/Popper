"""Record the demo footage: the cats reel (docs/demo.gif, stills docs/*.png) or the study-day reel.

    DEMO_REEL=cats  (default)  looking a word up, the cats playing, petting, a pomodoro that feeds them
    DEMO_REEL=study            Spanish and Japanese lookups, study time, the daily report, a level-up
    DEMO_DRY=3,9,15            no filming: screenshots at those seconds into the scenes (demo/_work/dry_*.png)

Unlike record.py, nothing here touches the real mouse or keyboard: the app runs in this process with a
throw-away data folder (demo/_work/home) full of made-up study data, every step is driven from inside
(root.after), the cursor you see is a small drawn window, and a plain full-screen "desk" with a book page
hides whatever else is on the screen. ffmpeg films only the area around the cats.

    .venv\\Scripts\\python demo\\record_cats.py        (about a minute; Esc stops it)
"""

import ctypes
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work")
HOME = os.path.join(WORK, "home")
DOCS = os.path.join(ROOT, "docs")
REEL = os.environ.get("DEMO_REEL", "cats")
DRY = [float(v) for v in os.environ.get("DEMO_DRY", "").split(",") if v]
RAW = os.path.join(WORK, f"{REEL}_raw.mp4")

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
from ctypes import wintypes  # noqa: E402

# 64-bit handles: without these, HWND_TOPMOST (-1) goes in as a 32-bit int and SetWindowPos quietly fails
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
HWND_TOPMOST = wintypes.HWND(-1)
SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def work_area_bottom():
    from ctypes import wintypes
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.bottom


GROUND = work_area_bottom()
# the filmed area: centred, ending at the floor the cats walk on
CAP_W, CAP_H = 1600, 820
CAP_X, CAP_Y = 0, GROUND - CAP_H + 6     # the left edge, where the desktop icons are
OUT_W = 680

# ---------------------------------------------------------------- a fresh, made-up home

shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["WORD_POPPER_HOME"] = HOME
mid = CAP_X + CAP_W // 2
json.dump({
    "ui_lang": "en", "learn": "en", "native": "zh-CN", "text_size": "large" if REEL == "cats" else "normal",
    "listening": True,
    "features": {"pet": True, "bond": True, "buddy": False, "review": True, "todos": True, "pomodoro": True,
                 "focus": True, "library": False, "journal": True, "report": False, "usage": False},
    "pet_two": True, "pet_skins": ["B_adult", "G_kitten"], "pet_ground": GROUND,
    "pet_x": mid - 420, "pet2_x": mid - 60, "pet_furniture": True, "pet_toys": [],
    "pet_items": {"water": CAP_X + 60, "food": CAP_X + 230, "bed": mid + 250, "post": CAP_X + CAP_W - 190},
    "pet_meals": 0, "pet_needs": {"food": 0.0, "hunger": [0.3, 0.3], "thirst": [0.0, 0.0], "t": time.time()},
}, open(os.path.join(HOME, "settings.json"), "w"))

sys.path.insert(0, ROOT)
os.chdir(ROOT)
import word_popper  # noqa: E402
import features.bond  # noqa: E402

if REEL == "cats":
    features.bond.LevelUp = lambda *a, **k: None   # the seeded data levels the bond up: no level-up card mid-film

def fetch_translation(word, learn="en", tries=12, need_roman=False):
    """Look the demo word up once before anything is filmed (the free translation endpoint rate-limits after a
    lot of testing: wait and try again). The card then shows this real result, without a second request."""
    import lookup
    for k in range(tries):
        try:
            result = lookup.look_up(word, learn, "zh-CN")
            if result and result.get("trans") and (result.get("pron") or not need_roman):
                return result
            print(f"{word}: no pronunciation yet (Google still unavailable?)", flush=True)
        except Exception as e:  # HTTP 429 and friends
            print(f"translation not available yet ({e}); trying again in 2 min", flush=True)
        time.sleep(120)
    print("translation still unavailable: not filming", flush=True)
    sys.exit(4)


if REEL == "study":   # Japanese needs Google for its romaji: wait for it rather than film without
    TRANSLATED = {"aprendizaje": fetch_translation("aprendizaje", "es"),
                  "少しずつ": fetch_translation("少しずつ", "ja", need_roman=not DRY)}
else:
    TRANSLATED = {"ubiquitous": fetch_translation("ubiquitous")}
_real_look_up = word_popper.look_up
word_popper.look_up = lambda word, learn, native: TRANSLATED.get(word) or _real_look_up(word, learn, native)

app = word_popper.App()
app.speak_item = lambda item: None          # no sound while filming
pets, pomo = app.feature("pet"), app.feature("pomodoro")
db = app.vocab.db


def seed():
    """Five weeks of plausible (invented) studying, for the stills and the bond level."""
    random.seed(7)
    today = dt.date.today()
    rows = []
    study = ["app:code.exe", "web:Brightspace", "app:acrord32.exe", "web:Gradescope", "app:notion.exe"]
    other = ["web:YouTube", "app:discord.exe"]
    for back in range(36):
        day = today - dt.timedelta(days=back)
        if random.random() < 0.15:
            continue
        start = dt.datetime.combine(day, dt.time(9 + random.randint(0, 3), random.randint(0, 59))).timestamp()
        for i in range(random.randint(100, 330)):
            key = random.choice(study) if random.random() < 0.82 else random.choice(other)
            rows.append((int((start + i * 60 + (i // 50) * 600) // 60), key, 55.0))
    db.executemany("INSERT OR IGNORE INTO focus_activity (minute, key, seconds) VALUES (?, ?, ?)", rows)
    now = time.time()
    words = [("acknowledged", "公认的"), ("ephemeral", "短暂的"), ("meticulous", "一丝不苟的"), ("closure", "闭包"),
             ("recursion", "递归"), ("serendipity", "意外发现"), ("heuristic", "启发式的")]
    for i, (w, tr) in enumerate(words):
        db.execute("INSERT OR IGNORE INTO words (word, trans, added, last_seen) VALUES (?, ?, ?, ?)",
                   (w, tr, now - 3600 * (i + 1), now - 3600 * (i + 1)))
    for text, spent, ago in (("Problem set 4: graphs", 5400, 2), ("Read chapter 7", 2400, 4), ("Lab report draft", 3600, 30)):
        db.execute("INSERT INTO todos (text, done, created, done_at, spent) VALUES (?, 1, ?, ?, ?)",
                   (text, now - 86400 * 2, now - 3600 * ago, spent))
    db.execute("INSERT INTO goals (title, deadline, done, created) VALUES ('Algorithms midterm', ?, 0, ?)",
               ((today + dt.timedelta(days=4)).isoformat(), now - 86400 * 20))
    db.commit()
    app.journal.save(today, "Dijkstra finally made sense once I drew the queue by hand. Tomorrow: practice problems.")
    for i in range(2):
        pomo.store.add(now - 3600 * (i + 2), now - 3600 * (i + 2) + 1500, 25)
    app.feature("bond").store.sync(app.feature("focus").log)   # straight to the store: no level-up card mid-film
    if REEL == "study":
        seed_study(now, today)


def seed_study(now, today):
    import bond
    rows = []      # an app not sorted yet, used every day this week: it tops the list in the study-time window
    for back in range(7):
        start = dt.datetime.combine(today - dt.timedelta(days=back), dt.time(16, 20)).timestamp()
        rows += [(int(start // 60) + i, "app:goodnotes.exe", 58.0) for i in range(55 if back == 0 else 45)]
    db.executemany("INSERT OR IGNORE INTO focus_activity (minute, key, seconds) VALUES (?, ?, ?)", rows)
    app.todos.add("Read: Retrieval practice paper")
    STUDY["task"] = db.execute("SELECT MAX(id) FROM todos").fetchone()[0]
    store = app.feature("bond").store
    have = store.total()
    nxt = max(9, bond.level_of(have)[0] + 1)              # level 9 unlocks the star clip
    target = bond.level_start(nxt) - bond.TASK_POINTS + 1    # ticking the task reaches it
    if have < target:
        db.execute("INSERT OR IGNORE INTO bond_points (source, ref, ts, points) VALUES ('focus', 'demo-earlier', ?, ?)",
                   (now - 86400 * 3, target - have))
        db.commit()
    app.settings["bond_seen_level"] = bond.level_of(store.total())[0]
    app.settings["bond_hat"] = "cap"
    app.feature("bond").restyle()
    store.sync = lambda *a, **k: 0     # the app's own bond timer waits: the level-up comes on cue (m_levelup)


STUDY = {}

# ---------------------------------------------------------------- the desk, captions and a drawn cursor

from PIL import ImageTk  # noqa: E402

desk = tk.Toplevel(app.root)
desk.overrideredirect(True)
desk.geometry(f"{SW}x{SH}+0+0")
desk.attributes("-topmost", True)   # covers everything of the owner's; restack() keeps the demo's windows above it
sys.path.insert(0, HERE)
import desktop_look  # noqa: E402

WALL = desktop_look.desktop_image((SW, SH), 8, 10, scale=1.5, app_icon=word_popper.app_icon())
wall_img = ImageTk.PhotoImage(WALL)
tk.Label(desk, image=wall_img, borderwidth=0).place(x=0, y=0)

# A real browser window: Edge with a brand-new, empty profile (no bookmarks, account or history of the owner's),
# in app mode (no address bar), showing demo/book.html from a local server (so no file path in the title bar).
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
EDGE_RECT = (CAP_X + 190, CAP_Y + 12, 1180, 600)    # x, y, w, h on screen (right of the icon column)
SELECT_AT = 20000                                    # ms after the page loads that it selects the word


PAPER_PATH = "/papers/retrieval-practice"
PAPER_QUERY = f"select=ubiquitous&at={SELECT_AT}&report=pos"
NOTES_PATH = "/notes/week-11"
NOTES_QUERY = f"select=aprendizaje,少しずつ&at={SELECT_AT},{SELECT_AT + 6000}&report=pos"
REPORT_PATH = "/inbox/study-report"
REPORT_HTML = [""]     # made on the Tk thread (sqlite), served by the server thread
AUTOSCROLL = """<script>setTimeout(() => { const t0 = performance.now();
  const H = document.documentElement.scrollHeight - innerHeight;
  const f = n => { const k = Math.min(1, (n - t0) / 7500); scrollTo(0, H * k * k * (3 - 2 * k)); if (k < 1) requestAnimationFrame(f); };
  requestAnimationFrame(f); }, 1500);</script>"""
FIRST_PAGE = NOTES_PATH if REEL == "study" else PAPER_PATH


def serve_demo_folder():
    import functools
    import http.server
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            pages = {PAPER_PATH: ("paper.html", PAPER_QUERY), NOTES_PATH: ("notes.html", NOTES_QUERY)}
            if path in pages or path == REPORT_PATH:   # the demo's pages, with their settings baked in
                if path == REPORT_PATH:
                    html = REPORT_HTML[0].replace("</body>", AUTOSCROLL + "</body>", 1)
                else:
                    name, query = pages[path]
                    html = open(os.path.join(HERE, name), encoding="utf-8").read()
                    html = html.replace("<script>", f"<script>window.DEMO_QUERY = {json.dumps(query)};", 1)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

        def log_message(self, *a):
            pass
    handler = functools.partial(Handler, directory=HERE)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


PORT = serve_demo_folder()
EDGE_PROFILE = os.path.join(WORK, "edge-profile")
shutil.rmtree(EDGE_PROFILE, ignore_errors=True)
edge_proc = subprocess.Popen([EDGE, f"--user-data-dir={EDGE_PROFILE}", "--no-first-run", "--no-default-browser-check",
                              "--disable-sync", "--force-device-scale-factor=1.25", "--new-window", "--test-type",
                              "--disable-features=Translate,TranslateUI,msEdgeTranslate",
                              f"--host-resolver-rules=MAP lab.example 127.0.0.1:{PORT}",
                              f"http://lab.example{FIRST_PAGE}"])
edge = {"hwnd": None, "found": None, "word": None, "before": None}


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def find_edge():
    """Edge's window, by the page's title; the page briefly reports where the word is ("pos:x,y,dpr")."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        title = window_title(hwnd)
        if user32.IsWindowVisible(hwnd) and (title.startswith("pos:") or "Retrieval Practice" in title
                                             or "reading notes" in title):
            found.append((hwnd, title))
        return True
    user32.EnumWindows(each, 0)
    for hwnd, title in found:
        if os.environ.get("DEMO_TITLES"):
            print("title", hwnd, repr(title), flush=True)
        if edge["hwnd"] is None:
            x, y, w, h = EDGE_RECT
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, 0x40)      # SWP_SHOWWINDOW
            edge["hwnd"], edge["found"] = hwnd, time.time()
            edge["before"] = title.split(" - ")[0] if title.startswith("pos:") else ""
            continue          # the page reports the word's place again after this resize
        # a report made before we moved the window has the old numbers: wait for one that differs
        if title.startswith("pos:") and edge["hwnd"] == hwnd and title.split(" - ")[0] != edge["before"]:
            from ctypes import wintypes
            import re
            body = title[4:].split(" - ")[0]
            if ";" in body:                 # several words: "x,y;x,y;dpr"
                *spots, dpr = body.split(";")
                spots = [tuple(float(v) for v in spot.split(",")) for spot in spots]
            else:
                px, py, dpr = re.match(r"([\d.]+),([\d.]+),([\d.]+)", body).groups()
                spots = [(float(px), float(py))]
            dpr = float(dpr)
            r = wintypes.RECT()            # the page reports from the window's outer corner, frame included
            user32.GetWindowRect(edge["hwnd"], ctypes.byref(r))
            edge["words"] = [(r.left + int(x * dpr), r.top + int(y * dpr)) for x, y in spots]
            edge["word"] = edge["words"][0]
    if edge["word"] is None:
        app.root.after(150, find_edge)


caption = tk.Toplevel(app.root)
caption.overrideredirect(True)
caption.attributes("-topmost", True)
caption.attributes("-alpha", 0.96)   # a layered window, like the cursor: a plain override-redirect one ignored moves here
cap_lbl = tk.Label(caption, text="", bg="#1f2430", fg="#ffffff", font=("Segoe UI Semibold", 17), padx=18, pady=8)
cap_lbl.pack()


marks = []     # (seconds into the film, caption)


def say(text):
    marks.append((time.time() - film_t0[0], text))
    return
    cap_lbl.configure(text=text)
    caption.update_idletasks()
    # size and place together: an override-redirect window that only gets "+x+y" snaps back when it resizes
    cap_geo[0] = f"{cap_lbl.winfo_reqwidth()}x{cap_lbl.winfo_reqheight()}+{CAP_X + 24}+{CAP_Y + CAP_H - 470}"
    caption.geometry(cap_geo[0])
    caption.lift()


cap_geo = [None]


KEY = "#ff00fe"
cursor = tk.Toplevel(app.root)
cursor.overrideredirect(True)
cursor.attributes("-topmost", True)
cursor.attributes("-transparentcolor", KEY)
cv = tk.Canvas(cursor, width=34, height=46, bg=KEY, highlightthickness=0)
cv.create_polygon(2, 2, 2, 36, 11, 28, 18, 43, 24, 40, 17, 26, 29, 26, fill="white", outline="black", width=2)
cv.pack()
pos = [CAP_X + CAP_W // 2, CAP_Y + CAP_H // 2]


def put_cursor(x, y):
    pos[:] = [x, y]
    cursor.geometry(f"+{int(x)}+{int(y)}")
    cursor.lift()


def glide(x, y, ms=700, then=None):
    x0, y0 = pos
    steps = max(1, ms // 30)
    for i in range(1, steps + 1):
        k = i / steps
        k = k * k * (3 - 2 * k)
        app.root.after(i * 30, lambda k=k: put_cursor(x0 + (x - x0) * k, y0 + (y - y0) * k))
    if then:
        app.root.after(steps * 30 + 30, then)


def click_flash():
    cv.itemconfigure(1, fill="#f4d27a")
    app.root.after(160, lambda: cv.itemconfigure(1, fill="white"))


E = lambda x, y: type("E", (), {"x_root": int(x), "y_root": int(y)})()   # noqa: E731

# ---------------------------------------------------------------- filming

ff = None
film_t0 = [time.time()]


stacking = [True]     # off while the stills are taken
EXTRA = []            # the app's own windows that appear in the study reel
WANT = {}             # window -> (x, y, w, h) it should keep


def keep_in_shot(top, x=None, y=None, size=None):
    """Put one of the app's windows inside the filmed area (centred over the browser unless x/y given),
    optionally at a size that fits it; again a moment later, after the window has laid itself out."""
    def place():
        if not top.winfo_exists():
            return
        top.update_idletasks()
        w = size[0] if size else top.winfo_reqwidth()
        xx = x if x is not None else EDGE_RECT[0] + (EDGE_RECT[2] - w) // 2
        yy = y if y is not None else CAP_Y + 40
        top.geometry((f"{size[0]}x{size[1]}" if size else "") + f"+{int(xx)}+{int(yy)}")
        if size:
            WANT[top] = (int(xx), int(yy), size[0], size[1])
    place()
    top.after(150, place)
    top.after(600, place)
    top.attributes("-topmost", True)
    if top not in EXTRA:
        EXTRA.append(top)


def all_toplevels(widget=None):
    out = []
    for w in (widget or app.root).winfo_children():
        if isinstance(w, tk.Toplevel):
            out.append(w)
        out += all_toplevels(w)
    return out


def adopt_new_windows(known):
    """Any window the app opened since `known` (a celebration, a level-up card): into the shot with it."""
    for w in all_toplevels():
        print("toplevel", w, w.winfo_ismapped(), w in known, flush=True) if os.environ.get("DEMO_TITLES") else None
        if w not in known and w.winfo_exists() and w.winfo_ismapped():
            known.add(w)
            if w not in (desk, caption, cursor) and w not in [c.top for c in pets.cats]:
                keep_in_shot(w)


def restack():
    """Desk, then the cats' things and the cats, then the card, then caption and cursor. Other programs' windows
    (even topmost ones) can come forward at any time; this keeps putting the demo's own windows back on top."""
    if not stacking[0]:
        return
    try:
        # Edge to the top of the always-on-top windows, then the desk directly under it: whatever Edge does
        # (a popup, a new tab), the desk stays between it and the owner's windows
        desk_hwnd = user32.GetParent(desk.winfo_id()) or desk.winfo_id()
        if edge["hwnd"]:
            user32.SetWindowPos(edge["hwnd"], HWND_TOPMOST, 0, 0, 0, 0, 0x13)   # no move/size/activate
            user32.SetWindowPos(desk_hwnd, edge["hwnd"], 0, 0, 0, 0, 0x13)
        else:
            desk.lift()
        for item in pets.items.values():
            for layer in item.layers:
                layer.top.lift()
        for toy in pets.toys:
            for w in vars(toy).values():
                if isinstance(w, tk.Toplevel):
                    w.lift()
        for c in pets.cats:
            c.top.lift()
        for item in pets.items.values():
            if item.front:
                item.front.top.lift()
        for w in [w for w in EXTRA if w.winfo_exists()]:
            want = WANT.get(w)
            if want and (w.winfo_width(), w.winfo_height()) != want[2:]:
                w.geometry(f"{want[2]}x{want[3]}+{want[0]}+{want[1]}")
            w.lift()
        app.root.lift()
        if cap_geo[0] and caption.winfo_geometry() != cap_geo[0]:
            caption.geometry(cap_geo[0])
        caption.lift()
        cursor.lift()
    finally:
        app.root.after(400, restack)


def only_demo_on_screen():
    """Privacy guard: points across the filmed area must be the wallpaper we drew, or inside the demo's own
    windows (the Edge window, the card, the cats and their things). Anything else means some window of the
    owner's is in the shot: then nothing gets filmed."""
    from PIL import ImageGrab
    shot = ImageGrab.grab((CAP_X, CAP_Y, CAP_X + CAP_W, CAP_Y + CAP_H))
    m = 24   # the window's drop shadow darkens the wallpaper around it
    ours = [(EDGE_RECT[0] - m, EDGE_RECT[1] - m, EDGE_RECT[0] + EDGE_RECT[2] + m, EDGE_RECT[1] + EDGE_RECT[3] + m)]
    for w in [app.root, caption, cursor] + [c.top for c in pets.cats] + \
             [layer.top for item in pets.items.values() for layer in item.layers + ([item.front] if item.front else [])] + \
             [w for toy in pets.toys for w in vars(toy).values() if isinstance(w, tk.Toplevel)] + \
             []:
        ours.append((w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()))
    for w in [w for w in EXTRA if w.winfo_exists() and w.winfo_ismapped()]:
        r = wintypes.RECT()
        user32.GetWindowRect(user32.GetParent(w.winfo_id()) or w.winfo_id(), ctypes.byref(r))
        ours.append((r.left - m, r.top - m, r.right + m, r.bottom + m))
    bad = []
    for fx in [i / 12 for i in range(13)]:
        for fy in [i / 8 for i in range(8)]:
            x, y = CAP_X + int((CAP_W - 1) * fx), CAP_Y + int((CAP_H - 1) * fy)
            if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in ours):
                continue
            got, want = shot.getpixel((x - CAP_X, y - CAP_Y))[:3], WALL.getpixel((x, y))[:3]
            if max(abs(u - v) for u, v in zip(got, want)) > 10:
                bad.append((x, y, got))
    return bad


def dry_snap(sec):
    def go():
        from PIL import ImageGrab
        ImageGrab.grab((CAP_X, CAP_Y, CAP_X + CAP_W, CAP_Y + CAP_H)).save(os.path.join(WORK, f"dry_{REEL}_{sec:g}.png"))
        print("snap", sec, "guard", only_demo_on_screen()[:3], flush=True)
    return go


def start_film():
    global ff
    if DRY:
        film_t0[0] = time.time()
        for sec in DRY:
            app.root.after(int(sec * 1000), dry_snap(sec))
        return
    bad = only_demo_on_screen()
    if bad:
        print("NOT FILMING: something other than the demo is on screen at", bad[:6], flush=True)
        edge_proc.terminate()
        os._exit(2)
    import imageio_ffmpeg
    film_t0[0] = time.time()
    ff = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "gdigrab",
                           "-framerate", "20", "-draw_mouse", "0", "-offset_x", str(CAP_X), "-offset_y", str(CAP_Y),
                           "-video_size", f"{CAP_W}x{CAP_H}", "-i", "desktop", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "16", "-pix_fmt", "yuv420p", RAW], stdin=subprocess.PIPE)
    app.root.after(2000, keep_checking)


def keep_checking():
    """While filming, look again every 2 s: if anything that isn't the demo shows up (a notification, an
    input-method box, someone's window), stop and throw the recording away."""
    if not ff or ff.poll() is not None:
        return
    bad = only_demo_on_screen()
    if bad:
        print("STOPPED: something other than the demo came on screen at", bad[:6], flush=True)
        ff.communicate(b"q", timeout=30)
        try:
            os.remove(RAW)
        except OSError:
            pass
        edge_proc.terminate()
        os._exit(3)
    app.root.after(2000, keep_checking)


def stop_film():
    if DRY:
        return
    if ff and ff.poll() is None:
        ff.communicate(b"q", timeout=30)


def watch_esc():
    if user32.GetAsyncKeyState(0x1B) & 0x8000:
        stop_film()
        edge_proc.terminate()
        os._exit(1)
    app.root.after(100, watch_esc)


steps = []


def at(sec, fn):
    steps.append((sec, fn))


def a_b():
    return pets.cats[0], pets.cats[1]


# scene 1: reading in the browser, a word gets selected, Ctrl+Shift
def s1_start():
    pets.director.next_time = time.time() + 9999
    pets.idle = lambda: 2
    say("Select a word in any app, tap Ctrl+Shift")
    x, y = edge["word"]
    glide(x - 30, y + 6, 900)


def s1_select():      # the page selects the word itself at this moment (see SELECT_AT); this is the hand doing it
    x, y = edge["word"]
    glide(x + 70, y + 6, 450)


def debug_report():
    """DEMO_DEBUG=1: one screenshot and where the demo's windows are, then quit (nothing is filmed)."""
    from ctypes import wintypes
    from PIL import ImageGrab
    ImageGrab.grab((CAP_X, CAP_Y, CAP_X + CAP_W, CAP_Y + CAP_H)).save(os.path.join(WORK, "debug.png"))
    r = wintypes.RECT()
    if edge["hwnd"]:
        user32.GetWindowRect(edge["hwnd"], ctypes.byref(r))
    ex = user32.GetWindowLongW(edge["hwnd"], -20) if edge["hwnd"] else 0
    print("edge", edge, "rect", (r.left, r.top, r.right, r.bottom), "visible", bool(edge["hwnd"] and user32.IsWindowVisible(edge["hwnd"])),
          "topmost", bool(ex & 8), "title", window_title(edge["hwnd"]) if edge["hwnd"] else None, flush=True)
    print("caption", caption.winfo_ismapped(), caption.winfo_rootx(), caption.winfo_rooty(), caption.winfo_width(),
          caption.winfo_height(), repr(cap_lbl.cget("text")), flush=True)
    edge_proc.terminate()
    os._exit(0)


def s1_lookup():
    app.lookup("ubiquitous")


# scene 2: the cats get on with their lives
def s2_start():
    say("Two cats live on your desktop")
    glide(CAP_X + CAP_W - 80, CAP_Y + 300, 900)
    a, b = a_b()
    pets.director.boop(a, b)


def s2_ball():
    a, b = a_b()
    pets.director.end(a, b)
    pets.drop_toy("ball", x=(a.centre() + b.centre()) / 2)
    app.root.after(900, lambda: pets.toy("ball") and pets.director.pingpong(a, b, pets.toy("ball")))


# scene 3: petting and clicking
def s3_start():
    a, b = a_b()
    pets.director.end(a, b)
    pets.put_toys_away()
    b.sit(30)
    say("Stroke one with the mouse")
    glide(b.centre() - 40, b.ground - b.h * 0.38, 800)


def s3_stroke():
    a, b = a_b()
    cx, y = b.centre(), b.ground - b.h * 0.38
    half = b.body_width() * 0.42
    xs = []
    for k in range(9):   # slow strokes back and forth along its back, about 6 s
        xs += [cx - half + i * 2 * half / 10 for i in range(11)] + [cx + half - i * 2 * half / 10 for i in range(1, 11)]
    for i, x in enumerate(xs):
        app.root.after(i * 34, lambda x=x: (put_cursor(x, y), b.on_hover(E(x, y))))


def s3_click():
    a, b = a_b()
    say("Click one and it answers")
    glide(a.centre(), a.ground - a.h * 0.45, 700,
          then=lambda: (click_flash(), a.answer_you()))


# scene 4: pomodoros earn the cats their dinner
def s4_start():
    a, b = a_b()
    pets.director.end(a, b)
    say("Pomodoros earn the cats their dinner")
    glide(CAP_X + CAP_W - 80, CAP_Y + 300, 700)
    app.clear_notice()
    now = time.time()
    app.settings["pomo"] = {"phase": "break", "start": now - 300, "end": now - 1}
    pomo.tick()                      # break over: a tummy rumbles, a cat sits by the empty bowl


def card_spot():
    r = app.root
    return r.winfo_rootx() + r.winfo_width() * 0.45, r.winfo_rooty() + r.winfo_height() * 0.55


def back_to_middle():
    """Before the pomodoro scene the card's cat trots back towards the middle, so its card stays in the shot."""
    a, b = a_b()
    pets.director.end(a, b)
    a.walk_to(CAP_X + 560, then=lambda: a.sit(20), run=True)


def s4_click_start():
    x, y = card_spot()
    glide(x, y, 700, then=lambda: (click_flash(), app.card_clicked()))


def s4_progress(part):
    def go():
        st = app.settings["pomo"]
        length = st["end"] - st["start"]
        st["start"] = time.time() - length * part
        st["end"] = st["start"] + length
        pomo.tick()
    return go


def s4_finish():
    st = app.settings["pomo"]
    st["end"] = time.time() - 1
    pomo.tick()                      # round done: someone smells dinner


def s4_feed():
    x, y = card_spot()
    glide(x, y, 600, then=lambda: (click_flash(), app.card_clicked()))


if os.environ.get("DEMO_DEBUG"):
    at(2.6, debug_report)
else:
    at(0.0, start_film)

# ---------------------------------------------------------------- the study-day reel

def find_text(widget, text):
    """The first label under `widget` whose text contains `text` (case-insensitive)."""
    for w in widget.winfo_children():
        if isinstance(w, tk.Label) and text.lower() in str(w.cget("text")).lower():
            return w
        found = find_text(w, text)
        if found:
            return found
    return None


def centre_of(w):
    return w.winfo_rootx() + w.winfo_width() // 2, w.winfo_rooty() + w.winfo_height() // 2


def l1_start():
    pets.director.next_time = time.time() + 9999
    pets.idle = lambda: 2
    say("12 languages, either direction")
    x, y = edge["words"][0]
    glide(x - 60, y + 6, 900)


def l1_select():
    x, y = edge["words"][0]
    glide(x + 60, y + 6, 450)


def l_lookup(word, learn):
    def go():
        app.settings["learn"] = learn
        app.lookup(word)
    return go


def l2_move():
    x, y = edge["words"][1]
    glide(x - 30, y + 6, 900)


def l2_select():
    x, y = edge["words"][1]
    glide(x + 30, y + 6, 400)


def f_open():
    say("Counts the time you actually study")
    app.clear_notice()
    app.root.withdraw()           # the card waits behind the scenes while windows are open
    feat = app.feature("focus")
    feat.open()
    win = feat.window("main")
    keep_in_shot(win.top, x=EDGE_RECT[0] + 150, y=CAP_Y + 18, size=(900, 770))
    STUDY["focus"] = win


def f_point():
    win = STUDY["focus"]
    label = find_text(win.top, "goodnotes")
    row = label.master if label else win.rows
    chip = next((w for w in row.winfo_children() if isinstance(w, tk.Label) and w is not label), label)
    STUDY["chip"] = chip
    glide(*centre_of(chip), 800)


def f_click():
    click_flash()
    win = STUDY["focus"]
    win.cycle("app:goodnotes.exe", "unsorted")     # what clicking its tag does: now it counts as study


def r_open():
    say("A study report in your inbox, every evening")
    STUDY["focus"].top.destroy()
    import report
    _, html, _, _ = report.daily(app, dt.date.today(), note=(
        "Three hours and a quarter, most of it before lunch. Your reading notes got the longest stretch today. "
        "Tomorrow, try one pomodoro on the midterm topics first thing, while the morning is still quiet."))
    REPORT_HTML[0] = html
    subprocess.Popen([EDGE, f"--user-data-dir={EDGE_PROFILE}", f"http://lab.example{REPORT_PATH}"])
    glide(CAP_X + CAP_W - 120, CAP_Y + 320, 900)


def m_open():
    say("Practice levels up your bond with the cats")
    feat = app.feature("todos")
    feat.open()
    win = feat.window("todos")
    keep_in_shot(win.top, x=EDGE_RECT[0] + 110, y=CAP_Y + 30, size=(980, 520))
    STUDY["todos"] = win


def m_point():
    win = STUDY["todos"]
    label = find_text(win.top, "Retrieval practice paper")
    box = None
    if label:
        box = next((w for w in label.master.winfo_children() if isinstance(w, tk.Label) and w is not label), None)
    x, y = centre_of(box or label)
    glide(x, y, 800)


def m_tick():
    click_flash()
    known = set(all_toplevels())
    STUDY["todos"].finish_task(STUDY["task"])      # what ticking its box does: a small celebration
    app.root.after(300, lambda: adopt_new_windows(known))


def m_levelup():
    known = set(all_toplevels())
    for w in list(EXTRA):
        if w.winfo_exists() and w is not STUDY["todos"].top:
            w.destroy()                                 # the celebration has had its moment
    bond_feat = app.feature("bond")
    del bond_feat.store.sync           # back to the real one
    before = bond_feat.store.total()
    bond_feat.sync()                                    # the task's points reach the next level
    print("bond", before, "->", bond_feat.store.total(), "level", bond_feat.level(),
          "seen", app.settings.get("bond_seen_level"), flush=True)
    app.root.after(200, lambda: adopt_new_windows(known))
    a, _ = a_b()
    glide(a.centre(), a.ground - a.h * 0.55, 900)


def m_show_cat():
    """The windows close: there's the cat, wearing what it just unlocked."""
    for w in list(EXTRA):
        if w.winfo_exists():
            w.destroy()
    app.root.deiconify()
    a, _ = a_b()
    glide(a.centre() + 40, a.ground - a.h * 0.5, 700, then=lambda: (click_flash(), a.answer_you()))


if REEL == "study":
    at(0.6, l1_start)
    at(1.6, l1_select)
    at(2.4, l_lookup("aprendizaje", "es"))
    at(6.4, l2_move)
    at(7.6, l2_select)
    at(8.4, l_lookup("少しずつ", "ja"))
    at(13.2, f_open)
    at(15.0, f_point)
    at(16.4, f_click)
    at(21.5, r_open)
    at(31.5, m_open)
    at(33.0, m_point)
    at(34.2, m_tick)
    at(37.4, m_levelup)
    at(42.0, m_show_cat)
    at(47.0, lambda: (stop_film(), edge_proc.terminate(), app.root.destroy()))
else:
    at(0.6, s1_start)
    at(1.6, s1_select)
    at(2.4, s1_lookup)
    at(7.5, s2_start)
    at(12.0, s2_ball)
    at(20.5, s3_start)
    at(21.6, s3_stroke)
    at(28.8, s3_click)
    at(31.8, back_to_middle)
    at(35.0, s4_start)
    at(38.5, s4_click_start)
    at(40.1, s4_progress(0.30))
    at(41.3, s4_progress(0.55))
    at(42.5, s4_progress(0.80))
    at(43.9, s4_finish)
    at(46.5, s4_feed)
    at(54.5, lambda: (stop_film(), stills()))




# ---------------------------------------------------------------- stills

def grab_window(top, name):
    from PIL import ImageGrab
    top.attributes("-topmost", True)    # above the demo desk, which is still covering the owner's screen
    top.lift()
    top.update()
    time.sleep(0.5)
    top.update()
    box = (top.winfo_rootx(), top.winfo_rooty(), top.winfo_rootx() + top.winfo_width(), top.winfo_rooty() + top.winfo_height())
    ImageGrab.grab(box).save(os.path.join(DOCS, name), optimize=True)


def stills():
    stacking[0] = False
    edge_proc.terminate()
    for w in [cursor, caption, app.root] + [c.top for c in pets.cats] + \
             [layer.top for item in pets.items.values() for layer in item.layers + ([item.front] if item.front else [])]:
        w.withdraw()
    app.clear_notice()
    pets.open_skins()
    win = next(iter(pets._windows.values()))
    grab_window(win.top, "cats-window.png")
    win.top.destroy()
    app.feature("bond").open()
    win = next(iter(app.feature("bond")._windows.values()))
    grab_window(win.top, "bond.png")
    win.top.destroy()
    app.feature("journal").open()
    win = app.feature("journal").window("journal")
    grab_window(win.top, "journal.png")
    win.top.destroy()
    import report
    subj, html, _, _ = report.daily(app, dt.date.today(), note=(
        "Look at you: over three hours, and most of it before lunch. Your algorithms work got the longest stretch. "
        "Tomorrow, try one pomodoro on the midterm topics first thing, while the morning is still quiet."))
    path = os.path.join(WORK, "report.html")
    open(path, "w", encoding="utf-8").write(html)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1.5",
                    f"--screenshot={os.path.join(WORK, 'report_full.png')}", "--window-size=680,1900", path],
                   capture_output=True, timeout=60)
    from PIL import Image
    im = Image.open(os.path.join(WORK, "report_full.png"))
    bg = Image.new("RGB", im.size, im.getpixel((2, 2)))
    from PIL import ImageChops
    box = ImageChops.difference(im.convert("RGB"), bg).getbbox()
    im.crop((0, 0, im.width, min(im.height, (box[3] if box else im.height) + 40))).save(os.path.join(DOCS, "report.png"), optimize=True)
    make_gif()
    edge_proc.terminate()
    app.root.destroy()


def caption_filter():
    """ffmpeg drawtext for each caption, shown until the next one, centred near the top."""
    font = "C\\:/Windows/Fonts/segoeuib.ttf"
    out = []
    for i, (t0, text) in enumerate(marks):
        t1 = marks[i + 1][0] if i + 1 < len(marks) else 999
        safe = text.replace("\\", "").replace("'", "\u2019").replace(":", "\\:").replace(",", "\\,")
        out.append(f",drawtext=fontfile='{font}':text='{safe}':fontsize=22:fontcolor=white:box=1:"
                   f"boxcolor=0x1f2430@0.88:boxborderw=12:x=(w-tw)/2:y=12:enable='between(t\\,{t0:.2f}\\,{t1:.2f})'")
    return "".join(out)


def make_gif():
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    pal = os.path.join(WORK, "palette.png")
    vf = f"fps=8,scale={OUT_W}:-1:flags=lanczos" + caption_filter()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", RAW, "-vf", vf + ",palettegen=max_colors=128:stats_mode=diff", pal], check=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", RAW, "-i", pal, "-lavfi",
                    vf + " [x]; [x][1:v] paletteuse=dither=sierra2_4a:diff_mode=rectangle",
                    os.path.join(DOCS, "demo.gif")], check=True)


def run_steps():
    for sec, fn in steps:
        app.root.after(int(sec * 1000), fn)
    print("filming", CAP_X, CAP_Y, CAP_W, CAP_H, "ground", GROUND, flush=True)


def begin_when_ready():
    if edge["word"] is None or edge["found"] is None:
        return app.root.after(200, begin_when_ready)
    wait = SELECT_AT / 1000 - (time.time() - edge["found"]) - 1.6
    print("edge ready; scenes start in", round(wait, 1), "s", flush=True)
    app.current = {"word": "consolidation", "trans": "巩固", "senses": [], "pron": {}, "speak": None, "speak_lang": "en"}
    app.show_current()        # a word from earlier on the card, without spending a request on it
    app.collapse()
    app.root.after(max(0, int(wait * 1000)), run_steps)


seed()
app.root.after(1500, restack)
app.root.after(800, find_edge)
app.root.after(1000, begin_when_ready)
app.root.after(400, watch_esc)
app.root.after(240_000, lambda: (stop_film(), app.root.destroy()))
app.root.mainloop()

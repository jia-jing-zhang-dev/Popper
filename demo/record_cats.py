"""Record the README demo (docs/demo.gif) and stills (docs/*.png) with the cats.

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
RAW = os.path.join(WORK, "cats_raw.mp4")

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
    "ui_lang": "en", "learn": "en", "native": "zh-CN", "text_size": "large", "listening": True,
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

features.bond.LevelUp = lambda *a, **k: None   # the seeded data levels the bond up: no level-up card mid-film

def fetch_translation(word, tries=12):
    """Look the demo word up once before anything is filmed (the free translation endpoint rate-limits after a
    lot of testing: wait and try again). The card then shows this real result, without a second request."""
    import lookup
    for k in range(tries):
        try:
            result = lookup.look_up(word, "en", "zh-CN")
            if result and result.get("trans"):
                return result
        except Exception as e:  # HTTP 429 and friends
            print(f"translation not available yet ({e}); trying again in 2 min", flush=True)
        time.sleep(120)
    print("translation still unavailable: not filming", flush=True)
    sys.exit(4)


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


def serve_demo_folder():
    import functools
    import http.server
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == PAPER_PATH:   # the paper, with the demo's settings baked in
                html = open(os.path.join(HERE, "paper.html"), encoding="utf-8").read()
                html = html.replace("<script>", f"<script>window.DEMO_QUERY = {json.dumps(PAPER_QUERY)};", 1)
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
                              f"--host-resolver-rules=MAP lab.example 127.0.0.1:{PORT}",
                              f"http://lab.example{PAPER_PATH}"])
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
        if user32.IsWindowVisible(hwnd) and (title.startswith("pos:") or "Retrieval Practice" in title):
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
            px, py, dpr = (float(v) for v in re.match(r"pos:([\d.]+),([\d.]+),([\d.]+)", title).groups())
            r = wintypes.RECT()            # the page reports from the window's outer corner, frame included
            user32.GetWindowRect(edge["hwnd"], ctypes.byref(r))
            edge["word"] = (r.left + int(px * dpr), r.top + int(py * dpr))
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


def restack():
    """Desk, then the cats' things and the cats, then the card, then caption and cursor. Other programs' windows
    (even topmost ones) can come forward at any time; this keeps putting the demo's own windows back on top."""
    if not stacking[0]:
        return
    try:
        desk.lift()
        if edge["hwnd"]:
            user32.SetWindowPos(edge["hwnd"], HWND_TOPMOST, 0, 0, 0, 0, 0x13)   # no move/size/activate
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
             [layer.top for item in pets.items.values() for layer in item.layers + ([item.front] if item.front else [])] +              [w for toy in pets.toys for w in vars(toy).values() if isinstance(w, tk.Toplevel)]:
        ours.append((w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()))
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


def start_film():
    global ff
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

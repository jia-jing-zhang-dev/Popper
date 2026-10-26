"""Record the Popper demo.

Opens demo/book.html full-screen in Edge, runs Popper with a throw-away data folder, and
drives both with real mouse/keyboard input while ffmpeg captures the screen. Captions and key
presses are logged to _work/marks.json; Popper logs when each word is spoken
(_work/events.tsv). edit.py turns all of it into the final video.

Don't touch the mouse or keyboard while it runs (about two minutes).
"""

import ctypes
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
import unicodedata
from ctypes import wintypes

import imageio_ffmpeg
from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work")
HOME = os.path.join(WORK, "home")
EVENTS = os.path.join(WORK, "events.tsv")
MARKS = os.path.join(WORK, "marks.json")
PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32

VK = {"ctrl": 0x11, "shift": 0x10, "win": 0x5B, "s": 0x53, "space": 0x20, "esc": 0x1B,
      "right": 0x27, "1": 0x31, "2": 0x32, "f11": 0x7A}
MOUSE = {"left": (0x2, 0x4), "right": (0x8, 0x10)}

marks = []
CARD = {"x": 2040, "bottom": 1180}
BASE_SETTINGS = {"ui_lang": "en", "voices": {"en": "US", "es": "Spain"}, "speed": "-10%",
                 "text_size": "large", "trigger": "ctrl_shift", "screenshots": True,
                 "listening": True, "x": CARD["x"], "bottom": CARD["bottom"]}


# ---------------------------------------------------------------- input

def mark(kind, text, dur=None):
    marks.append({"t": time.time(), "kind": kind, "text": text, "dur": dur})


def caption(text, dur):
    mark("caption", text, dur)


def cursor():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move(x, y, dur=0.55):
    sx, sy = cursor()
    steps = max(1, int(dur * 90))
    for i in range(1, steps + 1):
        k = i / steps
        k = k * k * (3 - 2 * k)  # ease in-out
        move_to(sx + (x - sx) * k, sy + (y - sy) * k)
        time.sleep(dur / steps)


def move_to(x, y):
    """Real mouse-move input (SetCursorPos is ignored by e.g. the Snipping overlay)."""
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.mouse_event(0x0001 | 0x8000, int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)), 0, 0)


def button(which, down):
    user32.mouse_event(MOUSE[which][0 if down else 1], 0, 0, 0, 0)


def click(x, y, which="left", double=False):
    move(x, y)
    time.sleep(0.12)
    for _ in range(2 if double else 1):
        button(which, True)
        time.sleep(0.04)
        button(which, False)
        time.sleep(0.06)


def drag(x1, y1, x2, y2):
    move(x1, y1)
    time.sleep(0.1)
    button("left", True)
    move(x2, y2, dur=0.7)
    time.sleep(0.08)
    button("left", False)


def tap(*keys, hold=0.14):
    for k in keys:
        user32.keybd_event(VK[k], 0, 0, 0)
        time.sleep(0.03)
    time.sleep(hold)
    for k in reversed(keys):
        user32.keybd_event(VK[k], 0, 2, 0)
        time.sleep(0.02)


def ctrl_shift():
    mark("keys", "Ctrl + Shift")
    time.sleep(0.25)
    tap("ctrl", "shift")


# ---------------------------------------------------------------- finding things on screen

def plain(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalnum()).lower()


def screen_words(region=None):
    import winocr
    img = ImageGrab.grab(region)
    ox, oy = (region[0], region[1]) if region else (0, 0)
    words = []
    for line in winocr.recognize_pil_sync(img, "en-US")["lines"]:
        for w in line["words"]:
            r = w["bounding_rect"]
            words.append((plain(w["text"]), r["x"] + ox, r["y"] + oy,
                          r["x"] + ox + r["width"], r["y"] + oy + r["height"]))
    return words


def find(phrase, region=None):
    """Bounding box (x1, y1, x2, y2) of a word or phrase on screen."""
    target = [plain(p) for p in phrase.split()]
    words = screen_words(region)

    def same(a, b):  # OCR often garbles accented letters ("rocín" -> "rocfn")
        return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8

    for i in range(len(words) - len(target) + 1):
        if all(same(words[i + j][0], target[j]) for j in range(len(target))):
            first, last = words[i], words[i + len(target) - 1]
            return first[1], min(first[2], last[2]), last[3], max(first[4], last[4])
    raise RuntimeError(f"couldn't find {phrase!r} on screen")


def window_rect(title):
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def close_window(title):
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


# ---------------------------------------------------------------- actions

def select_word(box):
    x1, y1, x2, y2 = box
    click((x1 + x2) // 2, (y1 + y2) // 2, double=True)


def select_phrase(box):
    x1, y1, x2, y2 = box
    drag(x1 + 2, (y1 + y2) // 2, x2 - 1, (y1 + y2) // 2)


def look_up(box, phrase=False, wait=5.0):
    (select_phrase if phrase else select_word)(box)
    time.sleep(0.35)
    ctrl_shift()
    time.sleep(wait)


def card_center():
    """A point inside the card. Near the bottom, which stays put when the card expands or collapses."""
    x1, y1, x2, y2 = window_rect("Popper")
    return (x1 + x2) // 2, y2 - 22


def open_card_menu(item):
    """Right-click the card and choose a menu item by its first word."""
    cx, cy = card_center()
    click(cx, cy, which="right")
    time.sleep(0.8)
    region = (cx - 50, cy - 700, min(cx + 1100, 2560), min(cy + 700, 1600))
    x1, y1, x2, y2 = find(item, region)
    click((x1 + x2) // 2, (y1 + y2) // 2)


def set_snip_mode(mode):
    """Pick Rectangle/Window/... in the Win+Shift+S toolbar (the choice is remembered)."""
    tap("win", "shift", "s", hold=0.2)
    time.sleep(1.8)
    w = user32.GetSystemMetrics(0)
    click(int(w * 0.461), 55)  # capture-mode dropdown, just right of the photo/video toggle
    time.sleep(0.9)
    region = (int(w * 0.3), 0, int(w * 0.7), 700)
    for name in mode:
        try:
            x1, y1, x2, y2 = find(name, region)
            break
        except RuntimeError:
            continue
    else:
        ImageGrab.grab((int(w * 0.3), 0, int(w * 0.7), 700)).save(os.path.join(WORK, "snip_menu.png"))
        tap("esc")
        time.sleep(0.5)
        tap("esc")
        raise RuntimeError(f"snip mode {mode} not found; see _work/snip_menu.png")
    click((x1 + x2) // 2, (y1 + y2) // 2)
    time.sleep(0.6)
    # The choice is only remembered after a finished snip (Esc discards it), so snip a bit of
    # blank margin. Popper isn't running yet, so nothing reacts to it.
    drag(120, 700, 320, 820)
    time.sleep(6)  # let the "snip copied" toast go away before recording starts


def ensure_fullscreen():
    """The book must cover the whole screen so nothing else on the desktop gets recorded."""
    rest()
    r = wintypes.RECT()
    user32.GetWindowRect(user32.GetForegroundWindow(), ctypes.byref(r))
    if r.left > 0 or r.top > 0 or r.right < user32.GetSystemMetrics(0) or r.bottom < user32.GetSystemMetrics(1):
        raise RuntimeError(f"the book window isn't full-screen ({r.left},{r.top},{r.right},{r.bottom})")


def rest():
    """Park the cursor in the right margin and clear the selection."""
    click(2380, 260)


# ---------------------------------------------------------------- processes

class WordPopper:
    proc = None

    def start(self, **settings):
        self.stop()
        with open(os.path.join(HOME, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(dict(BASE_SETTINGS, **settings), f)
        env = dict(os.environ, WORD_POPPER_HOME=HOME, WORD_POPPER_EVENTS=EVENTS)
        log = open(os.path.join(WORK, "word_popper.log"), "a")
        self.proc = subprocess.Popen([PYTHON, os.path.join(ROOT, "word_popper.py")], env=env,
                                     stdout=log, stderr=log, cwd=ROOT)
        time.sleep(2.5)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
            time.sleep(0.5)


class Recorder:
    def __init__(self, name):
        self.path = os.path.join(WORK, f"{name}.mkv")

    def __enter__(self):
        self.proc = subprocess.Popen(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "gdigrab", "-framerate", "30",
             "-draw_mouse", "1", "-i", "desktop", "-copyts", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "14", self.path], stdin=subprocess.PIPE)
        time.sleep(1.2)
        return self

    def __exit__(self, *exc):
        time.sleep(0.6)
        self.proc.communicate(b"q", timeout=60)


def stop_user_instance():
    """The real Popper (single instance) has to step aside while the demo copy runs."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
                          "'*word_popper.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId "
                          "-Force; 'stopped' }"], capture_output=True, text=True).stdout
    return "stopped" in out


def restart_user_instance():
    link = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup",
                        "Popper.lnk")
    if os.path.exists(link):
        os.startfile(link)
    else:
        subprocess.Popen([PYTHON.replace("python.exe", "pythonw.exe"),
                          os.path.join(ROOT, "word_popper.py")], cwd=ROOT)


# ---------------------------------------------------------------- the script

def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(HOME)
    had_user_instance = stop_user_instance()
    app = WordPopper()
    browser = subprocess.Popen([CHROME, f"--user-data-dir={os.path.join(WORK, 'chrome')}",
                             "--kiosk", "--incognito", "--no-first-run", "--no-default-browser-check",
                             "--disable-features=Translate", "--disable-sync",
                             "file:///" + os.path.join(HERE, "book.html").replace("\\", "/")])
    try:
        time.sleep(6)
        set_snip_mode(["Rectangle", "矩形"])
        ensure_fullscreen()
        app.start(learn="en", native="zh-CN")
        boxes = {p: find(p) for p in ["acknowledged", "rightful property", "impatiently", "synonymously"]}

        # 1. English reader, Chinese speaker
        with Recorder("1_english"):
            caption("Reading Pride and Prejudice in English", 3.2)
            time.sleep(3.4)
            caption("Select a word, then tap Ctrl+Shift", 3.6)
            look_up(boxes["acknowledged"], wait=1.6)
            caption("Translation, IPA and a natural voice, right where you're reading", 4.4)
            time.sleep(4.0)
            caption("Phrases work too", 4.5)
            look_up(boxes["rightful property"], phrase=True, wait=4.0)
            caption("Click the card to hear it again", 2.8)
            cx, cy = card_center()
            click(cx, cy)
            time.sleep(2.6)
            look_up(boxes["impatiently"], wait=4.2)
            caption("Can't select it? Snip it with Win+Shift+S", 6.5)
            mark("keys", "Win + Shift + S")
            time.sleep(0.25)
            tap("win", "shift", "s", hold=0.2)
            time.sleep(1.6)
            x1, y1, x2, y2 = boxes["synonymously"]
            drag(x1 - 14, y1 - 14, x2 + 14, y2 + 14)
            time.sleep(6.0)
            rest()

        # 2. Switch to an English speaker learning Spanish
        app.start(learn="es", native="en")
        click(2380, 260)
        tap("right")
        time.sleep(1.0)
        boxes = {p: find(p) for p in ["hidalgo", "rocín flaco", "lentejas"]}
        with Recorder("2_spanish"):
            caption("12 languages: choose what you're learning and what you speak", 5.0)
            open_card_menu("Settings")
            time.sleep(3.8)
            close_window("Popper Settings")
            time.sleep(0.4)
            rest()  # give the book the keyboard focus back
            time.sleep(0.6)
            caption("Reading Don Quijote in Spanish", 3.0)
            time.sleep(1.4)
            look_up(boxes["hidalgo"], wait=4.6)
            look_up(boxes["rocín flaco"], phrase=True, wait=4.6)
            look_up(boxes["lentejas"], wait=4.4)
            rest()

        # 3. Word list and review
        with Recorder("3_review"):
            caption("Every word you look up is saved", 4.0)
            open_card_menu("My words")
            time.sleep(3.6)
            close_window("My words")
            time.sleep(0.5)
            caption("Review later with spaced repetition", 9.5)
            open_card_menu("Review")
            time.sleep(2.2)
            for grade in ("2", "2", "1"):
                tap("space")
                time.sleep(2.2)
                tap(grade)
                time.sleep(2.0)
            tap("esc")
            time.sleep(0.8)
    finally:
        with open(MARKS, "w", encoding="utf-8") as f:
            json.dump(marks, f, ensure_ascii=False, indent=1)
        app.stop()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(browser.pid)], capture_output=True)
        if had_user_instance:
            restart_user_instance()
    print("recorded:", sorted(f for f in os.listdir(WORK) if f.endswith(".mkv")))


if __name__ == "__main__":
    sys.exit(main())

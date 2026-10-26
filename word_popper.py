"""Word Popper — look up any word you're reading, hear it, and review it later.

  - Select a word, phrase or sentence and tap Ctrl+Shift  -> translation + pronunciation
  - Win+Shift+S a word on screen (images, PDFs, videos)   -> OCR -> translation + pronunciation
  - Every word you look up goes into your word list; right-click the card -> Review
  - Click the card to hear the word again; drag it anywhere; right-click for everything else
"""

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from PIL import Image, ImageGrab

import i18n
from i18n import t
from languages import LANGUAGES, label, normalize, voice_for
from lookup import CJK_RE, look_up, ocr_image, ocr_tag_for
from settings_window import SettingsWindow
from speech import Speaker
from journal import Journal, JournalWindow
from library import LibraryLog, LibraryWindow, TodoList, TodoWindow, fmt_duration, fmt_long
from vocab import ReviewWindow, Vocab, VocabWindow

FROZEN = getattr(sys, "frozen", False)  # running as the packaged WordPopper.exe
SCRIPT_PATH = sys.executable if FROZEN else os.path.abspath(__file__)
# The packaged app keeps settings and words in %APPDATA%, so they survive moving or updating it
DATA_DIR = (os.environ.get("WORD_POPPER_HOME")
            or (os.path.join(os.environ["APPDATA"], "Word Popper") if FROZEN else os.path.dirname(SCRIPT_PATH)))
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
VOCAB_PATH = os.path.join(DATA_DIR, "vocab.db")
EVENT_LOG = os.environ.get("WORD_POPPER_EVENTS")  # optional playback log (used to sync the demo video)

MAX_TEXT_LEN = 300         # longer selections are ignored
COPY_MAX_LEN = 80          # in copy mode, only short copies count as lookups
VOCAB_MAX_WORDS = 4        # sentences are translated but not saved to the word list
# Only small snips are looked up: a word, a phrase or a line or two. Bigger screenshots are
# usually taken for something else (sharing a window, a bug report) and would be read as junk.
MAX_SNIP_HEIGHT = 220         # pixels
MAX_SNIP_PIXELS = 600_000
MIN_LETTER_RATIO = 0.8        # OCR results with more symbols than this are treated as junk
HOTKEY_MAX_SECONDS = 1.0   # holding Ctrl+Shift longer than this isn't a "tap"
EXPANDED_SECONDS = 8
TEXT_SIZES = {"small": 0.9, "normal": 1.0, "large": 1.25, "huge": 1.6}
CARD_FONT_SIZES = {"word": 12, "pron": 10, "trans": 11, "senses": 9}

BG = "#1f2430"
BG_HOVER = "#2a3040"
FG = "#f2f4f8"
FG_DIM = "#9aa3b5"
ACCENT = "#7cc4ff"

LETTER_RE = re.compile(r"\w", re.UNICODE)

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short

VK_SHIFT, VK_CONTROL, VK_C = 0x10, 0x11, 0x43
MODIFIER_VKS = {VK_SHIFT, VK_CONTROL, 0xA0, 0xA1, 0xA2, 0xA3}
OTHER_VKS = [vk for vk in range(1, 256) if vk not in MODIFIER_VKS]  # includes mouse buttons, Alt, Win
KEYEVENTF_KEYUP = 0x2

# Windows UI language (primary id) -> our language code, for first-run defaults
WINDOWS_LANGS = {0x09: "en", 0x11: "ja", 0x12: "ko", 0x0C: "fr", 0x07: "de", 0x0A: "es",
                 0x10: "it", 0x16: "pt", 0x19: "ru", 0x2A: "vi"}


def key_down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000


def send_ctrl_c():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------- settings

def system_language():
    lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    if lang_id & 0x3FF == 0x04:
        return "zh-TW" if lang_id in (0x0404, 0x0C04, 0x1404) else "zh-CN"
    return WINDOWS_LANGS.get(lang_id & 0x3FF, "en")


def load_settings():
    native = system_language()
    settings = {"ui_lang": "zh" if native.startswith("zh") else "en",
                "learn": "es" if native == "en" else "en",
                "native": native, "voices": {}, "speed": "-10%", "text_size": "normal",
                "trigger": "ctrl_shift",
                "screenshots": True, "listening": True, "library": False, "x": None, "bottom": None}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    if "accent" in saved:  # settings from the first version
        settings["voices"]["en"] = "UK" if saved.pop("accent") == "英音" else "US"
    settings.update(saved)
    for key in ("learn", "native"):
        if settings[key] not in LANGUAGES:
            settings[key] = "en"
    return settings


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- helpers

def clean_text(text):
    text = " ".join(text.split())
    return text.strip(" \t\"'“”‘’.,;:!?()[]{}<>«»「」『』。，、！？")


def looks_like_lookup(text, max_len=MAX_TEXT_LEN):
    if not text or len(text) > max_len or not LETTER_RE.search(text) or text.isdigit():
        return False
    return not re.search(r"https?://|www\.", text)


def looks_like_words(text):
    """True for OCR output that reads like real words, not junk such as 'üfra(EJi$'."""
    chars = [c for c in text if not c.isspace()]
    return bool(chars) and sum(c.isalpha() for c in chars) / len(chars) >= MIN_LETTER_RATIO


def log_event(path, text):
    if EVENT_LOG:
        with open(EVENT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f}\t{path}\t{text}\n")


# ---------------------------------------------------------------- UI

class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.script_path = SCRIPT_PATH
        self.settings = load_settings()
        i18n.set_language(self.settings["ui_lang"])
        self.speaker = Speaker(on_play=log_event)
        self.vocab = Vocab(VOCAB_PATH)
        self.library = LibraryLog(self.vocab.db)
        self.todos = TodoList(self.vocab.db)
        self.journal = Journal(self.vocab.db)
        self.ui_q = queue.Queue()
        self.current = None        # dict: word / trans / senses / pron / speak / speak_lang
        self.last_trigger = ("", 0.0)
        self.clip_seq = user32.GetClipboardSequenceNumber()
        self.ignore_clip_until = 0.0
        self.hotkey = {"armed_at": None, "dirty": False}
        self.collapse_job = None
        self.drag = None
        self.review_win = self.vocab_win = self.settings_win = self.library_win = self.todo_win = self.journal_win = None

        root = self.root = tk.Tk()
        root.title("Word Popper")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.96)
        root.configure(bg=BG)
        icon = os.path.join(getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(SCRIPT_PATH), "packaging")),
                            "icon.ico")
        if os.path.exists(icon):
            root.iconbitmap(default=icon)  # also used by the review, word-list and settings windows
        self.display_scale = root.winfo_fpixels("1i") / 96

        self.card_fonts = {"word": tkfont.Font(family="Segoe UI Semibold"),
                           "pron": tkfont.Font(family="Segoe UI"),
                           "trans": tkfont.Font(family="Microsoft YaHei UI"),
                           "senses": tkfont.Font(family="Microsoft YaHei UI")}
        self.frame = tk.Frame(root, bg=BG, padx=14, pady=8)
        self.frame.pack(fill="both", expand=True)
        self.word_lbl = tk.Label(self.frame, bg=BG, fg=FG, font=self.card_fonts["word"],
                                 anchor="w", justify="left")
        self.pron_lbl = tk.Label(self.frame, bg=BG, fg=ACCENT, font=self.card_fonts["pron"], anchor="w")
        self.trans_lbl = tk.Label(self.frame, bg=BG, fg=FG, font=self.card_fonts["trans"],
                                  anchor="w", justify="left")
        self.senses_lbl = tk.Label(self.frame, bg=BG, fg=FG_DIM, font=self.card_fonts["senses"],
                                   anchor="w", justify="left")
        self.word_lbl.pack(fill="x")
        self.detail_widgets = [self.pron_lbl, self.trans_lbl, self.senses_lbl]
        self.apply_text_size()

        for w in [root, self.frame, self.word_lbl, *self.detail_widgets]:
            w.bind("<ButtonPress-1>", self.on_press)
            w.bind("<B1-Motion>", self.on_drag)
            w.bind("<ButtonRelease-1>", self.on_release)
            w.bind("<Button-3>", self.show_menu)
            w.bind("<Enter>", lambda e: self.set_bg(BG_HOVER))
            w.bind("<Leave>", lambda e: self.set_bg(BG))

        self.update_status()
        self.place_window()
        root.after(300, self.poll_clipboard)
        root.after(30, self.poll_hotkey)
        root.after(100, self.poll_ui_queue)
        root.after(1000, self.library_tick)

    # ---------- layout

    @property
    def zoom(self):
        return TEXT_SIZES.get(self.settings["text_size"], 1.0)

    @property
    def scale(self):
        """Pixel scale for windows: display scaling times the user's text size."""
        return self.display_scale * self.zoom

    def font(self, family, size):
        return (family, round(size * self.zoom))

    def apply_text_size(self):
        for name, size in CARD_FONT_SIZES.items():
            self.card_fonts[name].configure(size=round(size * self.zoom))
        wrap = int(320 * self.scale)
        for w in [self.word_lbl, self.trans_lbl, self.senses_lbl]:
            w.configure(wraplength=wrap)

    def place_window(self):
        """Keep the card's bottom-left corner fixed so it grows upwards."""
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.settings["x"] if self.settings["x"] is not None else sw - w - 40
        bottom = self.settings["bottom"] if self.settings["bottom"] is not None else sh - 80
        x = max(0, min(x, sw - w))
        bottom = max(h, min(bottom, sh))
        self.root.geometry(f"+{x}+{bottom - h}")

    def set_bg(self, color):
        for w in [self.root, self.frame, self.word_lbl, *self.detail_widgets]:
            w.configure(bg=color)

    def expand(self, seconds=EXPANDED_SECONDS):
        for w in self.detail_widgets:
            w.pack_forget()
        for w in self.detail_widgets:
            if w.cget("text"):
                w.pack(fill="x")
        self.place_window()
        if self.collapse_job:
            self.root.after_cancel(self.collapse_job)
        self.collapse_job = self.root.after(seconds * 1000, self.collapse)

    def collapse(self):
        self.collapse_job = None
        for w in self.detail_widgets:
            w.pack_forget()
        self.place_window()

    def update_status(self):
        text = f"🔊 {self.current['word']}" if self.current else f"🔊 {t('idle')}"
        if not self.settings["listening"]:
            text += f"  {t('paused')}"
        self.word_lbl.configure(text=text)

    def flash(self, message, ms=1500):
        self.word_lbl.configure(text=message)
        self.place_window()
        self.root.after(ms, lambda: (self.update_status(), self.place_window()))

    # ---------- mouse

    def on_press(self, e):
        self.drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def on_drag(self, e):
        if not self.drag:
            return
        sx, sy, wx, wy, moved = self.drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if moved or abs(dx) + abs(dy) > 4:
            self.drag = (sx, sy, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_release(self, e):
        if not self.drag:
            return
        moved = self.drag[4]
        self.drag = None
        if moved:
            self.settings["x"] = self.root.winfo_x()
            self.settings["bottom"] = self.root.winfo_y() + self.root.winfo_height()
            save_settings(self.settings)
        elif self.current:
            self.speak_item(self.current)
            self.expand()

    def show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=t("menu_review", n=self.vocab.due_count()), command=self.open_review)
        menu.add_command(label=t("menu_vocab", n=self.vocab.count()), command=self.open_vocab)
        recent = tk.Menu(menu, tearoff=0)
        items = self.vocab.recent()
        for item in items:
            recent.add_command(label=f"{item['word']}   {item['trans'][:20]}",
                               command=lambda it=item: self.recall(it))
        if not items:
            recent.add_command(label=t("menu_none"), state="disabled")
        menu.add_cascade(label=t("menu_recent"), menu=recent)
        menu.add_command(label=t("menu_journal"), command=self.open_journal)
        if self.settings["library"]:
            menu.add_separator()
            session = self.library.current()
            label_ = (t("menu_lib_in_now", time=fmt_duration(time.time() - session["start"])) if session
                      else t("menu_lib"))
            menu.add_command(label=label_, command=self.toggle_library)
            done, total = self.todos.progress()
            menu.add_command(label=t("menu_todo", done=done, total=total) if total else t("todo_title"),
                             command=self.open_todo)
            menu.add_command(label=t("menu_lib_stats"), command=self.open_library)
        menu.add_separator()
        menu.add_command(label=f"{t('menu_settings')}   ({LANGUAGES[self.settings['learn']][1]} → "
                               f"{LANGUAGES[self.settings['native']][1]})", command=self.open_settings)
        menu.add_command(label=t("menu_resume") if not self.settings["listening"] else t("menu_pause"),
                         command=self.toggle_listening)
        menu.add_command(label=t("menu_quit"), command=self.root.destroy)
        menu.tk_popup(e.x_root, e.y_root)

    # ---------- windows

    @staticmethod
    def _reuse(win):
        if win and win.top.winfo_exists():
            win.top.lift()
            return True
        return False

    def open_review(self):
        if self._reuse(self.review_win):
            return
        items, note = self.vocab.due(), ""
        if not items:
            items, note = self.vocab.random_pick(), t("review_random")
        if not items:
            messagebox.showinfo(t("review_title"), t("review_empty"), parent=self.root)
            return
        self.review_win = ReviewWindow(self, items, note)

    def open_vocab(self):
        if self._reuse(self.vocab_win):
            self.vocab_win.refresh()
            return
        self.vocab_win = VocabWindow(self)

    # ---------- library check-in

    def toggle_library(self):
        """One button: checks in (and opens today's to-dos) or checks out, whichever applies."""
        if self.library.current():
            seconds = self.library.check_out()
            done, total = self.todos.progress()
            message = t("flash_lib_out", time=fmt_long(seconds))
            if total:
                message += t("flash_lib_tasks", done=done, total=total)
            self.flash(message, ms=4000)
        else:
            self.library.check_in()
            self.flash(t("flash_lib_in", time=time.strftime("%H:%M")), ms=3000)
            self.open_todo()
        if self.library_win and self.library_win.top.winfo_exists():
            self.library_win.refresh()

    def open_journal(self):
        if self._reuse(self.journal_win):
            self.journal_win.refresh()
            return
        self.journal_win = JournalWindow(self)

    def open_todo(self):
        if self._reuse(self.todo_win):
            self.todo_win.refresh()
            return
        self.todo_win = TodoWindow(self)

    def open_library(self):
        if self._reuse(self.library_win):
            self.library_win.refresh()
            return
        self.library_win = LibraryWindow(self)

    def library_tick(self):
        """End sessions nobody checked out of."""
        try:
            if self.library.close_stale():
                messagebox.showinfo(t("lib_title"), t("lib_auto_closed"), parent=self.root)
                if self.library_win and self.library_win.top.winfo_exists():
                    self.library_win.refresh()
        finally:
            self.root.after(30000, self.library_tick)

    def open_settings(self):
        if not self._reuse(self.settings_win):
            self.settings_win = SettingsWindow(self)

    def apply_settings(self, new):
        learn_changed = new["learn"] != self.settings["learn"]
        self.settings = new
        save_settings(new)
        i18n.set_language(new["ui_lang"])
        self.apply_text_size()
        self.update_status()
        self.place_window()
        if learn_changed and new["screenshots"]:
            self.check_ocr_language()

    def check_ocr_language(self):
        learn = self.settings["learn"]
        wanted = LANGUAGES[learn][3].split("-")[0].lower()
        if not ocr_tag_for(learn).lower().startswith(wanted):
            messagebox.showinfo("Word Popper", t("ocr_missing", lang=label(learn)), parent=self.root)

    def toggle_listening(self):
        self.settings["listening"] = not self.settings["listening"]
        save_settings(self.settings)
        self.clip_seq = user32.GetClipboardSequenceNumber()
        self.update_status()
        self.place_window()

    def recall(self, item):
        self.current = item
        self.show_current()
        self.speak_item(item)

    # ---------- Ctrl+Shift hotkey

    def poll_hotkey(self):
        """A lone tap of Ctrl+Shift (no other key or mouse button in between) looks up the selection."""
        try:
            ctrl, shift = key_down(VK_CONTROL), key_down(VK_SHIFT)
            hk = self.hotkey
            if ctrl or shift:
                if any(key_down(vk) for vk in OTHER_VKS):
                    hk["dirty"] = True
                if ctrl and shift and hk["armed_at"] is None:
                    hk["armed_at"] = time.time()
            else:
                if (hk["armed_at"] is not None and not hk["dirty"]
                        and time.time() - hk["armed_at"] < HOTKEY_MAX_SECONDS
                        and self.settings["listening"] and self.settings["trigger"] == "ctrl_shift"):
                    self.grab_selection()
                hk["armed_at"], hk["dirty"] = None, False
        finally:
            self.root.after(30, self.poll_hotkey)

    def grab_selection(self):
        """Press Ctrl+C on the user's behalf to read the selection, then restore the old clipboard text."""
        try:
            old = self.root.clipboard_get()
        except tk.TclError:
            old = None
        before = user32.GetClipboardSequenceNumber()
        self.ignore_clip_until = time.time() + 1.0
        send_ctrl_c()
        self.root.after(40, self.read_selection, before, old, 0)

    def read_selection(self, before, old, tries):
        if user32.GetClipboardSequenceNumber() == before:
            if tries < 12:
                self.root.after(40, self.read_selection, before, old, tries + 1)
            else:
                self.flash(t("no_selection"))
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if old is not None:
            self.root.clipboard_clear()
            self.root.clipboard_append(old)
        if text.strip():
            self.lookup(text)
        else:
            self.flash(t("no_selection"))

    # ---------- clipboard (copy mode + screenshots)

    def poll_clipboard(self):
        try:
            seq = user32.GetClipboardSequenceNumber()
            if seq != self.clip_seq:
                self.clip_seq = seq
                if self.settings["listening"] and time.time() > self.ignore_clip_until:
                    self.handle_clipboard()
        finally:
            self.root.after(300, self.poll_clipboard)

    def handle_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = None
        if text:
            if self.settings["trigger"] == "copy":
                self.lookup(text, max_len=COPY_MAX_LEN)
            return
        if not self.settings["screenshots"]:
            return
        try:
            img = ImageGrab.grabclipboard()
        except Exception:
            return
        if (isinstance(img, Image.Image) and img.height <= MAX_SNIP_HEIGHT
                and img.width * img.height <= MAX_SNIP_PIXELS):
            self.word_lbl.configure(text=f"🔍 {t('reading_screenshot')}")
            self.place_window()
            threading.Thread(target=self.ocr_worker, args=(img,), daemon=True).start()

    def ocr_worker(self, img):
        try:
            text = ocr_image(img, self.settings["learn"])
        except Exception:
            text = ""
        self.ui_q.put(("ocr", text))

    # ---------- lookup

    def lookup(self, raw, max_len=MAX_TEXT_LEN):
        text = clean_text(raw)
        if not looks_like_lookup(text, max_len):
            return
        last_text, last_time = self.last_trigger
        if self.current and text.lower() == last_text.lower() and time.time() - last_time < 2:
            self.speak_item(self.current)
            self.expand()
            return
        self.last_trigger = (text, time.time())

        self.current = {"word": text, "trans": t("translating"), "senses": [], "pron": {},
                        "speak": None, "speak_lang": self.settings["learn"]}
        # Non-CJK text is most likely in the language being learned: speak it right away
        # instead of waiting for the translation (unless the user's own language is Latin-script)
        native_cjk = self.settings["native"].startswith(("zh", "ja", "ko"))
        if native_cjk and not CJK_RE.search(text):
            self.current["speak"] = text
            self.speak_item(self.current)
        self.show_current()
        threading.Thread(target=self.lookup_worker, args=(self.current,), daemon=True).start()

    def lookup_worker(self, item):
        try:
            result = look_up(item["word"], self.settings["learn"], self.settings["native"])
        except Exception:
            result = None
        self.ui_q.put(("result", item, result))

    def poll_ui_queue(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                if msg[0] == "ocr":
                    if looks_like_words(msg[1]):
                        self.lookup(msg[1])
                    else:
                        self.update_status()
                        self.place_window()
                elif msg[0] == "result":
                    self.on_result(msg[1], msg[2])
        except queue.Empty:
            pass
        self.root.after(100, self.poll_ui_queue)

    def on_result(self, item, result):
        if result is None:
            item["trans"] = t("translate_failed")
        else:
            early = (item["speak"], normalize(item["speak_lang"]))
            item.update(result)
            # Speak now unless the early guess already said the same thing with the same voice
            if item is self.current and early != (item["speak"], normalize(item["speak_lang"])):
                self.speak_item(item)
            if len(item["word"].split()) <= VOCAB_MAX_WORDS:
                self.vocab.add(item)
        if item is self.current:
            self.show_current()

    def pron_text(self, item):
        pron = item.get("pron") or {}
        variant = self.settings["voices"].get(item.get("speak_lang"))
        return pron.get(variant) or pron.get("*") or next(iter(pron.values()), "")

    def show_current(self):
        item = self.current
        self.update_status()
        self.pron_lbl.configure(text=self.pron_text(item))
        self.trans_lbl.configure(text=item["trans"])
        self.senses_lbl.configure(text="\n".join(item["senses"]))
        self.expand()

    def speak_item(self, item):
        lang = normalize(item.get("speak_lang")) or self.settings["learn"]
        if item.get("speak"):
            voice = voice_for(lang, self.settings["voices"].get(lang))
            self.speaker.say(item["speak"], voice, self.settings["speed"])

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Single instance: launching again while it's running does nothing
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "WordPopperSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit()
    App().run()

"""Word Popper — 复制或截图一个英文单词，自动翻译并朗读；桌面上的小卡片点一下再读一遍。

用法：
  - 选中一个单词/短语/句子，按一下 Ctrl+Shift（同时按下再松开）→ 翻译 + 发音
  - Win+Shift+S 截图包含单词的区域 → OCR 识别 → 翻译 + 发音
  - 查过的单词自动存进词库（vocab.db），右键卡片 →“复习单词”按遗忘曲线复习
  - 左键点卡片：再读一遍；拖动：移动位置
  - 右键卡片：复习、词库、最近单词、美音/英音、暂停监听、退出
"""

import asyncio
import ctypes
import hashlib
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import urllib.parse
from tkinter import messagebox
import urllib.request

from PIL import Image, ImageGrab

from vocab import ReviewWindow, Vocab, VocabWindow

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
VOCAB_PATH = os.path.join(APP_DIR, "vocab.db")
AUDIO_DIR = os.path.join(tempfile.gettempdir(), "word_popper_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

VOICES = {"美音": "en-US-AriaNeural", "英音": "en-GB-SoniaNeural"}
MAX_TEXT_LEN = 300       # 选中的文字超过这个长度就不翻译
VOCAB_MAX_WORDS = 4      # 超过这么多词（句子）只翻译，不存进词库
HOTKEY_MAX_SECONDS = 1.0  # Ctrl+Shift 按住超过这个时间不算“按一下”
MAX_IMAGE_PIXELS = 1_500_000  # 太大的图片（整屏截图）不做 OCR
EXPANDED_SECONDS = 8

BG = "#1f2430"
BG_HOVER = "#2a3040"
FG = "#f2f4f8"
FG_DIM = "#9aa3b5"
ACCENT = "#7cc4ff"

CJK_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm
user32.GetAsyncKeyState.restype = ctypes.c_short

VK_SHIFT, VK_CONTROL, VK_C = 0x10, 0x11, 0x43
MODIFIER_VKS = {VK_SHIFT, VK_CONTROL, 0xA0, 0xA1, 0xA2, 0xA3}
OTHER_VKS = [vk for vk in range(1, 256) if vk not in MODIFIER_VKS]  # 含鼠标键、Alt、Win
KEYEVENTF_KEYUP = 0x2


def key_down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000


def send_ctrl_c():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------- settings

def load_settings():
    defaults = {"accent": "美音", "x": None, "bottom": None, "listening": True}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            defaults.update(json.load(f))
    except (OSError, ValueError):
        pass
    return defaults


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- network

def http_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def translate(text, target):
    """Google 翻译免费接口。返回 (主翻译, [词性释义行])。"""
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
           f"&sl=auto&tl={target}&hl=zh-CN&dt=t&dt=bd&q={urllib.parse.quote(text)}")
    data = http_json(url)
    main = "".join(seg[0] for seg in data[0] if seg and seg[0])
    senses = []
    if len(data) > 1 and data[1]:
        for entry in data[1][:4]:
            senses.append(f"{entry[0]}  {'；'.join(entry[1][:5])}")
    return main, senses


def youdao_lookup(word):
    """有道词典：返回 ({"美音": 音标, "英音": 音标}, [释义行])，查不到就返回空。"""
    try:
        data = http_json("https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(word), timeout=5)
        entry = data["ec"]["word"]
        entry = entry[0] if isinstance(entry, list) else entry
    except Exception:
        return {}, []
    ipa = {}
    if entry.get("usphone"):
        ipa["美音"] = f"/{entry['usphone']}/"
    if entry.get("ukphone"):
        ipa["英音"] = f"/{entry['ukphone']}/"
    senses = []
    for tr in entry.get("trs", [])[:4]:
        try:
            line = tr["tr"][0]["l"]["i"][0]
        except (KeyError, IndexError, TypeError):
            continue
        if line.startswith("【名】"):  # 人名之类的释义没用
            continue
        line = re.sub(r"^([a-z]+\.) ", "\\1\u00a0", line)  # 词性和释义不要被换行拆开
        senses.append(line if len(line) <= 70 else line[:70] + "…")
    return ipa, senses


# ---------------------------------------------------------------- speech

class Speaker:
    """后台线程：edge-tts 生成语音（带缓存），MCI 播放；没网时退回 Windows 自带 SAPI。"""

    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text, voice):
        self.q.put((text, voice))

    def _mci(self, cmd):
        winmm.mciSendStringW(cmd, None, 0, 0)

    def _run(self):
        while True:
            text, voice = self.q.get()
            while not self.q.empty():  # 只读最新的那个
                text, voice = self.q.get()
            try:
                path = self._synthesize(text, voice)
                self._mci("close wp")
                self._mci(f'open "{path}" type mpegvideo alias wp')
                self._mci("play wp")
            except Exception:
                self._sapi(text)

    def _synthesize(self, text, voice):
        key = hashlib.md5(f"{voice}|{text}".encode()).hexdigest()
        path = os.path.join(AUDIO_DIR, key + ".mp3")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            import edge_tts
            tmp = path + ".part"
            asyncio.run(edge_tts.Communicate(text, voice, rate="-10%").save(tmp))
            os.replace(tmp, path)
        return path

    def _sapi(self, text):
        safe = text.replace("'", "''")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"],
            creationflags=subprocess.CREATE_NO_WINDOW)


# ---------------------------------------------------------------- OCR

def ocr_image(img):
    import winocr
    img = img.convert("RGB")
    # 小截图放大一下，识别率高很多
    if img.height < 80:
        scale = max(2, 80 // max(img.height, 1))
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    result = winocr.recognize_pil_sync(img, "en")
    return " ".join(result.get("text", "").split())


# ---------------------------------------------------------------- helpers

def clean_text(text):
    text = " ".join(text.split())
    return text.strip(" \t\"'“”‘’.,;:!?()[]{}<>")


def looks_like_lookup(text):
    if not text or len(text) > MAX_TEXT_LEN:
        return False
    if not (LATIN_RE.search(text) or CJK_RE.search(text)):
        return False
    return not re.search(r"https?://|www\.", text)


# ---------------------------------------------------------------- UI

class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.settings = load_settings()
        self.speaker = Speaker()
        self.ui_q = queue.Queue()
        self.vocab = Vocab(VOCAB_PATH)
        self.hotkey = {"armed_at": None, "dirty": False}
        self.review_win = self.vocab_win = None
        self.current = None        # dict: word / speak / ipa / trans / senses
        self.last_trigger = ("", 0.0)
        self.clip_seq = user32.GetClipboardSequenceNumber()
        self.collapse_job = None
        self.drag = None

        root = self.root = tk.Tk()
        root.title("Word Popper")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.96)
        root.configure(bg=BG)

        wrap = int(320 * root.winfo_fpixels("1i") / 96)  # 按屏幕缩放调整换行宽度
        self.frame = tk.Frame(root, bg=BG, padx=14, pady=8)
        self.frame.pack(fill="both", expand=True)
        self.word_lbl = tk.Label(self.frame, text="🔊 Word Popper", bg=BG, fg=FG,
                                 font=("Segoe UI Semibold", 12), anchor="w",
                                 justify="left", wraplength=wrap)
        self.ipa_lbl = tk.Label(self.frame, bg=BG, fg=ACCENT,
                                font=("Segoe UI", 10), anchor="w")
        self.trans_lbl = tk.Label(self.frame, bg=BG, fg=FG,
                                  font=("Microsoft YaHei UI", 11), anchor="w",
                                  justify="left", wraplength=wrap)
        self.senses_lbl = tk.Label(self.frame, bg=BG, fg=FG_DIM,
                                   font=("Microsoft YaHei UI", 9), anchor="w",
                                   justify="left", wraplength=wrap)
        self.word_lbl.pack(fill="x")
        self.detail_widgets = [self.ipa_lbl, self.trans_lbl, self.senses_lbl]

        for w in [root, self.frame, self.word_lbl, *self.detail_widgets]:
            w.bind("<ButtonPress-1>", self.on_press)
            w.bind("<B1-Motion>", self.on_drag)
            w.bind("<ButtonRelease-1>", self.on_release)
            w.bind("<Button-3>", self.show_menu)
            w.bind("<Enter>", lambda e: self.set_bg(BG_HOVER))
            w.bind("<Leave>", lambda e: self.set_bg(BG))

        self.place_window()
        self.update_status()
        root.after(300, self.poll_clipboard)
        root.after(30, self.poll_hotkey)
        root.after(100, self.poll_ui_queue)

    # ---------- layout

    def place_window(self):
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
        if self.current:
            text = f"🔊 {self.current['word']}"
        else:
            text = "🔊 Word Popper"
        if not self.settings["listening"]:
            text += "  (已暂停)"
        self.word_lbl.configure(text=text)

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
            self.speak_current()
            self.expand()

    def show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"复习单词（{self.vocab.due_count()} 个待复习）",
                         command=self.open_review)
        menu.add_command(label=f"我的词库（{self.vocab.count()} 个）", command=self.open_vocab)
        recent = tk.Menu(menu, tearoff=0)
        items = self.vocab.recent()
        for item in items:
            recent.add_command(label=f"{item['word']}   {item['trans'][:20]}",
                               command=lambda it=item: self.recall(it))
        if not items:
            recent.add_command(label="(还没有)", state="disabled")
        menu.add_cascade(label="最近的单词", menu=recent)
        menu.add_separator()
        for name in VOICES:
            mark = "✓ " if self.settings["accent"] == name else "    "
            menu.add_command(label=mark + name, command=lambda n=name: self.set_accent(n))
        menu.add_separator()
        menu.add_command(label="继续监听" if not self.settings["listening"] else "暂停监听",
                         command=self.toggle_listening)
        menu.add_command(label="退出", command=self.root.destroy)
        menu.tk_popup(e.x_root, e.y_root)

    def set_accent(self, name):
        self.settings["accent"] = name
        save_settings(self.settings)
        if self.current:
            self.show_current()
        self.speak_current()

    def toggle_listening(self):
        self.settings["listening"] = not self.settings["listening"]
        save_settings(self.settings)
        self.clip_seq = user32.GetClipboardSequenceNumber()
        self.update_status()
        self.place_window()

    def open_review(self):
        if self.review_win and self.review_win.top.winfo_exists():
            self.review_win.top.lift()
            return
        items, note = self.vocab.due(), ""
        if not items:
            items = self.vocab.random_pick()
            note = "今天没有到期的词，随机抽几个复习一下"
        if not items:
            messagebox.showinfo("复习单词", "词库还是空的，先去查几个单词吧。", parent=self.root)
            return
        self.review_win = ReviewWindow(self, items, note)

    def open_vocab(self):
        if self.vocab_win and self.vocab_win.top.winfo_exists():
            self.vocab_win.refresh()
            self.vocab_win.top.lift()
            return
        self.vocab_win = VocabWindow(self)

    def voice(self):
        return VOICES[self.settings["accent"]]

    def recall(self, item):
        self.current = item
        self.show_current()
        self.speak_current()

    # ---------- Ctrl+Shift 热键

    def poll_hotkey(self):
        """单独按一下 Ctrl+Shift（中间没按别的键、没点鼠标）就查选中的文字。"""
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
                        and self.settings["listening"]):
                    self.grab_selection()
                hk["armed_at"], hk["dirty"] = None, False
        finally:
            self.root.after(30, self.poll_hotkey)

    def grab_selection(self):
        """模拟 Ctrl+C 拿到选中的文字，然后把剪贴板原来的文字放回去。"""
        try:
            old = self.root.clipboard_get()
        except tk.TclError:
            old = None
        before = user32.GetClipboardSequenceNumber()
        send_ctrl_c()
        self.root.after(40, self.read_selection, before, old, 0)

    def read_selection(self, before, old, tries):
        if user32.GetClipboardSequenceNumber() == before:
            if tries < 12:
                self.root.after(40, self.read_selection, before, old, tries + 1)
            else:
                self.flash("没有选中文字")
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
            self.flash("没有选中文字")

    def flash(self, message):
        self.word_lbl.configure(text=message)
        self.place_window()
        self.root.after(1500, lambda: (self.update_status(), self.place_window()))

    # ---------- clipboard（只处理截图）

    def poll_clipboard(self):
        try:
            seq = user32.GetClipboardSequenceNumber()
            if seq != self.clip_seq:
                self.clip_seq = seq
                if self.settings["listening"]:
                    self.handle_clipboard()
        finally:
            self.root.after(300, self.poll_clipboard)

    def handle_clipboard(self):
        text = None
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            pass
        if text:  # 复制文字不再触发，查词改用 Ctrl+Shift
            return
        try:
            img = ImageGrab.grabclipboard()
        except Exception:
            return
        if isinstance(img, Image.Image) and img.width * img.height <= MAX_IMAGE_PIXELS:
            self.word_lbl.configure(text="🔍 识别截图中…")
            self.place_window()
            threading.Thread(target=self.ocr_worker, args=(img,), daemon=True).start()

    def ocr_worker(self, img):
        try:
            text = ocr_image(img)
        except Exception:
            text = ""
        self.ui_q.put(("ocr", text))

    # ---------- lookup

    def lookup(self, raw):
        text = clean_text(raw)
        if not looks_like_lookup(text):
            return
        last_text, last_time = self.last_trigger
        if self.current and text.lower() == last_text.lower() and time.time() - last_time < 2:
            self.speak_current()
            self.expand()
            return
        self.last_trigger = (text, time.time())

        is_chinese = bool(CJK_RE.search(text))
        self.current = {"word": text, "speak": None if is_chinese else text,
                        "ipa": {}, "trans": "翻译中…", "senses": []}
        self.show_current()
        if not is_chinese:
            self.speak_current()
        threading.Thread(target=self.lookup_worker, args=(self.current,), daemon=True).start()

    def lookup_worker(self, item):
        is_chinese = item["speak"] is None
        try:
            main, senses = translate(item["word"], "en" if is_chinese else "zh-CN")
        except Exception:
            main, senses = "（翻译失败，检查网络）", []
        ipa = {}
        english = (main if is_chinese else item["word"]).strip()
        if english and len(english.split()) <= 3 and LATIN_RE.search(english):
            ipa, yd_senses = youdao_lookup(english)
            if yd_senses and not is_chinese:
                senses = yd_senses
        self.ui_q.put(("result", item, main, senses, ipa))

    def poll_ui_queue(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                if msg[0] == "ocr":
                    if msg[1]:
                        self.lookup(msg[1])
                    else:
                        self.update_status()
                        self.place_window()
                elif msg[0] == "result":
                    _, item, main, senses, ipa = msg
                    item["trans"], item["senses"], item["ipa"] = main, senses, ipa
                    if item["speak"] is None:  # 中文 → 读英文翻译
                        item["speak"] = main
                        if item is self.current:
                            self.speak_current()
                    if (not main.startswith("（翻译失败")
                            and len(item["word"].split()) <= VOCAB_MAX_WORDS):
                        self.vocab.add(item)
                    if item is self.current:
                        self.show_current()
        except queue.Empty:
            pass
        self.root.after(100, self.poll_ui_queue)

    def show_current(self):
        item = self.current
        self.update_status()
        ipa = item["ipa"]
        self.ipa_lbl.configure(text=ipa.get(self.settings["accent"]) or next(iter(ipa.values()), ""))
        self.trans_lbl.configure(text=item["trans"])
        self.senses_lbl.configure(text="\n".join(item["senses"]))
        self.expand()

    def speak_current(self):
        if self.current and self.current.get("speak"):
            self.speaker.say(self.current["speak"], VOICES[self.settings["accent"]])

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # 只允许一个实例（开机自启后再双击启动也不会出现两张卡片）
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "WordPopperSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        raise SystemExit
    App().run()

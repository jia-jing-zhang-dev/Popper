"""词库（SQLite）+ 复习窗口 + 词库列表窗口。"""

import csv
import json
import random
import sqlite3
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# 复习间隔（天）：答“认识”升一级，答“不认识”回到 0 级
INTERVALS = [0, 1, 2, 4, 7, 15, 30, 60]
FORGOT_DELAY = 10 * 60  # 不认识的词 10 分钟后再出现

BG = "#1f2430"
PANEL = "#2a3040"
FG = "#f2f4f8"
FG_DIM = "#9aa3b5"
ACCENT = "#7cc4ff"
GOOD = "#3f9f6a"
BAD = "#c4544f"


class Vocab:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS words (
                word      TEXT PRIMARY KEY COLLATE NOCASE,
                speak     TEXT,
                trans     TEXT,
                senses    TEXT,
                ipa       TEXT,
                lookups   INTEGER DEFAULT 1,
                added     REAL,
                last_seen REAL,
                level     INTEGER DEFAULT 0,
                due       REAL
            )""")
        self.db.commit()

    @staticmethod
    def to_item(row):
        return {"word": row["word"], "speak": row["speak"], "trans": row["trans"],
                "senses": json.loads(row["senses"] or "[]"),
                "ipa": json.loads(row["ipa"] or "{}"),
                "lookups": row["lookups"], "added": row["added"]}

    def add(self, item):
        """查一次就记一次；再次查同一个词说明还没记住，复习进度归零。"""
        now = time.time()
        args = (item["speak"], item["trans"], json.dumps(item["senses"], ensure_ascii=False),
                json.dumps(item["ipa"], ensure_ascii=False))
        cur = self.db.execute("""
            UPDATE words SET speak=?, trans=?, senses=?, ipa=?, lookups=lookups+1,
                             last_seen=?, level=0, due=? WHERE word=?""",
                              (*args, now, now, item["word"]))
        if cur.rowcount == 0:
            self.db.execute("""
                INSERT INTO words (word, speak, trans, senses, ipa, lookups, added, last_seen, level, due)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, 0, ?)""", (item["word"], *args, now, now, now))
        self.db.commit()

    def recent(self, n=12):
        rows = self.db.execute("SELECT * FROM words ORDER BY last_seen DESC LIMIT ?", (n,))
        return [self.to_item(r) for r in rows]

    def due(self, limit=50):
        rows = self.db.execute("SELECT * FROM words WHERE due <= ? ORDER BY due LIMIT ?",
                               (time.time(), limit))
        return [self.to_item(r) for r in rows]

    def random_pick(self, n=20):
        rows = self.db.execute("SELECT * FROM words ORDER BY due LIMIT ?", (n * 3,)).fetchall()
        random.shuffle(rows)
        return [self.to_item(r) for r in rows[:n]]

    def due_count(self):
        return self.db.execute("SELECT COUNT(*) FROM words WHERE due <= ?", (time.time(),)).fetchone()[0]

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM words").fetchone()[0]

    def grade(self, word, known):
        row = self.db.execute("SELECT level FROM words WHERE word=?", (word,)).fetchone()
        if not row:
            return
        now = time.time()
        if known:
            level = min(row["level"] + 1, len(INTERVALS) - 1)
            due = now + INTERVALS[level] * 86400
        else:
            level, due = 0, now + FORGOT_DELAY
        self.db.execute("UPDATE words SET level=?, due=? WHERE word=?", (level, due, word))
        self.db.commit()

    def search(self, text=""):
        like = f"%{text}%"
        rows = self.db.execute("""SELECT * FROM words WHERE word LIKE ? OR trans LIKE ?
                                  ORDER BY last_seen DESC""", (like, like))
        return [self.to_item(r) for r in rows]

    def delete(self, word):
        self.db.execute("DELETE FROM words WHERE word=?", (word,))
        self.db.commit()

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["单词", "音标", "翻译", "释义", "查询次数"])
            for item in self.search():
                ipa = item["ipa"].get("美音") or next(iter(item["ipa"].values()), "")
                w.writerow([item["word"], ipa, item["trans"], "\n".join(item["senses"]),
                            item["lookups"]])


def ipa_for(item, accent):
    return item["ipa"].get(accent) or next(iter(item["ipa"].values()), "")


def flat_button(parent, text, command, bg=PANEL, **kw):
    return tk.Button(parent, text=text, command=command, bg=bg, fg=FG, activebackground=bg,
                     activeforeground=FG, relief="flat", bd=0, padx=16, pady=8,
                     font=("Microsoft YaHei UI", 11), cursor="hand2", **kw)


class ReviewWindow:
    """闪卡复习：先看单词（自动读），想一想，再看释义，选认识/不认识。"""

    def __init__(self, app, items, note=""):
        self.app, self.queue, self.retried = app, list(items), set()
        self.done_count = 0
        top = self.top = tk.Toplevel(app.root)
        top.title("复习单词")
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        scale = app.root.winfo_fpixels("1i") / 96
        top.geometry(f"{int(480 * scale)}x{int(400 * scale)}")
        wrap = int(420 * scale)

        self.progress = tk.Label(top, bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 9))
        self.progress.pack(anchor="w", padx=20, pady=(14, 0))
        self.note = tk.Label(top, text=note, bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 9))
        if note:
            self.note.pack(anchor="w", padx=20)

        self.word = tk.Label(top, bg=BG, fg=FG, font=("Segoe UI Semibold", 26),
                             wraplength=wrap, cursor="hand2")
        self.word.pack(pady=(24, 0))
        self.word.bind("<Button-1>", lambda e: self.speak())
        self.ipa = tk.Label(top, bg=BG, fg=ACCENT, font=("Segoe UI", 12))
        self.ipa.pack()
        self.answer = tk.Frame(top, bg=BG)
        self.trans = tk.Label(self.answer, bg=BG, fg=FG, font=("Microsoft YaHei UI", 14),
                              wraplength=wrap)
        self.senses = tk.Label(self.answer, bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 10),
                               wraplength=wrap, justify="left")
        self.trans.pack(pady=(10, 4))
        self.senses.pack()

        self.buttons = tk.Frame(top, bg=BG)
        self.buttons.pack(side="bottom", pady=18)
        self.reveal_btn = flat_button(self.buttons, "显示释义（空格）", self.reveal)
        self.bad_btn = flat_button(self.buttons, "不认识（1）", lambda: self.grade(False), bg=BAD)
        self.good_btn = flat_button(self.buttons, "认识（2）", lambda: self.grade(True), bg=GOOD)
        self.speak_btn = flat_button(self.buttons, "🔊", self.speak)

        top.bind("<space>", lambda e: self.reveal())
        top.bind("1", lambda e: self.grade(False) if self.revealed else None)
        top.bind("2", lambda e: self.grade(True) if self.revealed else None)
        top.bind("r", lambda e: self.speak())
        top.bind("<Escape>", lambda e: top.destroy())
        top.lift()
        top.focus_force()
        self.next_card()

    def speak(self):
        if self.item and self.item.get("speak"):
            self.app.speaker.say(self.item["speak"], self.app.voice())

    def next_card(self):
        for w in self.buttons.winfo_children():
            w.pack_forget()
        self.answer.pack_forget()
        self.revealed = False
        if not self.queue:
            self.item = None
            self.word.configure(text="复习完成 ✓")
            self.ipa.configure(text=f"本次复习了 {self.done_count} 个词")
            self.progress.configure(text="")
            flat_button(self.buttons, "关闭", self.top.destroy).pack()
            return
        self.item = self.queue.pop(0)
        self.progress.configure(text=f"还剩 {len(self.queue) + 1} 个")
        self.word.configure(text=self.item["word"])
        self.ipa.configure(text="")
        self.reveal_btn.pack(side="left", padx=6)
        self.speak_btn.pack(side="left", padx=6)
        self.speak()

    def reveal(self):
        if not self.item or self.revealed:
            return
        self.revealed = True
        self.ipa.configure(text=ipa_for(self.item, self.app.settings["accent"]))
        self.trans.configure(text=self.item["trans"])
        self.senses.configure(text="\n".join(self.item["senses"]))
        self.answer.pack()
        for w in self.buttons.winfo_children():
            w.pack_forget()
        self.bad_btn.pack(side="left", padx=6)
        self.good_btn.pack(side="left", padx=6)
        self.speak_btn.pack(side="left", padx=6)

    def grade(self, known):
        if not self.item:
            return
        self.app.vocab.grade(self.item["word"], known)
        word = self.item["word"]
        if not known and word not in self.retried:  # 不认识的词本轮最后再来一次
            self.retried.add(word)
            self.queue.append(self.item)
        else:
            self.done_count += 1
        self.next_card()


class VocabWindow:
    """词库列表：搜索、朗读、删除、导出 CSV。"""

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title("我的词库")
        top.attributes("-topmost", True)
        scale = app.root.winfo_fpixels("1i") / 96
        top.geometry(f"{int(640 * scale)}x{int(480 * scale)}")

        bar = ttk.Frame(top, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="搜索：").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh())
        entry = ttk.Entry(bar, textvariable=self.search_var, width=24)
        entry.pack(side="left")
        ttk.Button(bar, text="导出 CSV", command=self.export).pack(side="right")
        ttk.Button(bar, text="删除", command=self.delete).pack(side="right", padx=4)
        ttk.Button(bar, text="朗读", command=self.speak).pack(side="right")

        style = ttk.Style(top)
        style.configure("Vocab.Treeview", rowheight=int(26 * scale), font=("Microsoft YaHei UI", 10))
        cols = ("word", "trans", "lookups", "added")
        self.tree = ttk.Treeview(top, columns=cols, show="headings", style="Vocab.Treeview")
        for col, title, width in [("word", "单词", 160), ("trans", "翻译", 280),
                                  ("lookups", "查询次数", 70), ("added", "添加日期", 100)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=int(width * scale), anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.speak())
        self.tree.bind("<Delete>", lambda e: self.delete())

        self.status = ttk.Label(top, padding=(8, 4))
        self.status.pack(fill="x")
        self.items = {}
        self.refresh()
        top.lift()
        entry.focus_force()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        for item in self.app.vocab.search(self.search_var.get().strip()):
            iid = self.tree.insert("", "end", values=(
                item["word"], item["trans"], item["lookups"],
                time.strftime("%Y-%m-%d", time.localtime(item["added"]))))
            self.items[iid] = item
        self.status.configure(text=f"共 {self.app.vocab.count()} 个词，"
                                   f"{self.app.vocab.due_count()} 个待复习　·　双击朗读")

    def selected(self):
        return [self.items[i] for i in self.tree.selection() if i in self.items]

    def speak(self):
        for item in self.selected()[:1]:
            if item.get("speak"):
                self.app.speaker.say(item["speak"], self.app.voice())

    def delete(self):
        items = self.selected()
        if not items:
            return
        names = "、".join(i["word"] for i in items[:5]) + ("…" if len(items) > 5 else "")
        if messagebox.askyesno("删除", f"从词库删除 {names}？", parent=self.top):
            for item in items:
                self.app.vocab.delete(item["word"])
            self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self.top, defaultextension=".csv",
                                            initialfile="我的词库.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.app.vocab.export_csv(path)
            self.status.configure(text=f"已导出到 {path}")

"""Study buddy: Claude, through the owner's own Claude Code login, as a friend who keeps them learning.

Popper runs `claude -p` (Claude Code's one-shot mode) in the background, so it uses the Claude
subscription the owner is already signed in to; no API key. Claude Code gets read-only tools
(Read/Glob/Grep) and only the course folders the owner picked, so it can open the lecture they're on
by itself. Each day is one Claude Code session, resumed for every message, so the chat remembers
the day's questions.

Replies end with machine-readable tags that Popper strips before showing them:
  [[topic: ...]] [[source: ...]]   on a new question
  [[verdict: correct|partial|wrong]] when grading an answer
  [[interest: ...]]                when the student shows curiosity about something
"""

import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, GOOD, PANEL

CLAUDE_TIMEOUT = 240  # seconds; reading a long PDF can take a while
TAG_RE = re.compile(r"\[\[\s*(\w+)\s*:\s*(.*?)\s*\]\]")
# Markdown markers and emoji, which the plain Tk chat would show as-is or as broken glyphs
CLEAN_RE = re.compile("\\*\\*|__|`|[\U0001F000-\U0001FAFF☀-➿️]")
# how the chat lays out a reply: answer options, code, the "(Slides: deck, slides N)" line, other notes
OPTION_RE = re.compile(r"^\s*\(?([A-Ha-h])[).:]\s+\S")
SLIDES_RE = re.compile(r"^[（(](?:Slides|课件)[:：]\s*(.+?\.(?:pdf|pptx))[，,]\s*(?:slides|第)\s*([\d\s,–-]+)", re.I)
NOTE_RE = re.compile(r"^[（(].*[）)]$")
BADGE_RE = re.compile(r"^([✓~✗]) ")  # the verdict line Popper puts on top of graded feedback

PERSONA = """You are Popper (泡泡), a warm, slightly fussy study buddy who lives in the corner of a university student's screen. Think of a caring friend who keeps nudging them to learn, notices what they're working on, and is genuinely curious with them. Your goal: before each exam the student truly understands everything on that course's lecture slides.

The student studies computer science. Their course materials are in the folders you can read (Read, Glob, Grep); plain-text copies of the lecture slides are under slides/ in your working folder. Base every question and explanation on what the slides actually say (name the deck and slides in the tags, not in the text: Popper shows them). You cannot change files or run anything, and you don't need to.

Questions test understanding, not recall (Bloom's understand and apply levels): ask the student to explain why, apply an idea to a small new example, compare two ideas, predict what happens, or trace a short piece of code. Never ask for a definition word for word. When you judge an answer, ask for or give the reasoning, not just the result.

Style: short and friendly, plain text only: no Markdown (no **, #, bullets or backticks) and no emoji. The chat keeps your line breaks, so lay things out in short lines, never one long paragraph:
- A question: the student already has the slides open beside the chat (Popper opens them), so don't restate or summarise them and don't name the file; refer to a slide number if needed. Ask exactly one thing: no second question, no "also", no "for contrast". At most one short line of setup, a blank line, then the question on one line ending with "?" (the last line before any options). About half the time make it multiple choice: three or four options, each on its own line as "A) ...", "B) ...", and ask the student to pick one and say why in a sentence (the student clicks an option to answer). Code goes on its own lines, each indented by four spaces. Under 80 words in all.
- Feedback on an answer: a first line of a few words (e.g. "Not quite." or "Yes, exactly."), then the key idea in two to four short lines. If they picked an option without saying why, ask why in one line.
One question at a time. No headings. Encourage without flattering.

Language: questions, answers to questions, explanations and anything else about course content are always in English, the language of the courses and exams, even when the student writes in another language. Casual chat (greetings, mood, plans) is in {language}.

End your reply with tags on their own line (Popper reads and hides them):
- When you ask a new question: [[topic: <concept, in English>]] [[source: <file name, or none>]]
- When you judge an answer to your question: [[verdict: correct|partial|wrong]] [[topic: <concept>]]
- When the student shows curiosity about something new: [[interest: <topic, in English>]]
- Whenever a question or explanation is about particular slides: [[source: <deck file name>]] \
[[slides: <first>-<last>]] (slide numbers in that deck); Popper opens the deck there so the student can follow

Coding exercises: when an idea is best practised by writing or running code (the student asks for one, or \
the topic is about code), make the question a small coding exercise: say what to do, then give a short \
starter file in one fenced code block (the only Markdown allowed) that compiles or runs as is, with TODOs \
and a main or tests that print what to check. Use the language the course's slides use and one that this PC \
has (see the context). Add [[exercise: c|python|ocaml]] to the tags. Popper saves the file and opens it in \
VS Code, so don't explain how to set anything up."""


def find_claude():
    path = shutil.which("claude")
    if path:
        return path
    guess = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return guess if os.path.exists(guess) else None


def split_tags(text):
    """(visible text, {tag: value}) — tags are removed from what the student sees."""
    tags = {}
    for name, value in TAG_RE.findall(text or ""):
        tags[name.lower()] = value
    return CLEAN_RE.sub("", TAG_RE.sub("", text or "")).strip(), tags


class ClaudeBridge:
    """Runs one `claude -p` at a time in the background and hands results back on the Tk thread."""

    def __init__(self, app, workdir):
        self.app = app
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)
        self.jobs = queue.Queue()
        self.busy = False
        threading.Thread(target=self._worker, daemon=True).start()

    def ask(self, prompt, folders, session_id, on_done, system=None, timeout=CLAUDE_TIMEOUT):
        """on_done({"ok", "text", "session_id", "error"}) is called on the Tk thread. `system` replaces the persona."""
        self.jobs.put((prompt, list(folders), session_id, on_done, system, timeout))

    def _worker(self):
        while True:
            prompt, folders, session_id, on_done, system, timeout = self.jobs.get()
            self.busy = True
            result = self._run(prompt, folders, session_id, system, timeout)
            self.busy = False
            self.app.ui_q.put(("call", lambda r=result, f=on_done: f(r)))

    def _run(self, prompt, folders, session_id, system=None, timeout=CLAUDE_TIMEOUT):
        exe = find_claude()
        if not exe:
            return {"ok": False, "error": t("buddy_no_claude")}
        language = "Simplified Chinese" if self.app.settings["ui_lang"] == "zh" else "English"
        cmd = [exe, "-p", prompt, "--output-format", "json",
               "--tools", "Read,Glob,Grep", "--allowedTools", "Read", "Glob", "Grep",
               "--strict-mcp-config", "--permission-prompts", "none",
               "--system-prompt", system or PERSONA.format(language=language)]
        for folder in folders:
            if os.path.isdir(folder):
                cmd += ["--add-dir", folder]
        if session_id:
            cmd += ["--resume", session_id]
        try:
            proc = subprocess.run(cmd, cwd=self.workdir, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout, stdin=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            data = json.loads(proc.stdout or "{}")
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": t("buddy_timeout")}
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"{t('buddy_failed')} ({e.__class__.__name__})"}
        if data.get("is_error") or not data.get("result"):
            message = data.get("result") or proc.stderr.strip()[:200] or t("buddy_failed")
            if "authenticate" in message.lower() or "log in" in message.lower():
                message = t("buddy_login")
            return {"ok": False, "error": message, "session_id": data.get("session_id")}
        return {"ok": True, "text": data["result"], "session_id": data.get("session_id")}


class BuddyStore:
    """Everything said, the questions asked (with how they went) and the topics the student likes."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_messages (
                id      INTEGER PRIMARY KEY,
                ts      REAL NOT NULL,
                day     TEXT NOT NULL,
                role    TEXT NOT NULL,      -- 'buddy' or 'me'
                kind    TEXT,               -- 'question', 'chat', 'nudge', 'discovery'
                text    TEXT NOT NULL
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_questions (
                id       INTEGER PRIMARY KEY,
                ts       REAL NOT NULL,
                topic    TEXT,
                source   TEXT,
                question TEXT NOT NULL,
                verdict  TEXT,              -- correct / partial / wrong, once answered
                level    INTEGER DEFAULT 0, -- spaced-repetition step for missed topics
                due      REAL,              -- when to come back to it (missed ones only)
                topic_id INTEGER            -- the slide topic (mastery_topics) it was about
            )""")
        if "topic_id" not in [c[1] for c in self.db.execute("PRAGMA table_info(buddy_questions)")]:
            self.db.execute("ALTER TABLE buddy_questions ADD COLUMN topic_id INTEGER")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_interests (
                topic TEXT PRIMARY KEY,
                score REAL NOT NULL,
                last  REAL NOT NULL
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_sessions (
                day        TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )""")
        self.db.commit()

    def session(self, day):
        row = self.db.execute("SELECT session_id FROM buddy_sessions WHERE day=?", (day.isoformat(),)).fetchone()
        return row[0] if row else None

    def set_session(self, day, session_id):
        self.db.execute("INSERT INTO buddy_sessions (day, session_id) VALUES (?, ?) "
                        "ON CONFLICT(day) DO UPDATE SET session_id=excluded.session_id", (day.isoformat(), session_id))
        self.db.commit()

    def say(self, role, text, kind="chat"):
        self.db.execute("INSERT INTO buddy_messages (ts, day, role, kind, text) VALUES (?, ?, ?, ?, ?)",
                        (time.time(), dt.date.today().isoformat(), role, kind, text))
        self.db.commit()

    def messages(self, day):
        return self.db.execute("SELECT * FROM buddy_messages WHERE day=? ORDER BY ts", (day.isoformat(),)).fetchall()

    def add_question(self, text, topic, source, topic_id=None):
        cur = self.db.execute("INSERT INTO buddy_questions (ts, topic, source, question, topic_id) "
                              "VALUES (?, ?, ?, ?, ?)", (time.time(), topic, source, text, topic_id))
        self.db.commit()
        return cur.lastrowid

    def open_question(self):
        """The latest question still waiting for an answer (from the last 12 hours)."""
        return self.db.execute("SELECT * FROM buddy_questions WHERE verdict IS NULL AND ts > ? "
                               "ORDER BY ts DESC LIMIT 1", (time.time() - 12 * 3600,)).fetchone()

    def grade(self, question_id, verdict):
        """Record how an answer went; missed topics come back after 1, 3, 7 then 14 days."""
        steps = [1, 3, 7, 14]
        row = self.db.execute("SELECT level FROM buddy_questions WHERE id=?", (question_id,)).fetchone()
        level = row[0] if row else 0
        due = None if verdict == "correct" else time.time() + steps[min(level, len(steps) - 1)] * 86400
        self.db.execute("UPDATE buddy_questions SET verdict=?, due=?, level=? WHERE id=?",
                        (verdict, due, level + (verdict != "correct"), question_id))
        self.db.commit()

    def due_reviews(self):
        """Missed questions whose time to try again has come, oldest first."""
        return self.db.execute("SELECT * FROM buddy_questions WHERE due IS NOT NULL AND due <= ? ORDER BY due",
                               (time.time(),)).fetchall()

    def take_review(self, question_id):
        """The missed question is being asked again (as a new question), so it's no longer due."""
        self.db.execute("UPDATE buddy_questions SET due=NULL WHERE id=?", (question_id,))
        self.db.commit()

    def interests(self, limit=6):
        return [r[0] for r in self.db.execute("SELECT topic FROM buddy_interests ORDER BY score DESC, last DESC "
                                              "LIMIT ?", (limit,))]

    def day_summary(self, start, end):
        """(questions asked, {verdict: count}, topics) for one day."""
        rows = self.db.execute("SELECT topic, verdict FROM buddy_questions WHERE ts >= ? AND ts < ?",
                               (start, end)).fetchall()
        verdicts = {}
        for r in rows:
            if r["verdict"]:
                verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        topics = list(dict.fromkeys(r["topic"] for r in rows if r["topic"]))
        return len(rows), verdicts, topics

    def like(self, topic, amount=1.0):
        self.db.execute("INSERT INTO buddy_interests (topic, score, last) VALUES (?, ?, ?) "
                        "ON CONFLICT(topic) DO UPDATE SET score = score + excluded.score, last = excluded.last",
                        (topic.strip()[:80], amount, time.time()))
        self.db.commit()


# ---------------------------------------------------------------- windows

class FolderDialog:
    """Pick which folders the buddy may read."""

    def __init__(self, app, feature):
        self.app, self.feature = app, feature
        top = self.top = tk.Toplevel(app.root)
        top.title(t("buddy_folders_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        f = app.font
        tk.Label(top, text=t("buddy_folders_hint"), bg=BG, fg=FG_DIM, font=f("Microsoft YaHei UI", 9),
                 justify="left", wraplength=int(460 * app.scale)).pack(anchor="w", padx=16, pady=(14, 6))
        self.list = tk.Listbox(top, bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground=BG, relief="flat",
                               highlightthickness=0, width=60, height=8, font=f("Microsoft YaHei UI", 10))
        self.list.pack(fill="both", expand=True, padx=16)
        bar = tk.Frame(top, bg=BG)
        bar.pack(fill="x", padx=16, pady=12)
        for key, cmd in (("buddy_folders_add", self.add), ("buddy_folders_remove", self.remove)):
            b = tk.Label(bar, text=t(key), bg=PANEL, fg=ACCENT, padx=12, pady=4, cursor="hand2",
                         font=f("Microsoft YaHei UI", 10))
            b.pack(side="left", padx=(0, 8))
            b.bind("<Button-1>", lambda e, c=cmd: c())
        top.bind("<Escape>", lambda e: top.destroy())
        self.refresh()

    def refresh(self):
        self.list.delete(0, "end")
        for folder in self.feature.folders():
            self.list.insert("end", folder)

    def add(self):
        folder = filedialog.askdirectory(parent=self.top, initialdir=os.path.expanduser("~\\Desktop"))
        if folder:
            self.feature.set_folders(self.feature.folders() + [os.path.normpath(folder)])
            self.refresh()

    def remove(self):
        for i in reversed(self.list.curselection()):
            folders = self.feature.folders()
            del folders[i]
            self.feature.set_folders(folders)
        self.refresh()


class ChatWindow:
    """A small chat with the buddy. The input sits below the transcript and never moves."""

    def __init__(self, app, feature):
        self.app, self.feature = app, feature
        top = self.top = tk.Toplevel(app.root)
        top.title(t("buddy_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s, f = app.scale, app.font

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(head, text=t("buddy_title"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 14)).pack(side="left")
        self.status = tk.Label(head, bg=BG, fg=ACCENT, font=f("Microsoft YaHei UI", 9))
        self.status.pack(side="left", padx=10)
        for key, cmd in (("buddy_folders", lambda: feature.open_folders()), ("buddy_checklist", feature.open_mastery),
                         ("buddy_exercise", feature.ask_exercise), ("buddy_past", feature.ask_past_exam),
                         ("buddy_snooze", feature.snooze_today), ("buddy_review", feature.review_now),
                         ("buddy_new_question", feature.ask_question)):
            b = tk.Label(head, text=t(key), bg=PANEL, fg=ACCENT, padx=10, pady=2, cursor="hand2",
                         font=f("Microsoft YaHei UI", 9))
            b.pack(side="right", padx=(6, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())

        # input first, packed at the bottom, so the growing transcript never pushes it
        bottom = tk.Frame(top, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(4, 12))
        # one-click replies to the current question, fixed above the input
        quick = tk.Frame(top, bg=BG)
        quick.pack(side="bottom", fill="x", padx=14, pady=(6, 0))
        self.quick_buttons = []
        for key in ("hint", "explain", "skip"):
            b = tk.Label(quick, text=t("buddy_" + key), bg=PANEL, fg=ACCENT, padx=10, pady=2, cursor="hand2",
                         font=f("Microsoft YaHei UI", 9))
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, k=key: feature.quick(k))
            self.quick_buttons.append(b)
        self.context = tk.Label(quick, text=t("buddy_pick_hint"), bg=BG, fg=FG_DIM, anchor="w",
                                font=f("Microsoft YaHei UI", 9))
        self.context.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.input = tk.Text(bottom, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", height=3, width=1, wrap="word",
                             padx=int(8 * s), pady=int(6 * s), font=f("Microsoft YaHei UI", 11), highlightthickness=0)
        self.input.pack(side="left", fill="x", expand=True)
        self.input.bind("<Return>", self.send)
        self.input.bind("<Shift-Return>", lambda e: None)  # newline
        send = tk.Label(bottom, text=t("buddy_send"), bg=GOOD, fg=BG, padx=14, cursor="hand2",
                        font=f("Microsoft YaHei UI", 11))
        send.pack(side="left", fill="y", padx=(8, 0))
        send.bind("<Button-1>", self.send)

        body = tk.Frame(top, bg=PANEL)
        body.pack(fill="both", expand=True, padx=14)
        self.view = tk.Text(body, bg=PANEL, fg=FG, relief="flat", wrap="word", cursor="arrow", width=1, height=1,
                            padx=int(12 * s), pady=int(10 * s), spacing1=int(2 * s), spacing3=int(4 * s),
                            font=f("Microsoft YaHei UI", 11), highlightthickness=0)
        scroll = tk.Scrollbar(body, command=self.view.yview)
        self.view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        self.view.tag_configure("buddy_name", foreground=GOOD, font=f("Microsoft YaHei UI Semibold", 10),
                                spacing1=int(10 * s))
        self.view.tag_configure("me_name", foreground=ACCENT, font=f("Microsoft YaHei UI Semibold", 10),
                                spacing1=int(10 * s))
        self.view.tag_configure("note", foreground=FG_DIM, font=f("Microsoft YaHei UI", 9))
        self.view.tag_configure("question", font=f("Microsoft YaHei UI", 11) + ("bold",), spacing1=int(6 * s))
        self.view.tag_configure("option", lmargin1=int(14 * s), lmargin2=int(34 * s), spacing1=int(3 * s))
        self.view.tag_configure("option_hover", background="#36405a")
        self.view.tag_configure("code", font=f("Consolas", 10), background="#20252f", lmargin1=int(10 * s),
                                lmargin2=int(10 * s))
        self.view.tag_configure("link", foreground=ACCENT, underline=True, font=f("Microsoft YaHei UI", 9))
        self.view.tag_configure("me_text", foreground="#d6e9ff", lmargin1=int(24 * s), lmargin2=int(24 * s))
        self.view.tag_configure("thinking", foreground=FG_DIM, font=f("Microsoft YaHei UI", 10) + ("italic",),
                                spacing1=int(10 * s))
        for kind, color in (("✓", GOOD), ("~", "#f0b85a"), ("✗", "#e57373")):
            self.view.tag_configure("badge" + kind, foreground=color, font=f("Microsoft YaHei UI", 10) + ("bold",))
        self.tags = 0

        top.bind("<Escape>", lambda e: top.destroy())
        top.geometry(f"{int(700 * s)}x{int(620 * s)}")
        self.reload()
        self.set_busy(feature.bridge.busy or feature.waiting)
        self.set_context(feature.current_context())
        top.lift()
        top.focus_force()
        self.input.focus_set()

    def reload(self):
        v = self.view
        v.configure(state="normal")
        v.delete("1.0", "end")
        rows = self.feature.store.messages(dt.date.today())
        if not rows:
            v.insert("end", t("buddy_empty") + "\n", "note")
        for r in rows:
            self.add_line(r["role"], r["text"], scroll=False)
        v.configure(state="disabled")
        v.see("end")

    def add_line(self, role, text, scroll=True):
        v = self.view
        v.configure(state="normal")
        start = v.index("end-1c")
        name = t("buddy_name") if role == "buddy" else t("buddy_me")
        v.insert("end", f"{name}\n", "buddy_name" if role == "buddy" else "me_name")
        if role == "buddy":
            self.add_buddy_text(text)
        else:
            v.insert("end", text.strip() + "\n", "me_text")
        v.configure(state="disabled")
        if scroll:
            v.see("end")
            v.see(start)  # a long reply is read from its start, not its end

    def add_buddy_text(self, text):
        """Lay out a reply: the question in bold, clickable answer options, code blocks, a link to the slides."""
        v = self.view
        lines = text.strip().splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        for n, line in enumerate(lines):
            if n == 0 and BADGE_RE.match(line):
                v.insert("end", line.strip() + "\n", "badge" + line[0])
                continue
            m = OPTION_RE.match(line)
            slides = SLIDES_RE.match(line.strip())
            self.tags += 1
            tag = f"x{self.tags}"
            if m:
                v.insert("end", line.strip() + "\n", ("option", tag))
                self.clickable(tag, lambda l=m.group(1).upper(): self.pick(l), hover=True)
            elif slides:
                v.insert("end", line.strip() + "\n", ("link", tag))
                self.clickable(tag, lambda d=slides.group(1), s=slides.group(2): self.feature.reopen_slides(d, s))
            elif line.startswith(("    ", "\t")):
                v.insert("end", (line[4:] if line.startswith("    ") else line.lstrip("\t")).rstrip() + "\n", "code")
            elif NOTE_RE.match(line.strip()):
                v.insert("end", line.strip() + "\n", "note")
            elif line.rstrip().endswith(("?", "？")):
                v.insert("end", line.strip() + "\n", "question")
            else:
                v.insert("end", line.rstrip() + "\n")

    def clickable(self, tag, action, hover=False):
        v = self.view
        v.tag_bind(tag, "<Enter>", lambda e: (v.configure(cursor="hand2"),
                                              hover and v.tag_add("option_hover", *v.tag_ranges(tag))))
        v.tag_bind(tag, "<Leave>", lambda e: (v.configure(cursor="arrow"), v.tag_remove("option_hover", "1.0", "end")))
        v.tag_bind(tag, "<Button-1>", lambda e: action())

    def pick(self, letter):
        """Clicking an option starts the answer with it; the student adds why (self-explanation) and sends."""
        self.input.delete("1.0", "end")
        self.input.insert("1.0", t("buddy_pick", letter=letter))
        self.input.focus_set()
        self.input.mark_set("insert", "end-1c")

    def set_busy(self, busy):
        """While Claude works: a "thinking" line at the end of the chat, and the quick replies greyed out."""
        if not self.top.winfo_exists():
            return
        self.status.configure(text=t("buddy_thinking") if busy else "")
        for b in self.quick_buttons:
            b.configure(fg=FG_DIM if busy else ACCENT, cursor="arrow" if busy else "hand2")
        v = self.view
        v.configure(state="normal")
        v.delete(*v.tag_ranges("thinking")[:2]) if v.tag_ranges("thinking") else None
        if busy:
            v.insert("end", t("buddy_thinking_line") + "\n", "thinking")
            v.see("end")
        v.configure(state="disabled")

    def set_context(self, text):
        if self.top.winfo_exists():
            self.context.configure(text=text)

    def send(self, _=None):
        text = self.input.get("1.0", "end").strip()
        if text:
            self.input.delete("1.0", "end")
            self.feature.chat(text)
        return "break"  # keep Enter from adding a newline

"""Mastery checklist: every topic on each course's lecture slides, and how well the student understands it.

Claude Code reads the slides once (Popper extracts their text locally first, so Claude reads small text
files instead of rendering PDFs) and lists the topics of each deck. Each answer to the buddy's questions
then updates the topic's estimate with Bayesian Knowledge Tracing (Corbett & Anderson 1995; same
equations as pyBKT, MIT), so one lucky answer doesn't count as understood but two good ones do.

The buddy asks about gaps first (shaky topics, then topics not covered yet, in slide order), mostly in the
course whose exam is nearest, and comes back to understood topics after 3, 7 and 14 days.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from urllib.parse import quote

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, GOOD, LATE, PANEL

# Bayesian Knowledge Tracing: chance the topic is known before any answer, of answering right without
# knowing it (guess), of answering wrong while knowing it (slip), and of learning it from one question
PRIOR, GUESS, SLIP, LEARN = 0.3, 0.2, 0.1, 0.15
KNOWN = 0.85                  # at or above this, the topic counts as understood
RECHECK_DAYS = [3, 7, 14]     # spaced re-checks of understood topics
COURSE_RE = re.compile(r"\b([A-Z]{2,4})\s*-?\s*(\d{3})\b")
SLIDE_EXT = (".pdf", ".pptx")
EXAM_RE = re.compile(r"(?i)midterm|exam|final|practice|sample|unit test|考试")  # past exams by file name
MAX_PAST_EXAMS = 6
SKIP_DIRS = {".git", ".vscode", "node_modules", "__pycache__", ".venv"}
MAX_FILE_MB = 40              # textbooks are bigger than any slide deck
MAX_CANDIDATES = 200
BATCH_CHARS = 60_000          # slide text read in one Claude call
TEXT_LIMIT = 150_000          # longest text kept per deck

BUILD_SYSTEM = """You help build a study checklist from a university student's lecture slides. \
Reply with JSON only: no other text, no Markdown fences."""

CLASSIFY_PROMPT = """These files are in the student's folder for the course {course}. Using only the \
file names and folders (don't open them), pick the lecture slide decks for {course} itself: skip textbooks, \
homework, exams, study guides, syllabi, notes, papers and slides of other courses. Where the same deck \
appears twice, pick one. Put them in lecture order.

{files}

Reply as {{"slides": [file numbers in lecture order]}}."""

TOPICS_PROMPT = """Below are plain-text copies of lecture slides for {course} ("--- slide N ---" marks each \
slide). Read each file, then list the topics a student must understand for the exam, in slide order: \
3 to 12 per deck, each a concept, technique or kind of code the slides actually teach (not the title \
slide, logistics or a single example). Name topics in English, short and specific (e.g. "LL(1) FIRST and \
FOLLOW sets", not "Parsing").

{files}

Reply as {{"decks": [{{"deck": <deck number>, "topics": [{{"topic": "...", "slides": "first-last", \
"kind": "concept|code|math"}}]}}]}}."""


def course_code(folder):
    """'CSE 307' from 'CSE 307 Principles of Programming Languages'; else the code most files in it carry
    (a folder called 'Syllabus' full of 'AMS 310 ...' files); else the folder name."""
    name = os.path.basename(os.path.normpath(folder))
    m = COURSE_RE.search(name.upper())
    if m:
        return f"{m.group(1)} {m.group(2)}"
    counts = {}
    try:
        for entry in os.listdir(folder):
            m = COURSE_RE.search(entry.upper())
            if m:
                code = f"{m.group(1)} {m.group(2)}"
                counts[code] = counts.get(code, 0) + 1
    except OSError:
        pass
    return max(counts, key=counts.get) if counts else name


def exam_days(course, goals, today=None):
    """Days until the nearest open goal that mentions the course code (an exam), or None."""
    today = today or dt.date.today()
    key = course.replace(" ", "").upper()
    days = [(dt.date.fromisoformat(g["deadline"]) - today).days for g in goals
            if g["deadline"] and key in (g["title"] or "").replace(" ", "").upper()]
    days = [d for d in days if d >= 0]
    return min(days) if days else None


def candidate_files(folder):
    """Every PDF/PPTX under the folder (one per file name, since decks get copied around), relative paths."""
    found, seen = [], set()
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if not name.lower().endswith(SLIDE_EXT) or name.startswith("~$") or name.lower() in seen:
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > MAX_FILE_MB * 2**20:
                    continue
            except OSError:
                continue
            seen.add(name.lower())
            found.append(path)
            if len(found) >= MAX_CANDIDATES:
                return found
    return found


def extract_text(path):
    """The slides as text, one '--- slide N ---' block per slide. '' if it has none (a scanned PDF)."""
    parts = []
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        for i, page in enumerate(PdfReader(path).pages, 1):
            parts.append(f"--- slide {i} ---\n{(page.extract_text() or '').strip()}")
    else:
        from pptx import Presentation
        for i, slide in enumerate(Presentation(path).slides, 1):
            lines = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    lines.append(shape.text_frame.text)
                elif getattr(shape, "has_table", False) and shape.has_table:
                    lines += [" | ".join(c.text for c in row.cells) for row in shape.table.rows]
            if slide.has_notes_slide:
                lines.append("(notes) " + slide.notes_slide.notes_text_frame.text)
            parts.append(f"--- slide {i} ---\n" + "\n".join(x for x in lines if x.strip()))
    text = "\n".join(parts)
    return text[:TEXT_LIMIT] if len(re.sub(r"--- slide \d+ ---|\s", "", text)) > 200 else ""


def first_slide(slides):
    """3 from '3-7' (or '3', 'slide 3'); 1 if there's no number."""
    m = re.search(r"\d+", str(slides or ""))
    return max(1, int(m.group())) if m else 1


def short_slides(slides):
    """'12' for '12-12', which reads oddly; other ranges as they are."""
    ends = re.findall(r"\d+", str(slides or ""))
    return ends[0] if len(ends) == 2 and ends[0] == ends[1] else str(slides or "")


def open_slides(path, slides):
    """Show the deck at the first of `slides`: PDFs in Edge (which can jump to a page), anything else as is."""
    if path.lower().endswith(".pdf"):
        edge = shutil.which("msedge") or os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge",
                                                      "Application", "msedge.exe")
        if os.path.exists(edge):
            url = "file:///" + quote(path.replace("\\", "/"), safe="/:") + f"#page={first_slide(slides)}"
            subprocess.Popen([edge, url], creationflags=subprocess.CREATE_NO_WINDOW)
            return
    os.startfile(path)


def past_exams(folder, out_dir, workdir):
    """Text copies of the past exams in a course folder (files named midterm/exam/sample...), relative to
    `workdir`. Extracted once; the same exam saved under two names counts once."""
    found, seen = [], set()
    os.makedirs(out_dir, exist_ok=True)
    for path in candidate_files(folder):
        if not EXAM_RE.search(os.path.basename(path)) or not path.lower().endswith(".pdf"):
            continue
        dst = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + ".txt")
        try:
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(path):
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(extract_text(path))
            with open(dst, encoding="utf-8") as fh:
                text = fh.read()
        except Exception:  # unreadable file: skip it
            continue
        key = re.sub(r"\s", "", text)[:2000]
        if text and key not in seen:
            seen.add(key)
            found.append(os.path.relpath(dst, workdir))
        if len(found) >= MAX_PAST_EXAMS:
            break
    return found


def parse_json(text):
    """The first JSON object in a reply (Claude sometimes wraps it in a sentence or a fence)."""
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def status(row):
    """'new' (not covered yet), 'shaky' or 'known' (understood)."""
    if not row["attempts"]:
        return "new"
    return "known" if row["p"] >= KNOWN else "shaky"


def bkt(p, verdict):
    """Updated chance the topic is known after one answer; 'partial' counts half right, half wrong."""
    right = p * (1 - SLIP) / (p * (1 - SLIP) + (1 - p) * GUESS)
    wrong = p * SLIP / (p * SLIP + (1 - p) * (1 - GUESS))
    post = {"correct": right, "wrong": wrong}.get(verdict, (right + wrong) / 2)
    return post + (1 - post) * LEARN


class MasteryStore:
    """Slide files per course (and whether they're read) and the topics on them with their mastery."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS mastery_files (
                id        INTEGER PRIMARY KEY,
                course    TEXT NOT NULL,
                path      TEXT NOT NULL UNIQUE,
                state     TEXT NOT NULL,     -- 'new' (not sorted yet), 'skip', 'slides' (to read), 'done', 'failed'
                ord       INTEGER DEFAULT 0, -- lecture order
                text_file TEXT,              -- extracted text, relative to the buddy's working folder
                exam      INTEGER DEFAULT 1  -- 1 if the next exam covers this deck
            )""")
        if "exam" not in [c[1] for c in self.db.execute("PRAGMA table_info(mastery_files)")]:
            self.db.execute("ALTER TABLE mastery_files ADD COLUMN exam INTEGER DEFAULT 1")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS mastery_topics (
                id       INTEGER PRIMARY KEY,
                course   TEXT NOT NULL,
                file_id  INTEGER,
                topic    TEXT NOT NULL,
                slides   TEXT,
                kind     TEXT,               -- concept / code / math
                ord      INTEGER,            -- position in the course (deck, then slide order)
                p        REAL NOT NULL,      -- chance it's understood (Bayesian Knowledge Tracing)
                attempts INTEGER DEFAULT 0,
                correct  INTEGER DEFAULT 0,
                last     REAL,
                step     INTEGER DEFAULT 0,  -- spaced re-check step once understood
                due      REAL,               -- next re-check of an understood topic
                UNIQUE(course, topic)
            )""")
        self.db.commit()

    # ---------- files

    def sync_files(self, course, paths):
        """Remember files not seen before; returns how many are new."""
        new = 0
        for path in paths:
            cur = self.db.execute("INSERT OR IGNORE INTO mastery_files (course, path, state) VALUES (?, ?, 'new')",
                                  (course, path))
            new += cur.rowcount
        self.db.commit()
        return new

    def files(self, course, *states):
        marks = ",".join("?" * len(states))
        return self.db.execute(f"SELECT * FROM mastery_files WHERE course=? AND state IN ({marks}) ORDER BY ord, id",
                               (course, *states)).fetchall()

    def set_file(self, file_id, state, ord=None, text_file=None):
        self.db.execute("UPDATE mastery_files SET state=?, ord=COALESCE(?, ord), text_file=COALESCE(?, text_file) "
                        "WHERE id=?", (state, ord, text_file, file_id))
        self.db.commit()

    def set_exam(self, file_id, on):
        """Whether the next exam covers this deck (questions and readiness stay inside the exam's decks)."""
        self.db.execute("UPDATE mastery_files SET exam=? WHERE id=?", (1 if on else 0, file_id))
        self.db.commit()

    def retry_failed(self):
        self.db.execute("UPDATE mastery_files SET state='slides' WHERE state='failed'")
        self.db.commit()

    # ---------- topics

    def add_topics(self, course, file_row, items):
        for i, item in enumerate(items):
            topic = str(item.get("topic") or "").strip()[:120]
            if topic:
                self.db.execute("INSERT OR IGNORE INTO mastery_topics (course, file_id, topic, slides, kind, ord, p) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (course, file_row["id"], topic, str(item.get("slides") or "")[:20],
                                 str(item.get("kind") or "concept")[:10], file_row["ord"] * 1000 + i, PRIOR))
        self.db.commit()

    def courses(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT course FROM mastery_topics")]

    def topics(self, course):
        """Topics in slide order, with their deck's file and whether the exam covers it."""
        return self.db.execute("SELECT t.*, f.path, f.text_file, COALESCE(f.exam, 1) AS exam FROM mastery_topics t "
                               "LEFT JOIN mastery_files f ON f.id = t.file_id WHERE t.course=? ORDER BY t.ord",
                               (course,)).fetchall()

    def topic(self, topic_id):
        return self.db.execute("SELECT t.*, f.path, f.text_file, COALESCE(f.exam, 1) AS exam FROM mastery_topics t "
                               "LEFT JOIN mastery_files f ON f.id = t.file_id WHERE t.id=?", (topic_id,)).fetchone()

    def deck(self, name):
        """A read slide deck's path from its file name (a [[source]] tag), or None."""
        name = os.path.basename((name or "").strip()).lower()
        for (path,) in self.db.execute("SELECT path FROM mastery_files WHERE state='done'"):
            if os.path.basename(path).lower() == name:
                return path
        return None

    def find(self, name):
        """A topic id by name (from a [[topic]] tag), exact first, then one containing the other."""
        name = (name or "").strip().lower()
        if not name:
            return None
        rows = self.db.execute("SELECT id, topic FROM mastery_topics").fetchall()
        for r in rows:
            if r["topic"].lower() == name:
                return r["id"]
        for r in rows:
            if len(r["topic"]) > 5 and (r["topic"].lower() in name or name in r["topic"].lower()):
                return r["id"]
        return None

    def in_scope(self, rows):
        """The rows the exam covers (all of them if no deck is marked as covered)."""
        covered = [r for r in rows if r["exam"]]
        return covered or rows

    def summary(self, course):
        """Counts over the topics the exam covers; 'out' is how many it leaves out."""
        rows = self.topics(course)
        scope = self.in_scope(rows)
        counts = {"new": 0, "shaky": 0, "known": 0}
        for r in scope:
            counts[status(r)] += 1
        total = sum(counts.values())
        counts["total"] = total
        counts["out"] = len(rows) - len(scope)
        counts["ready"] = round(100 * counts["known"] / total) if total else 0
        return counts

    def record(self, topic_id, verdict, now=None):
        """Update a topic from one graded answer."""
        row = self.topic(topic_id)
        if not row:
            return
        now = now or time.time()
        p = bkt(row["p"], verdict)
        step, due = row["step"], None
        if p >= KNOWN:
            # first time understood: re-check soon; each later success spaces it out more
            if row["p"] >= KNOWN and verdict == "correct":
                step = min(step + 1, len(RECHECK_DAYS) - 1)
            due = now + RECHECK_DAYS[step] * 86400
        else:
            step = 0
        self.db.execute("UPDATE mastery_topics SET p=?, attempts=attempts+1, correct=correct+?, last=?, step=?, due=? "
                        "WHERE id=?", (p, verdict == "correct", now, step, due, topic_id))
        self.db.commit()

    def pick(self, course, avoid=None, rand=None, now=None, kind=None):
        """The next topic to ask about: gaps first, alternating shaky ones and new ones (interleaving).
        `kind` ('code') narrows it to topics of that kind when the course has any."""
        import random
        rand = rand or random.random
        now = now or time.time()
        rows = [r for r in self.in_scope(self.topics(course)) if r["id"] != avoid]
        if kind and any(r["kind"] == kind for r in rows):
            rows = [r for r in rows if r["kind"] == kind]
        shaky = sorted((r for r in rows if status(r) == "shaky"), key=lambda r: r["p"])
        new = [r for r in rows if status(r) == "new"]
        due = sorted((r for r in rows if status(r) == "known" and (r["due"] or 0) <= now), key=lambda r: r["due"] or 0)
        if shaky and new:
            return shaky[0] if rand() < 0.5 else new[0]
        for group in (shaky, new, due):
            if group:
                return group[0]
        return min(rows, key=lambda r: r["last"] or 0) if rows else None

    def answered_on(self, start, end):
        """(topic, verdict) for the slide topics answered in a time range."""
        return self.db.execute("SELECT t.topic, q.verdict FROM buddy_questions q JOIN mastery_topics t "
                               "ON t.id = q.topic_id WHERE q.verdict IS NOT NULL AND q.ts >= ? AND q.ts < ? "
                               "ORDER BY q.ts", (start, end)).fetchall()


class SlideBuilder:
    """Finds each course's slide decks and has Claude list their topics, one Claude call at a time."""

    def __init__(self, feature, bridge, store):
        self.feature, self.bridge, self.store = feature, bridge, store
        self.app = feature.app
        self.running = False
        self.progress = ""
        self.error = ""

    def slides_dir(self, course):
        return os.path.join(self.bridge.workdir, "slides", re.sub(r'[<>:"/\\|?*]', "_", course))

    def start(self):
        """Look for new slide files in every course folder, then read whatever isn't read yet."""
        if self.running:
            return
        self.running, self.error = True, ""
        self.store.retry_failed()
        self.set_progress(t("mastery_scanning"))

        def scan():
            found = {}
            for folder in self.feature.folders():
                if os.path.isdir(folder):
                    found.setdefault(course_code(folder), []).extend(candidate_files(folder))
            self.app.ui_q.put(("call", lambda: self.after_scan(found)))
        threading.Thread(target=scan, daemon=True).start()

    def after_scan(self, found):
        for course, paths in found.items():
            self.store.sync_files(course, paths)
        # the course whose exam is nearest gets its checklist first
        goals = self.app.todos.open_goals()
        self.courses = sorted(found, key=lambda c: (exam_days(c, goals) is None, exam_days(c, goals) or 0))
        self.step()

    def step(self):
        """Do the next piece of work: sort new files of a course, else read the next batch of decks."""
        for course in self.courses:
            new = self.store.files(course, "new")
            if new:
                return self.classify(course, new)
        for course in self.courses:
            todo = self.store.files(course, "slides")
            if todo:
                return self.read_decks(course, todo)
        self.running = False
        self.set_progress("")

    def classify(self, course, rows):
        self.set_progress(t("mastery_sorting", course=course))
        folder = next((f for f in self.feature.folders() if course_code(f) == course), "")
        listing = "\n".join(f"{i}. {os.path.relpath(r['path'], folder)}" for i, r in enumerate(rows, 1))
        prompt = CLASSIFY_PROMPT.format(course=course, files=listing)

        def done(result):
            data = parse_json(result.get("text")) if result["ok"] else None
            if data is None:
                return self.fail(course, rows, result.get("error") or "no JSON")
            picked = [n for n in data.get("slides", []) if isinstance(n, int) and 1 <= n <= len(rows)]
            base = len(self.store.files(course, "slides", "done", "failed"))
            for i, r in enumerate(rows, 1):
                if i in picked:
                    self.store.set_file(r["id"], "slides", ord=base + picked.index(i) + 1)
                else:
                    self.store.set_file(r["id"], "skip")
            self.step()
        self.bridge.ask(prompt, [], None, done, system=BUILD_SYSTEM, timeout=180)

    def read_decks(self, course, todo):
        total = len(self.store.files(course, "slides", "done", "failed"))
        done_count = total - len(todo)
        self.set_progress(t("mastery_reading", course=course, done=done_count, total=total))
        folder = self.slides_dir(course)

        def extract():
            os.makedirs(folder, exist_ok=True)
            batch, chars = [], 0
            for r in todo:
                name = f"{r['ord']:02d} {os.path.splitext(os.path.basename(r['path']))[0]}.txt"
                rel = os.path.relpath(os.path.join(folder, name), self.bridge.workdir)
                try:
                    text = extract_text(r["path"])
                except Exception:  # a broken or locked file: let Claude open the original
                    text = ""
                if text:
                    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                        fh.write(text)
                batch.append((r, rel if text else None))
                chars += len(text) or 20_000
                if chars >= BATCH_CHARS:
                    break
            self.app.ui_q.put(("call", lambda: self.ask_topics(course, batch)))
        threading.Thread(target=extract, daemon=True).start()

    def ask_topics(self, course, batch):
        lines = []
        for i, (r, rel) in enumerate(batch, 1):
            where = f"text: {rel}" if rel else f"no text layer, read the original: {r['path']}"
            lines.append(f"Deck {i}: {os.path.basename(r['path'])} ({where})")
        prompt = TOPICS_PROMPT.format(course=course, files="\n".join(lines))
        folders = self.feature.folders() if any(rel is None for _, rel in batch) else []

        def done(result):
            data = parse_json(result.get("text")) if result["ok"] else None
            if data is None:
                return self.fail(course, [r for r, _ in batch], result.get("error") or "no JSON")
            decks = {d.get("deck"): d.get("topics") or [] for d in data.get("decks", []) if isinstance(d, dict)}
            for i, (r, rel) in enumerate(batch, 1):
                self.store.set_file(r["id"], "done", text_file=rel)
                self.store.add_topics(course, self.store.db.execute(
                    "SELECT * FROM mastery_files WHERE id=?", (r["id"],)).fetchone(), decks.get(i, []))
            self.feature.mastery_changed()
            self.step()
        self.bridge.ask(prompt, folders, None, done, system=BUILD_SYSTEM, timeout=420)

    def fail(self, course, rows, error):
        """Leave these files for the next scan and stop for now (most failures are quota or login)."""
        for r in rows:
            self.store.set_file(r["id"], "failed" if r["state"] != "new" else "new")
        self.error = str(error)[:160]
        self.running = False
        self.set_progress(t("mastery_failed", error=self.error))

    def set_progress(self, text):
        self.progress = text
        win = self.feature.window("mastery")
        if win:
            win.set_status(text)


class MasteryWindow:
    """Per course: how ready for the exam, and every slide topic marked understood / shaky / not yet."""

    MARK = {"known": "✓", "shaky": "~", "new": "☐"}

    def __init__(self, app, feature):
        self.app, self.feature = app, feature
        top = self.top = tk.Toplevel(app.root)
        top.title(t("mastery_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s, f = app.scale, app.font

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(head, text=t("mastery_title"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 14)).pack(side="left")
        update = tk.Label(head, text=t("mastery_update"), bg=PANEL, fg=ACCENT, padx=10, pady=2, cursor="hand2",
                          font=f("Microsoft YaHei UI", 9))
        update.pack(side="right")
        update.bind("<Button-1>", lambda e: feature.builder.start())
        self.status = tk.Label(top, bg=BG, fg=ACCENT, anchor="w", font=f("Microsoft YaHei UI", 9))
        self.status.pack(fill="x", padx=14)
        tk.Label(top, text=t("mastery_hint"), bg=BG, fg=FG_DIM, anchor="w", justify="left",
                 wraplength=int(530 * s), font=f("Microsoft YaHei UI", 9)).pack(fill="x", padx=14, pady=(0, 6))

        body = tk.Frame(top, bg=PANEL)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.view = tk.Text(body, bg=PANEL, fg=FG, relief="flat", wrap="word", cursor="arrow", width=1, height=1,
                            padx=int(12 * s), pady=int(10 * s), spacing1=int(1 * s), spacing3=int(2 * s),
                            font=f("Microsoft YaHei UI", 10), highlightthickness=0)
        scroll = tk.Scrollbar(body, command=self.view.yview)
        self.view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        v = self.view
        v.tag_configure("course", font=f("Microsoft YaHei UI Semibold", 13), spacing1=int(12 * s))
        v.tag_configure("exam", foreground=ACCENT, font=f("Microsoft YaHei UI", 10))
        v.tag_configure("ready", foreground=GOOD, font=f("Microsoft YaHei UI Semibold", 11))
        v.tag_configure("bar_on", foreground=GOOD)
        v.tag_configure("bar_off", foreground="#475066")
        v.tag_configure("dim", foreground=FG_DIM, font=f("Microsoft YaHei UI", 9))
        v.tag_configure("deck", foreground=FG_DIM, font=f("Microsoft YaHei UI", 9), spacing1=int(8 * s))
        for st, color in (("known", GOOD), ("shaky", "#f0b85a"), ("new", FG_DIM)):
            v.tag_configure("mark_" + st, foreground=color)
        v.tag_configure("topic_new", foreground=FG)
        v.tag_configure("topic_shaky", foreground="#f0b85a")
        v.tag_configure("topic_known", foreground=FG_DIM)
        v.tag_configure("topic_out", foreground="#5d6578")
        v.tag_configure("scope_on", foreground=GOOD, font=f("Microsoft YaHei UI", 9))
        v.tag_configure("scope_off", foreground="#7d8597", font=f("Microsoft YaHei UI", 9))
        v.tag_configure("failed", foreground=LATE)

        top.bind("<Escape>", lambda e: top.destroy())
        top.geometry(f"{int(560 * s)}x{int(680 * s)}")
        self.refresh()
        self.set_status(feature.builder.progress)
        top.lift()

    def set_status(self, text):
        if self.top.winfo_exists():
            self.status.configure(text=text, fg=LATE if self.feature.builder.error and not
                                  self.feature.builder.running else ACCENT)

    def refresh(self):
        v = self.view
        top_line = v.yview()[0]
        v.configure(state="normal")
        v.delete("1.0", "end")
        courses = self.feature.course_list()
        if not courses:
            v.insert("end", t("mastery_no_folders") + "\n", "dim")
        for course, days in courses:
            self.add_course(course, days)
        v.configure(state="disabled")
        v.yview_moveto(top_line)

    def toggle_exam(self, file_id, on):
        self.feature.mastery.set_exam(file_id, on)
        self.feature.mastery_changed()

    def add_course(self, course, days):
        v, store = self.view, self.feature.mastery
        v.insert("end", course + "   ", "course")
        if days is None:
            v.insert("end", t("mastery_no_exam"), "dim")
        else:
            v.insert("end", t("mastery_exam", days=days) if days else t("mastery_exam_today"), "exam")
        v.insert("end", "\n")
        sm = store.summary(course)
        if not sm["total"]:
            v.insert("end", t("mastery_empty_course") + "\n", "dim")
            return
        filled = round(20 * sm["known"] / sm["total"])
        v.insert("end", "█" * filled, "bar_on")
        v.insert("end", "█" * (20 - filled), "bar_off")
        v.insert("end", "  " + t("mastery_ready", ready=sm["ready"]) + "\n", "ready")
        v.insert("end", t("mastery_counts", known=sm["known"], shaky=sm["shaky"], new=sm["new"])
                 + (t("mastery_out", n=sm["out"]) if sm["out"] else "") + "\n", "dim")
        # the exam's decks first with every topic; decks it leaves out folded into one line each
        rows = sorted(store.topics(course), key=lambda r: (not r["exam"], r["ord"]))
        deck = None
        for r in rows:
            if r["path"] != deck:
                deck = r["path"]
                v.insert("end", os.path.basename(deck or "") + "   ", "deck" if r["exam"] else "topic_out")
                scope = f"s{r['file_id']}"
                v.insert("end", t("mastery_in_exam") if r["exam"] else t("mastery_not_exam"),
                         ("scope_on" if r["exam"] else "scope_off", scope))
                if not r["exam"]:
                    n = sum(1 for x in rows if x["file_id"] == r["file_id"])
                    v.insert("end", "   " + t("mastery_folded", n=n), "dim")
                v.insert("end", "\n")
                v.tag_bind(scope, "<Enter>", lambda e: v.configure(cursor="hand2"))
                v.tag_bind(scope, "<Leave>", lambda e: v.configure(cursor="arrow"))
                v.tag_bind(scope, "<Button-1>", lambda e, i=r["file_id"], on=r["exam"]: self.toggle_exam(i, not on))
            if not r["exam"]:
                continue
            st = status(r)
            tag = f"t{r['id']}"
            v.insert("end", f"  {self.MARK[st]} ", "mark_" + st)
            v.insert("end", r["topic"], ("topic_" + st, tag))
            if r["slides"]:
                v.insert("end", f"   {t('mastery_slides', slides=short_slides(r['slides']))}", "dim")
            v.insert("end", "\n")
            v.tag_bind(tag, "<Enter>", lambda e: v.configure(cursor="hand2"))
            v.tag_bind(tag, "<Leave>", lambda e: v.configure(cursor="arrow"))
            v.tag_bind(tag, "<Button-1>", lambda e, i=r["id"]: self.feature.ask_about(i))

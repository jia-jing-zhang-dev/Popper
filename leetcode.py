"""LeetCode plan: the Easy and Medium problems of NeetCode 150 in Python, in 12 weeks of about 45 minutes a day.

Problems come grouped by pattern (arrays & hashing, two pointers, ... dynamic programming), easy before medium
within a pattern, so each pattern is learned as a block first. Every attempt is timed and rated by the
student (on my own / needed a hint / looked at the solution); problems that weren't solved cleanly, or only
slowly, come back to be solved again after a few days, and a clean solve comes back once more after two weeks
to check it stuck. Fluent = solved cleanly twice.

Starting a problem opens its LeetCode page, a ready-to-run folder in VS Code (made by leetcode-py,
wislertt/leetcode-py, Apache-2.0: solution.py to fill in and a pytest suite of 10+ cases) and, when the
problem uses an idea from CSE 373, that lecture's slides.
"""

import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

LIST = "neetcode-150"
LEVELS = ("Easy", "Medium")
PLAN_DAYS = 84               # 12 weeks
MINUTES_PER_DAY = 45
SLOW = {"Easy": 20, "Medium": 30}  # minutes; a clean solve slower than this still needs practice
AGAIN = {"solution": 2, "hint": 3, "slow": 7}  # days until a problem is solved again
CHECK_DAYS = [14, 45]        # after the first and second clean solve

# patterns in NeetCode roadmap order; a problem goes to the first one its topics match (see pattern_of)
PATTERNS = ["arrays", "two_pointers", "sliding_window", "stack", "binary_search", "linked_list", "trees", "tries",
            "heap", "backtracking", "graphs", "dp", "greedy", "intervals", "math", "bits"]

# which CSE 373 lecture a LeetCode topic belongs to (matched against the deck's file name)
SLIDES_373 = [("Breadth-First Search", r"Breadth"), ("Depth-First Search", r"Depth"),
              ("Shortest Path", r"Shortest"), ("Topological Sort", r"Depth"), ("Union Find", r"Spanning"),
              ("Union-Find", r"Spanning"), ("Graph", r"Graph Data"), ("Graph Theory", r"Graph Data"),
              ("Backtracking", r"Backtracking"), ("Dynamic Programming", r"Dynamic Programming"),
              ("Heap (Priority Queue)", r"Heapsort"), ("Hash Table", r"Hashing"), ("Merge Sort", r"Mergesort"),
              ("Sorting", r"Mergesort"), ("Binary Search Tree", r"Dictionaries")]


def resources():
    """leetcode-py's bundled problem data, or None if the package isn't installed."""
    try:
        import leetcode_py
    except ImportError:
        return None
    path = os.path.join(os.path.dirname(leetcode_py.__file__), "cli", "resources", "leetcode", "json")
    return path if os.path.isdir(path) else None


def pattern_of(topics, title):
    t = set(topics)
    title = title.lower()
    rules = [
        ("tries", {"Trie"}), ("linked_list", {"Linked List", "Doubly-Linked List"}),
        ("trees", {"Tree", "Binary Tree", "Binary Search Tree"}), ("backtracking", {"Backtracking"}),
        ("heap", {"Heap (Priority Queue)"}),
        ("graphs", {"Graph", "Graph Theory", "Union Find", "Union-Find", "Topological Sort", "Shortest Path"}),
    ]
    for name, keys in rules:
        if t & keys:
            return name
    if t & {"Breadth-First Search", "Depth-First Search"} and "Matrix" in t:
        return "graphs"
    if "Dynamic Programming" in t:
        return "dp"
    if "interval" in title or "meeting" in title:
        return "intervals"
    for name, keys in (("sliding_window", {"Sliding Window"}), ("binary_search", {"Binary Search"}),
                       ("stack", {"Stack", "Monotonic Stack"}), ("two_pointers", {"Two Pointers"}),
                       ("bits", {"Bit Manipulation"}), ("greedy", {"Greedy"}),
                       ("math", {"Math", "Geometry", "Matrix"})):
        if t & keys:
            return name
    return "arrays"


def load_plan():
    """[{slug, number, title, difficulty, topics, pattern}] in study order, or [] without leetcode-py."""
    base = resources()
    if not base:
        return []
    import json5
    with open(os.path.join(base, "tags.json5"), encoding="utf-8") as fh:
        slugs = [s for s in json5.load(fh)[LIST] if isinstance(s, str)]
    plan = []
    for slug in slugs:
        try:
            with open(os.path.join(base, "problems", slug + ".json"), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if d["difficulty"] not in LEVELS:
            continue
        topics = [x.strip() for x in d.get("topics", "").split(",") if x.strip()]
        plan.append({"slug": slug, "number": int(d["problem_number"]), "title": d["problem_title"],
                     "difficulty": d["difficulty"], "topics": topics,
                     "pattern": pattern_of(topics, d["problem_title"])})
    plan.sort(key=lambda p: (PATTERNS.index(p["pattern"]), LEVELS.index(p["difficulty"]), p["number"]))
    return plan


def url(slug):
    """LeetCode's page for a leetcode-py problem name (two_sum -> two-sum)."""
    return f"https://leetcode.com/problems/{slug.replace('_', '-')}/description/"


class LeetCodeStore:
    """The plan's problems and how each attempt went. Lives in vocab.db like everything else."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS leetcode_problems (
                slug       TEXT PRIMARY KEY,
                number     INTEGER,
                title      TEXT NOT NULL,
                difficulty TEXT,
                topics     TEXT,
                pattern    TEXT,
                ord        INTEGER,
                status     TEXT DEFAULT 'new',  -- new / learning (solve again) / solved (clean once) / fluent
                clean      INTEGER DEFAULT 0,   -- clean solves so far
                attempts   INTEGER DEFAULT 0,
                started    REAL,                -- an attempt in progress since then
                last       REAL,
                due        REAL,                -- when to solve it again
                minutes    REAL                 -- time of the latest attempt
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS leetcode_attempts (
                id      INTEGER PRIMARY KEY,
                slug    TEXT NOT NULL,
                ts      REAL NOT NULL,
                minutes REAL,
                rating  TEXT                    -- clean / hint / solution
            )""")
        self.db.commit()

    def sync(self, plan):
        """Add the plan's problems (keeping progress); order follows the plan."""
        for i, p in enumerate(plan):
            self.db.execute("INSERT INTO leetcode_problems (slug, number, title, difficulty, topics, pattern, ord) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(slug) DO UPDATE SET ord=excluded.ord, "
                            "pattern=excluded.pattern, topics=excluded.topics",
                            (p["slug"], p["number"], p["title"], p["difficulty"], ", ".join(p["topics"]),
                             p["pattern"], i))
        self.db.commit()

    def problems(self):
        return self.db.execute("SELECT * FROM leetcode_problems ORDER BY ord").fetchall()

    def problem(self, slug):
        return self.db.execute("SELECT * FROM leetcode_problems WHERE slug=?", (slug,)).fetchone()

    def in_progress(self):
        return self.db.execute("SELECT * FROM leetcode_problems WHERE started IS NOT NULL "
                               "ORDER BY started DESC LIMIT 1").fetchone()

    def start(self, slug, now=None):
        self.db.execute("UPDATE leetcode_problems SET started=NULL WHERE started IS NOT NULL")
        self.db.execute("UPDATE leetcode_problems SET started=? WHERE slug=?", (now or time.time(), slug))
        self.db.commit()

    def cancel(self, slug):
        self.db.execute("UPDATE leetcode_problems SET started=NULL WHERE slug=?", (slug,))
        self.db.commit()

    def finish(self, slug, rating, now=None):
        """Record an attempt rated 'clean', 'hint' or 'solution', and decide when it comes back."""
        now = now or time.time()
        p = self.problem(slug)
        minutes = (now - p["started"]) / 60 if p["started"] else None
        clean = p["clean"]
        if rating == "clean" and minutes is not None and minutes > SLOW.get(p["difficulty"], 30):
            status, due = "learning", now + AGAIN["slow"] * 86400  # right, but not fluent yet
        elif rating == "clean":
            clean += 1
            status = "fluent" if clean >= 2 else "solved"
            due = now + CHECK_DAYS[0] * 86400 if clean == 1 else None
        else:
            status, due = "learning", now + AGAIN[rating] * 86400
        self.db.execute("UPDATE leetcode_problems SET status=?, clean=?, attempts=attempts+1, started=NULL, last=?, "
                        "due=?, minutes=? WHERE slug=?", (status, clean, now, due, minutes, slug))
        self.db.execute("INSERT INTO leetcode_attempts (slug, ts, minutes, rating) VALUES (?, ?, ?, ?)",
                        (slug, now, minutes, rating))
        self.db.commit()

    def attempts(self, start, end):
        return self.db.execute("SELECT a.*, p.title, p.difficulty FROM leetcode_attempts a JOIN leetcode_problems p "
                               "ON p.slug = a.slug WHERE a.ts >= ? AND a.ts < ? ORDER BY a.ts", (start, end)).fetchall()

    def summary(self):
        rows = self.problems()
        counts = {"total": len(rows), "new": 0, "learning": 0, "solved": 0, "fluent": 0}
        for r in rows:
            counts[r["status"]] += 1
        counts["done"] = counts["solved"] + counts["fluent"] + counts["learning"]
        return counts

    def today(self, day_start, day_end, start_date, today=None):
        """(problems to solve again today, new problems for today) — enough new ones to finish on time."""
        rows = self.problems()
        again = [r for r in rows if r["due"] and r["due"] < day_end and r["started"] is None]
        new_left = [r for r in rows if r["status"] == "new" and r["started"] is None]
        done_today = len({a["slug"] for a in self.attempts(day_start, day_end)})
        today = today or dt.date.today()
        days_left = max(1, PLAN_DAYS - (today - start_date).days)
        per_day = max(1, min(3, math.ceil(len(new_left) / days_left)))
        new_today = sum(1 for a in self.attempts(day_start, day_end)
                        if self.db.execute("SELECT COUNT(*) FROM leetcode_attempts WHERE slug=? AND ts < ?",
                                           (a["slug"], a["ts"])).fetchone()[0] == 0)
        return again, new_left[:max(0, per_day - new_today)], done_today

    def pace(self, start_date, today=None):
        """How many problems ahead (+) or behind (-) of an even pace over the plan's days."""
        today = today or dt.date.today()
        s = self.summary()
        elapsed = min(PLAN_DAYS, (today - start_date).days)  # finished days; today is still open
        return s["done"] - round(s["total"] * elapsed / PLAN_DAYS)

    def by_pattern(self):
        out = {}
        for r in self.problems():
            done, total = out.get(r["pattern"], (0, 0))
            out[r["pattern"]] = (done + (r["status"] != "new"), total + 1)
        return [(p, *out[p]) for p in PATTERNS if p in out]


# ---------------------------------------------------------------- the workspace

def workspace(root, python):
    """The folder of all problems, opened in VS Code: tests run with Popper's Python (it has leetcode-py and
    pytest), Ctrl+Shift+B runs the tests of the problem whose file is open."""
    os.makedirs(os.path.join(root, ".vscode"), exist_ok=True)
    settings = {"python.defaultInterpreterPath": python, "python.testing.pytestEnabled": True,
                "python.testing.pytestArgs": ["."], "python.testing.unittestEnabled": False}
    tasks = {"version": "2.0.0", "tasks": [{
        "label": "run tests (this problem)", "type": "process", "command": python,
        "args": ["-m", "pytest", "-q", "${fileDirname}"], "options": {"cwd": "${workspaceFolder}"},
        "group": {"kind": "build", "isDefault": True}, "problemMatcher": []}]}
    for name, data in (("settings.json", settings), ("tasks.json", tasks)):
        with open(os.path.join(root, ".vscode", name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    readme = os.path.join(root, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write("# LeetCode practice\n\nOne folder per problem (made by leetcode-py). Write your answer in "
                     "solution.py, then Ctrl+Shift+B runs its tests.\nOn leetcode.com the method name is camelCase "
                     "(two_sum -> twoSum).\n")


def generate(root, slug, python):
    """Make the problem's folder with leetcode-py if it isn't there yet; returns its solution.py."""
    folder = os.path.join(root, slug)
    if not os.path.exists(os.path.join(folder, "solution.py")):
        cli = "import sys; from leetcode_py.cli.main import app; sys.argv = ['lcpy'] + sys.argv[1:]; app()"
        subprocess.run([python, "-c", cli, "gen", "-s", slug, "-o", root, "--no-check"],
                       capture_output=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return os.path.join(folder, "solution.py")


def deck_373(topics, mastery):
    """(deck path, slides) of the CSE 373 lecture a problem's topics come from, or None."""
    if mastery is None:
        return None
    decks = [r for r in mastery.files("CSE 373", "done")]
    for topic, pattern in SLIDES_373:
        if topic in topics:
            for d in decks:
                if re.search(pattern, os.path.basename(d["path"]), re.I):
                    first = mastery.db.execute("SELECT slides FROM mastery_topics WHERE file_id=? ORDER BY ord "
                                               "LIMIT 1", (d["id"],)).fetchone()
                    return d["path"], (first[0] if first else "1")
    return None


def python_exe():
    """Popper's own Python, console version (pythonw has no stdout for pytest)."""
    exe = sys.executable
    console = os.path.join(os.path.dirname(exe), "python.exe")
    return console if os.path.exists(console) else exe


def open_problem(root, slug, topics, mastery, open_slides, on_ready=None):
    """Open the LeetCode page now, then (once leetcode-py has made the folder) VS Code and the 373 slides."""
    webbrowser.open(url(slug))
    python = python_exe()

    def work():
        workspace(root, python)
        solution = generate(root, slug, python)
        if on_ready:
            on_ready(solution if os.path.exists(solution) else None)
    threading.Thread(target=work, daemon=True).start()
    hit = deck_373(topics, mastery)
    if hit and open_slides:
        open_slides(*hit)
    return hit

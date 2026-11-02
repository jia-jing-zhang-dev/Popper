"""Coding exercises: when practice needs code, Popper writes a ready-to-run folder and opens VS Code on it.

Claude puts the starter file in one fenced code block and tags the reply [[exercise: c|python|ocaml]].
Popper saves it under DATA_DIR/exercises/ with what's needed to run it (a Makefile for C, a VS Code build
task for every language, so Ctrl+Shift+B builds and runs), plus the task text as README.md.

C and OCaml run in WSL when it has the tools (the courses use Linux toolchains, and Windows' Smart App
Control blocks freshly built native compilers); Python runs with the Windows Python.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess

CODE_RE = re.compile(r"```[ \t]*([\w+#-]*)[ \t]*\r?\n(.*?)```", re.S)
FILES = {"c": "main.c", "python": "exercise.py", "ocaml": "exercise.ml"}
ALIASES = {"py": "python", "python3": "python", "ml": "ocaml", "h": "c"}

MAKEFILE = """CC = gcc
CFLAGS = -Wall -Wextra -g -std=c11

main: main.c
\t$(CC) $(CFLAGS) -o $@ $<

run: main
\t./main

clean:
\trm -f main

.PHONY: run clean
"""


def take_code(text):
    """(text without the first code block, (language, code) or None)."""
    m = CODE_RE.search(text or "")
    if not m:
        return text, None
    rest = re.sub(r"\n\s*\n\s*\n", "\n\n", text[:m.start()] + text[m.end():])
    return rest.strip(), (m.group(1).lower(), m.group(2))


def lang_of(tag, fence):
    lang = (tag or fence or "").strip().lower()
    lang = ALIASES.get(lang, lang)
    return lang if lang in FILES else None


def detect_tools():
    """What can run exercises here: {'c': 'wsl'|'gcc'|None, 'ocaml': 'wsl'|'ocaml'|None, 'python': path|None}.
    Slow (starts WSL), so call it off the Tk thread."""
    tools = {"python": shutil.which("python") or shutil.which("py"), "c": None, "ocaml": None}
    try:
        out = subprocess.run(["wsl", "-e", "sh", "-c", "for x in gcc make ocaml; do command -v $x; done"], capture_output=True, text=True,
                             timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    if "/gcc" in out and "/make" in out:
        tools["c"] = "wsl"
    elif shutil.which("gcc"):
        tools["c"] = "gcc"
    if "/ocaml" in out:
        tools["ocaml"] = "wsl"
    elif shutil.which("ocaml"):
        tools["ocaml"] = "ocaml"
    return tools


def describe(tools):
    """One line for Claude about what the exercises can use."""
    parts = []
    if tools.get("c"):
        parts.append("C (gcc and make in WSL)" if tools["c"] == "wsl" else "C (gcc, no make)")
    if tools.get("ocaml"):
        parts.append("OCaml" + (" (in WSL)" if tools["ocaml"] == "wsl" else ""))
    if tools.get("python"):
        parts.append("Python 3")
    return ", ".join(parts) or "none"


def task(lang, tools):
    """The VS Code build task that runs the exercise."""
    if lang == "c" and tools.get("c") == "wsl":
        run = {"type": "shell", "command": "wsl make run"}
    elif lang == "c":
        run = {"type": "shell", "command": "gcc -Wall -Wextra -g -std=c11 main.c -o main.exe; ./main.exe"}
    elif lang == "ocaml":
        run = {"type": "shell", "command": "wsl ocaml exercise.ml" if tools.get("ocaml") == "wsl"
               else "ocaml exercise.ml"}
    else:
        run = {"type": "process", "command": tools.get("python") or "python", "args": ["exercise.py"]}
    run.update({"label": "run exercise", "group": {"kind": "build", "isDefault": True},
                "problemMatcher": ["$gcc"] if lang == "c" else []})
    return {"version": "2.0.0", "tasks": [run]}


def slug(text, n=40):
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "exercise").strip("-")[:n].lower() or "exercise"


def make(root, course, topic, lang, code, readme, tools):
    """Write the exercise folder; returns (folder, main file)."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H%M")
    folder = os.path.join(root, f"{stamp} {slug(course, 12)} {slug(topic)}")
    os.makedirs(os.path.join(folder, ".vscode"), exist_ok=True)
    main = os.path.join(folder, FILES[lang])
    with open(main, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(code.rstrip() + "\n")
    if lang == "c":
        with open(os.path.join(folder, "Makefile"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(MAKEFILE)
    with open(os.path.join(folder, ".vscode", "tasks.json"), "w", encoding="utf-8") as fh:
        json.dump(task(lang, tools), fh, indent=2)
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {course}: {topic}\n\n{readme.strip()}\n\nRun it: Ctrl+Shift+B (the \"run exercise\" task).\n")
    return folder, main


def find_code():
    """VS Code's command-line launcher, or None."""
    path = shutil.which("code")
    if path:
        return path
    guess = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code", "bin", "code.cmd")
    return guess if os.path.exists(guess) else None


def open_in_vscode(folder, main):
    code = find_code()
    if not code:
        os.startfile(folder)  # no VS Code: at least show the files
        return False
    subprocess.Popen([code, folder, main], creationflags=subprocess.CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True

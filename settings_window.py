"""Settings window and the Start-with-Windows shortcut."""

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from i18n import UI_LANGUAGES, t
from languages import LANGUAGES, label, voices

STARTUP_LINK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                            "Word Popper.lnk")
SPEEDS = [("speed_slow", "-25%"), ("speed_relaxed", "-10%"), ("speed_normal", "+0%"), ("speed_fast", "+15%")]
SIZES = [("size_small", "small"), ("size_normal", "normal"), ("size_large", "large"), ("size_huge", "huge")]


def autostart_enabled():
    return os.path.exists(STARTUP_LINK)


def set_autostart(enabled, script):
    if not enabled:
        if os.path.exists(STARTUP_LINK):
            os.remove(STARTUP_LINK)
        return
    if getattr(sys, "frozen", False):  # packaged exe: the shortcut points straight at it
        target, args = sys.executable, ""
    else:
        target = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(target):
            target = sys.executable
        args = f'"{script}"'
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:WP_LINK);"
          "$s.TargetPath=$env:WP_TARGET; $s.Arguments=$env:WP_ARGS;"
          "$s.WorkingDirectory=$env:WP_DIR; $s.Description='Word Popper'; $s.Save()")
    env = dict(os.environ, WP_LINK=STARTUP_LINK, WP_TARGET=target, WP_ARGS=args,
               WP_DIR=os.path.dirname(script))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                   creationflags=subprocess.CREATE_NO_WINDOW, check=False)


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        s = app.settings
        top = self.top = tk.Toplevel(app.root)
        top.title(t("settings_title"))
        top.attributes("-topmost", True)
        top.resizable(False, False)
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)

        self.lang_codes = list(LANGUAGES)
        lang_labels = [label(c) for c in self.lang_codes]
        self.ui_codes = list(UI_LANGUAGES)

        self.ui_var = tk.StringVar(value=UI_LANGUAGES.get(s["ui_lang"], "English"))
        self.learn_var = tk.StringVar(value=label(s["learn"]))
        self.native_var = tk.StringVar(value=label(s["native"]))
        self.voice_var = tk.StringVar()
        self.speed_var = tk.StringVar(value=next((t(k) for k, v in SPEEDS if v == s["speed"]),
                                                 t("speed_relaxed")))
        self.size_var = tk.StringVar(value=next((t(k) for k, v in SIZES if v == s["text_size"]),
                                                t("size_normal")))
        self.trigger_var = tk.StringVar(value=s["trigger"])
        self.shots_var = tk.BooleanVar(value=s["screenshots"])
        self.library_var = tk.BooleanVar(value=s["library"])
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())

        def row(r, key, widget):
            ttk.Label(body, text=t(key)).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            widget.grid(row=r, column=1, sticky="we", pady=4)

        row(0, "set_ui_lang", ttk.Combobox(body, textvariable=self.ui_var, state="readonly",
                                           values=list(UI_LANGUAGES.values()), width=30))
        learn_box = ttk.Combobox(body, textvariable=self.learn_var, state="readonly",
                                 values=lang_labels, width=30)
        learn_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_voices())
        row(1, "set_learn", learn_box)
        row(2, "set_native", ttk.Combobox(body, textvariable=self.native_var, state="readonly",
                                          values=lang_labels, width=30))
        self.voice_box = ttk.Combobox(body, textvariable=self.voice_var, state="readonly", width=30)
        row(3, "set_voice", self.voice_box)
        row(4, "set_speed", ttk.Combobox(body, textvariable=self.speed_var, state="readonly",
                                         values=[t(k) for k, _ in SPEEDS], width=30))
        row(5, "set_text_size", ttk.Combobox(body, textvariable=self.size_var, state="readonly",
                                             values=[t(k) for k, _ in SIZES], width=30))

        ttk.Label(body, text=t("set_trigger")).grid(row=6, column=0, sticky="nw", pady=(10, 4))
        triggers = ttk.Frame(body)
        triggers.grid(row=6, column=1, sticky="w", pady=(10, 4))
        ttk.Radiobutton(triggers, text=t("trigger_ctrl_shift"), value="ctrl_shift",
                        variable=self.trigger_var).pack(anchor="w")
        ttk.Radiobutton(triggers, text=t("trigger_copy"), value="copy",
                        variable=self.trigger_var).pack(anchor="w")
        ttk.Checkbutton(body, text=t("set_screenshots"), variable=self.shots_var).grid(
            row=7, column=1, sticky="w", pady=(8, 2))
        ttk.Checkbutton(body, text=t("set_autostart"), variable=self.autostart_var).grid(
            row=8, column=1, sticky="w", pady=2)
        ttk.Checkbutton(body, text=t("set_library"), variable=self.library_var).grid(
            row=9, column=1, sticky="w", pady=2)

        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text=t("set_cancel"), command=top.destroy).pack(side="right")
        ttk.Button(buttons, text=t("set_save"), command=self.save).pack(side="right", padx=6)

        self.refresh_voices()
        top.bind("<Escape>", lambda e: top.destroy())
        top.lift()
        top.focus_force()

    def code_of(self, var):
        return self.lang_codes[[label(c) for c in self.lang_codes].index(var.get())]

    def refresh_voices(self):
        learn = self.code_of(self.learn_var)
        options = list(voices(learn))
        self.voice_box.configure(values=options)
        current = self.app.settings["voices"].get(learn)
        self.voice_var.set(current if current in options else options[0])

    def save(self):
        s = dict(self.app.settings)
        s["ui_lang"] = self.ui_codes[list(UI_LANGUAGES.values()).index(self.ui_var.get())]
        s["learn"] = self.code_of(self.learn_var)
        s["native"] = self.code_of(self.native_var)
        s["voices"] = dict(s["voices"], **{s["learn"]: self.voice_var.get()})
        s["speed"] = next(v for k, v in SPEEDS if t(k) == self.speed_var.get())
        s["text_size"] = next(v for k, v in SIZES if t(k) == self.size_var.get())
        s["trigger"] = self.trigger_var.get()
        s["screenshots"] = self.shots_var.get()
        s["library"] = self.library_var.get()
        if self.autostart_var.get() != autostart_enabled():
            set_autostart(self.autostart_var.get(), self.app.script_path)
        self.top.destroy()
        self.app.apply_settings(s)

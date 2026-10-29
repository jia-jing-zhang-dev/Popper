# Popper (泡泡)

Formerly Word Popper. The code still uses the old name in a few places on purpose: `word_popper.py`,
the `WORD_POPPER_HOME` variable, the single-instance mutex and the packaged app's data folder
`%APPDATA%\Word Popper`. Don't rename those. Renaming them would split the owner's data and
startup setup.


A small Windows study companion (Python + Tkinter) built around a floating card in the corner
of the screen. Select a word anywhere and tap Ctrl+Shift to get a translation and hear it; plus a
word list with spaced-repetition review, library check-in, goals and to-dos with timers, and a
day-by-day journal. Windows 10/11 only. The UI is bilingual (English / 简体中文).

The owner is a student who uses it daily. Their running copy is this folder, started by a shortcut
in the Windows Startup folder.

## Running

```bat
setup.bat                                   :: first time: venv + requirements + start
run.bat                                     :: start (pythonw, no console)
.venv\Scripts\python word_popper.py         :: start with a console, to see tracebacks
```

- Use `.venv\Scripts\python -m pip`. `pip.exe` is blocked on the owner's machine.
- Only one instance runs at a time (a named mutex). To load new code, stop the running copy and start
  it again. Match **only `pythonw.exe`** processes whose command line contains `word_popper.py`.
  A broader match also kills the shell running the command, because its command line contains the
  same text. Then start `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Popper.lnk`
  (`rename_startup_link()` moves an old `Word Popper.lnk` over on start).
- Settings changed by editing `settings.json` only take effect if the app is stopped first,
  otherwise it writes its in-memory settings back over the file.

## Architecture: the card + features

The card and word lookup (Ctrl+Shift, screenshots, translation, speech) are the core in
`word_popper.py` and are always on. Everything else is a **feature** in `features/`: a `Feature`
subclass (`features/base.py`) that can add right-click menu items (`menu_items`), journal sections
(`journal_sections`), timers (`every`) and windows (`show`/`window`). `features/__init__.py`
lists them in menu/Settings/journal order. Settings → Features turns each on or off
(`settings["features"][id]`, default `Feature.default_on`). Features reach each other through
`app.feature("id")`. Shared data stores are on the app: `app.vocab`, `app.library`, `app.todos`,
`app.journal`.

### Adding a feature

1. Copy `features/_template.py` and pick a permanent `id`.
2. Put its UI strings in both languages in `i18n.py`, including its `name_key`.
3. Give its data its own table in `vocab.db`, created and upgraded in its store's constructor.
4. Add the class to `FEATURES`. It then appears in the menu, in Settings and in the journal.
5. Test it in-process in both languages, then commit and push.

## Layout

| File | What's in it |
| --- | --- |
| `word_popper.py` | `App`: the card, Ctrl+Shift hotkey, clipboard and screenshot handling, lookup flow, settings load/save, loading features and building the menu from them |
| `features/` | One module per feature (`review`, `todos`, `library`, `journal`) plus `base.py` and `_template.py` |
| `lookup.py` | Translation (Google, unofficial endpoint), Youdao EN↔ZH dictionary and IPA, Windows OCR |
| `speech.py` | `Speaker`: Edge TTS to cached mp3, played through MCI, SAPI fallback |
| `languages.py` | Supported languages, voices, OCR tags |
| `i18n.py` | Every UI string, `t(key, **kw)` |
| `vocab.py` | Word list (`Vocab`), review flash cards, word-list window |
| `library.py` | Library check-in (`LibraryLog`), goals and dated to-dos with stopwatches (`TodoList`), `DatePicker`, `Celebration`, `TodoWindow`, `LibraryWindow` |
| `focus.py` | Study-time detection: samples the foreground window and idle time every 5 s into per-minute buckets keyed by program/site; default rules plus the owner's overrides decide what counts |
| `journal.py` | Journal store and window; a page is the sections of every feature that's on |
| `settings_window.py` | Settings UI, Start-with-Windows shortcut |
| `packaging/` | PyInstaller build of a standalone exe (see caveats) |
| `demo/` | Scripts that recorded `docs/demo.mp4` / `docs/demo.gif` |

## Data

- `settings.json` and `vocab.db` sit next to the script (`%APPDATA%\Word Popper` for the packaged exe).
  Set `WORD_POPPER_HOME` to point them somewhere else; every test does this.
- `vocab.db` holds every table: `words`, `library_sessions`, `todos`, `goals`, `journal`.
  Study time adds `focus_activity` and `focus_rules`. All stores share **one** sqlite connection (`app.vocab.db`). Two connections locked each other.
- Schema changes go in the store's constructor as `CREATE TABLE IF NOT EXISTS` plus `ALTER TABLE ...
  ADD COLUMN` guarded by `PRAGMA table_info`. The owner's real data must upgrade in place. Never drop
  or rewrite their tables.
- New settings get a default in `load_settings()` so old `settings.json` files keep working.

## Conventions

- **Strings:** never hard-code UI text. Add the key to both `"en"` and `"zh"` in `i18n.py`. Check that
  the two languages have the same keys:
  `python -c "import i18n; print(set(i18n.STRINGS['en']) ^ set(i18n.STRINGS['zh']))"` → `set()`.
- **Sizes:** fonts go through `app.font(family, size)` and pixel sizes through `app.scale`, so the
  Text size setting and display scaling both apply.
- **Look:** dark windows use the palette in `library.py` / `vocab.py` (`BG`, `PANEL`, `FG`, `FG_DIM`,
  `ACCENT`, `GOOD`, `LATE`).
- **Comments:** English comments explain *why*, at the density of the surrounding code.

## Windows/Tk pitfalls already hit

- ttk `Combobox` and `Treeview` stay white on Windows. In dark windows use a `tk.Label` button with a
  `tk.Menu`, or a read-only `tk.Text` with tags.
- On the owner's machine, an `Entry` that moves after layout (because a list above it grew) stays drawn
  at its old position. Keep inputs **above** the lists that change.
- Colour emoji such as 📚 render as broken glyphs in Tk. 🔊 works. Prefer text or Segoe UI Symbol
  characters (☐ ☑ ▶ ⏸ ✦ ✓ ×).
- Smart App Control is on. A freshly built unsigned PyInstaller exe is **blocked** and can't be run
  here. Running from source with the signed python works.
- The screenshot (Win+Shift+S) path only reads small snips (`MAX_SNIP_HEIGHT`) and drops junk OCR.
  Bigger screenshots are usually taken for other reasons.

## Testing

- Test **in-process**: a script that sets `WORD_POPPER_HOME` to a temp dir, seeds data, creates
  `word_popper.App()`, drives it with `root.after(...)` steps, and screenshots windows with
  `PIL.ImageGrab` (the process is DPI-aware). Add `root.after(15000, root.destroy)` so a failed step
  can't hang the run. Look at the screenshots. Most UI bugs here were visual.
- Test both `ui_lang` values when you change UI text.
- Tk refuses `event_generate("<Double-1>")`. To simulate a double-click on a `Text` tag, send `<Motion>`
  first, then two `<ButtonPress-1>`/`<ButtonRelease-1>` pairs with `time=` values about 100 ms apart.
- Don't drive the owner's real mouse or keyboard (synthetic input, Snipping Tool) without asking. It
  interrupts their work, and they have stopped such runs before.

## Git

- Commit after each finished feature (one feature per commit, tested first), then push.
- Author identity is `jia-jing-zhang-dev` (global git config). The remote is
  `jia-jing-zhang-dev/Popper` (renamed from `Real-Time-Translate-MCP-`), which is **public**: everything
  pushed is visible to anyone. Never commit personal data, keys or tokens.
- `settings.json`, `vocab.db`, `.venv/`, `build/`, `dist/`, `demo/_work/` are ignored. Keep it that way;
  `vocab.db` is the owner's personal data.

## Not ready for distribution

Translation, the Youdao dictionary and Edge TTS are unofficial or non-commercial endpoints.
Commercial use needs licensed APIs (or bring-your-own-key). The exe also needs code signing before
it runs on machines with Smart App Control.

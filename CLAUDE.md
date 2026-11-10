# Desktop Study Cats

Formerly Popper, and before that Word Popper (renamed to Desktop Study Cats on 2026-11-08; the first cat used to be called Paopao; now each has its own name: its coat's default (`COAT_NAMES`, e.g. Tiger) or what the owner typed in the Cats window (`pet_names`); strings that name the cat use `{cat}`, filled by `i18n.t` from `i18n.CAT`, which `PetFeature.update_name` keeps current). The code still uses the old names in a few places on purpose: the local folder `word-popper`, `word_popper.py`,
the `WORD_POPPER_HOME` variable, the single-instance mutex and the packaged app's data folder
`%APPDATA%\Word Popper`. Don't rename those. Renaming them would split the owner's data and
startup setup.


A small Windows study companion (Python + Tkinter) built around a floating card in the corner
of the screen. Select a word anywhere and tap Ctrl+Shift to get a translation and hear it; plus a
word list with spaced-repetition review, library check-in, goals and to-dos with timers, and a
day-by-day journal. Windows 10/11 only. The UI is bilingual (English / Simplified Chinese).

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
  same text. Then start `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Desktop Study Cats.lnk`
  (`rename_startup_link()` moves an old `Word Popper.lnk` or `Popper.lnk` over on start).
- Launching again while it runs **closes** the running copy (it sets the named event `PopperQuit`), so the
  desktop icon `Desktop Study Cats.lnk` (made once on first start, an old `Popper.lnk` is replaced; `make_desktop_icon`; `paw.ico` in DATA_DIR, a cat's paw drawn by `appicon.py`; it is also the window icon and the packaged exe's icon)
  opens and closes the app. Starting a `.lnk` with `Start-Process` from Claude's shell doesn't survive; use
  `os.startfile`.
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
| `buddy.py` | Study buddy: `ClaudeBridge` runs `claude -p` (one job at a time, on a worker thread, results back via `app.ui_q` `"call"`), `BuddyStore` (messages, interests, one Claude session per day), chat window |
| `features/usage.py` | Claude plan usage badge: parses `claude -p /usage` (local, no quota) every 5 min; `app.set_badge` puts it on the card's top row |
| `features/pet.py`, `cat_skins.py` | Desktop cats: one transparent window (`-transparentcolor`) per cat showing frames from `assets/cats/<coat>_<type>/` (WebP renders of a rigged CC-BY model, see `tools/cat_render/`; `meta.json` has the canvas and head/ear anchors per frame). `Cat` runs one action at a time (sit with blinks, groom, yawn, look, nap, walk, run) and picks the next at random, calmer while `idle_seconds()` is low; `Director` brings the two together (boop, groom, chase, cuddle). Side frames face left and are mirrored. Cat 0 (the first cat) sets `app.anchor`/`app.card_drag` (`sync_loop` lifts the card above the cats and their things every second), shows the card's mood, wears the bond accessory (`bond.wear_at` at the frame's head anchor) and stays near `pet_x`. Settings: `pet_skins`, `pet_names`, `pet_two`, `pet_x`, `pet2_x`, `pet_ground`. `SkinWindow` names each cat and picks its coat and body; its swap button calls `PetFeature.swap_cats`, which swaps every per-cat setting (skins, names, `pet_x`/`pet2_x`, hunger/thirst) so the carrier is always cat 0. Clicking a cat (`Cat.answer_you`) makes it face you and meow; cat 0's click also calls `app.card_clicked`. `Director` meets every 15-45 s when you're away and 50-120 s while you work (calm games only then). Petting: `Cat.on_hover` counts back-and-forth mouse turns over a cat (no button held); `petted`: a cat busy in a pose of its own (lying, sleeping, in the bed, eating, drinking, scratching) keeps it and just gets `hearts1/2` marks; otherwise it mostly turns to face you (sit/blink/talk2), sometimes rolls over or rubs your hand; after `MELT_AFTER` s of stroking it `melt`s down and lies there; `after_petting` blinks or rolls. Marks (?, !, Zz, hearts) are drawn by `frame_image` above the frame's head anchor, mirrored with it |
| `furniture.py` | The cats' things on the floor (food bowl full/empty, water bowl, scratching post, bed with a separate front-rim window kept above a cat lying in it): still, see-through windows dragged along the floor, spots saved in `pet_items`, put away/set out from the menu (`pet_furniture`); frames in `assets/props/`. Cats line up by each frame's frontmost point (`Cat.front`, `x_for_front`: the nose tip when eating/drinking, the paw tips when scratching), not by the ear anchors, so mouths land in bowls and paws on the post for every body type; the eat/drink poses keep the mouth below the bowl's rim (`EAT_NECK`, `DRINK_NECK` in `tools/cat_render/catpose.py`). Needs (`pet_needs`: bowl level, hunger and thirst per cat, rising with time even while closed) drive `Cat.look_after_itself` (`go_drink`, `go_eat`, `beg`); `PetFeature.feed` (right-click menu, costs a pomodoro meal) fills the bowl and both cats eat from either side; naps go to the bed (`nap_in_bed`, raised by `elev`), `Director.cuddle` uses it, `Director.rub`, `go_scratch`, tail swish while sitting, `startle` arches at a fast toy |
| `toys.py` | Cat toys (yarn ball, bell ball): a see-through window each with simple physics (gravity, bounce, constant rolling friction, `speed_to_travel` for a roll of a given length), dragged and thrown with the mouse; frames in `assets/toys/` at the cats' scale. `PetFeature.drop_toy`/`put_toys_away` (right-click menu, `pet_toys` setting); `Cat.play` (approach so the nose meets the toy, crouch, maybe pounce, swat, kick); `Director.pingpong`/`yarn_race`. Play poses (crouch, pounce, bat1/2, stretch, roll1/2) only run when the assets have them (`can_play`) |
| `features/pomodoro.py` | Pomodoro: focus then break (`LENGTHS`, `pomo_lengths` from Settings; `LONG_BREAK` after every `LONG_EVERY`th of the day), state in `settings["pomo"]` so it survives a restart, no countdown on purpose (the owner asked): `app.set_badge("pomo")` shows today's rounds as dots, the current one a filling moon (`dots`, `PHASES`), and a click says the round and roughly how far along (`where`); the menu names the round of the day, never minutes left; the card's notes never give orders either (the owner asked): the cats hint instead (`pomo_*` strings: curls up quietly, smells dinner, tummy rumbling), and when a break ends `hungry_hint` sends a free cat (the one without the card first) to beg at the empty bowl; finished ones in the `pomodoros` table (journal section). Each finished pomodoro adds a meal (`pet_meals`, max `MAX_MEALS`); while this feature is on, `PetFeature.feed` spends one meal per bowlful (the menu item is greyed out without one) and the done notice's click feeds the cats |
| `report.py`, `features/report.py` | Study reports by email. `report.collect` gathers a range of days (focus_activity by category and hour, first/last study minute, words added, tasks/goals done, pomodoros, library, reflections, deadlines within 14 days); `daily`/`period` build (subject, inline-styled HTML for mail clients, plain summary, highlights). Highlights compare only with the owner's own past days. `ReportFeature`: today's report at shutdown after `DAY_DONE_HOUR` (Tk turns `WM_QUERYENDSESSION` into the `WM_SAVE_YOURSELF` protocol; `ShutdownBlockReasonCreate` says why it waits), otherwise `catch_up` every 10 min (yesterday after `NEW_DAY_HOUR`, last week on Monday, last month on the 1st). Each report goes out once and is never resent (the owner asked; an earlier resend rule looped because two study totals disagreed, so `report.split` is the one way to count). The study buddy's bridge writes a note (`NOTE_SYSTEM`); the shutdown report uses one prepared after `NOTE_HOUR`. Sent from the owner's Gmail over SMTP SSL; addresses in settings (`report_to`, `report_from`, never in code: the repo is public), the app password in Windows Credential Manager (`save_password`, target `CRED_TARGET`; tests must patch it). `report_sent` remembers what went out. Test with a fake `smtplib.SMTP_SSL` and a fake `bridge.ask`; simulate shutdown with `PostMessageW(WM_QUERYENDSESSION)` (`SendMessageW` from a Tk callback crashes Python) |
| `bond.py`, `features/bond.py` | The cat's bond: `BondStore` (`bond_points`, one row per `(source, ref)`) collects ♥ from other features' tables on each `sync` (done tasks/goals, library visits, study time per day) plus word reviews via `award` in `Vocab.grade`; daily caps for words and study time; never decreases, no streaks. Levels unlock a nickname (in the buddy's context) and accessories `wear_at` draws on the first cat's head, which also grows a little (`pet_style`, `Cat.restyle`); `LevelUp` card, `BondWindow` |
| `mascot.py` | The bubble on the card, drawn with PIL per mood (happy, blink, thinking, talking, worried, celebrate, sleepy); `app.mood()` picks it, `app.set_mood(mood, seconds)` shows one for a while |
| `focus.py` | Study-time detection: samples the foreground window and idle time every 5 s into per-minute buckets keyed by program/site; default rules plus the owner's overrides decide what counts |
| `journal.py` | Journal store and window; a page is the sections of every feature that's on |
| `settings_window.py` | Settings UI, Start-with-Windows shortcut |
| `packaging/` | PyInstaller build of a standalone exe (see caveats) |
| `demo/` | `record_cats.py` records `docs/demo.gif` and the `docs/*.png` stills in-process: a throw-away home with made-up data, Windows' default wallpaper and shell icons (`desktop_look.py`), a fresh-profile Edge window on `paper.html` (an example paper, served as `lab.example`), a drawn cursor, captions burnt in by ffmpeg. It never touches the real mouse or keyboard, and `only_demo_on_screen` refuses to film (and keeps checking every 2 s) if anything of the owner's is in the shot. The translation is fetched once before filming (the free endpoint returns 429 after heavy testing). Stop the owner's copy first: its cats would walk into the shot |

## Study buddy and Claude

- It calls the **Claude Code CLI** (`claude -p ... --output-format json`), so it runs on the owner's
  Claude subscription login, not an API key. If replies fail with an auth error, the CLI's login has
  expired. The owner runs `claude auth login` in a terminal; never enter credentials for them.
- The CLI gets only `--tools Read,Glob,Grep` (no `--add-dir`: it reads nothing beyond `DATA_DIR/buddy`),
  `--strict-mcp-config`, `--permission-prompts none`, and the persona from `PERSONA`. Keep it read-only.
- It only chats. It used to quiz the owner from their lecture slides (a mastery checklist, past exams, coding
  exercises) and run a LeetCode plan; the owner had all of that removed on 2026-11-08 because it didn't work
  well for them. Don't bring it back unasked.
- Unprompted messages: a good morning with deadline countdowns from open goals, an evening nudge after 21:00
  if under 30 min of study, and once a day after 14:00 something new from `buddy_interests` (a reply's
  `[[interest: ...]]` tag, read by `split_tags`, which also strips Markdown and emoji that Tk shows badly).
- Academic content is always English; casual chat follows `ui_lang`.
- The chat draws each reply as a card (`ChatWindow.buddy_card`, CustomTkinter widgets embedded in a read-only
  `tk.Text` so it scrolls like a page): a line ending in "?" in bold, 4-space lines as a code block, the
  student's messages as right-aligned bubbles. CTk font sizes are pixels at 96 dpi: use `cfont`.
- Every real call spends the owner's quota and takes 7-30 s. Test with a fake `bridge.ask` that queues a
  canned reply, and make real calls only for a final check.

## Data

- `settings.json` and `vocab.db` sit next to the script (`%APPDATA%\Word Popper` for the packaged exe).
  Set `WORD_POPPER_HOME` to point them somewhere else; every test does this.
- `vocab.db` holds every table: `words`, `library_sessions`, `todos`, `goals`, `journal`.
  Study time adds `focus_activity` and `focus_rules`; the buddy adds `buddy_messages`,
  `buddy_interests`, `buddy_sessions`. The cat's bond adds `bond_points`; pomodoros add `pomodoros`. All stores share **one** sqlite connection (`app.vocab.db`). Two connections locked each other.
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
- Before restarting the owner's copy, also start the app with the owner's own kind of settings (study buddy on,
  custom cat names, toys and needs saved): `.venv\Scripts\python word_popper.py` for ~20 s and read the console.
  A fresh temp setup missed a start-up crash (a feature refreshed the card before the buddy had started).
  Features start in `FEATURES` order, so `start()` must not reach into features listed after it.
- Tk refuses `event_generate("<Double-1>")`. To simulate a double-click on a `Text` tag, send `<Motion>`
  first, then two `<ButtonPress-1>`/`<ButtonRelease-1>` pairs with `time=` values about 100 ms apart.
- Don't drive the owner's real mouse or keyboard (synthetic input, Snipping Tool) without asking. It
  interrupts their work, and they have stopped such runs before.

## Git

- Commit after each finished feature (one feature per commit, tested first), then push.
- Author identity is `jia-jing-zhang-dev` (global git config). The remote is
  `jia-jing-zhang-dev/desktop-study-cats` (renamed from `Popper`, before that `Real-Time-Translate-MCP-`), which is **public**: everything
  pushed is visible to anyone. Never commit personal data, keys or tokens.
- Before every commit: if the change creates new files or folders (data, caches, working dirs, logs),
  add them to `.gitignore` in the same commit, then read `git status --short` (and `--ignored` when new
  files appeared) and the diff for personal content: emails, tokens, the owner's chats, journal or study
  data, screenshots of their screen, local paths. Run Claude Code (`claude -p`) in `DATA_DIR/buddy`, never
  in the repo.
- `settings.json`, `vocab.db`, `.venv/`, `build/`, `dist/`, `demo/_work/` are ignored. Keep it that way;
  `vocab.db` is the owner's personal data.

## Not ready for distribution

Translation, the Youdao dictionary and Edge TTS are unofficial or non-commercial endpoints.
Commercial use needs licensed APIs (or bring-your-own-key). The exe also needs code signing before
it runs on machines with Smart App Control.

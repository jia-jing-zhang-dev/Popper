"""Cut the promo (docs/promo.mp4) and the README GIF (docs/demo.gif) from the two reels record_cats.py films.

    .venv\\Scripts\\python demo\\record_cats.py                      (the cats reel  -> demo/_work/reel_cats.mp4)
    set DEMO_REEL=study && .venv\\Scripts\\python demo\\record_cats.py (the study reel -> demo/_work/study_raw.mp4)
    .venv\\Scripts\\python demo\\make_promo.py

Shaped like a product promo: a hook in the first seconds, the name, then one feature per section (a numbered
caption, a punch-in on the detail that matters), and an end card with where to get it. The title and end cards
are drawn here with PIL from the app's own paw icon and cat frames, over the same Windows wallpaper.
"""

import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work")
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import imageio_ffmpeg  # noqa: E402

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1600, 820            # the reels' size
FPS = 20
CATS = os.path.join(WORK, "reel_cats.mp4")
STUDY = os.path.join(WORK, "study_raw.mp4")
FONT = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_REG = r"C:\Windows\Fonts\segoeui.ttf"
INK, ACCENT = "#1f2430", "#7cc4ff"
REPO = "github.com/jia-jing-zhang-dev/desktop-study-cats"

# (caption, number, [(reel, start, end, zoom)]) ; zoom = (centre x, centre y, factor) or None
SECTIONS = [
    ("Two study buddies live on your desktop", "", [(CATS, 12.6, 16.2, (900, 600, 1.35))]),
    ("TITLE", "", []),
    ("Select a word in any app, tap Ctrl+Shift", "01", [(CATS, 0.8, 3.2, None), (CATS, 3.2, 6.6, (1180, 540, 1.9))]),
    ("12 languages, either direction", "02", [(STUDY, 1.2, 5.8, None), (STUDY, 8.0, 12.4, (560, 540, 1.7))]),
    ("Counts the time you actually study", "03", [(STUDY, 13.6, 16.8, None), (STUDY, 16.8, 20.4, (800, 240, 1.8))]),
    ("A study report in your inbox, every evening", "04", [(STUDY, 22.6, 30.6, None)]),
    ("Pomodoros earn the cats their dinner", "05", [(CATS, 35.4, 39.4, None), (CATS, 43.8, 47.4, None),
                                                    (CATS, 47.4, 51.0, (380, 640, 1.7))]),
    ("Studying levels up your bond", "06", [(STUDY, 33.6, 37.4, None), (STUDY, 37.6, 41.6, (780, 260, 1.6)),
                                            (STUDY, 42.4, 46.0, (1300, 600, 2.2))]),
    ("Pet them. They answer.", "07", [(CATS, 21.8, 23.4, None), (CATS, 23.4, 27.0, (640, 600, 1.7)),
                                       (CATS, 29.0, 31.4, None)]),
    ("END", "", []),
]
FADE = 0.3
CARD_SECONDS = {"TITLE": 2.8, "END": 4.0}


def font(size, bold=True):
    return ImageFont.truetype(FONT if bold else FONT_REG, size)


def backdrop():
    """The same wallpaper the reels were filmed on, blurred and darkened, for the cards."""
    import desktop_look
    wall = desktop_look.cover(Image.open(desktop_look.WALLPAPER).convert("RGB"), (W, H))
    wall = wall.filter(ImageFilter.GaussianBlur(18))
    shade = Image.new("RGB", (W, H), "#0d1220")
    return Image.blend(wall, shade, 0.55).convert("RGBA")


def cat_frame(skin, frame, height):
    im = Image.open(os.path.join(ROOT, "assets", "cats", skin, f"{frame}.webp")).convert("RGBA")
    im = im.crop(im.getbbox())
    k = height / im.height
    return im.resize((round(im.width * k), height), Image.LANCZOS)


def centred(d, y, text, f, fill):
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def title_card(path):
    import appicon
    im = backdrop()
    paw = appicon.paw(150).convert("RGBA")
    im.alpha_composite(paw, ((W - 150) // 2, 120))
    d = ImageDraw.Draw(im)
    centred(d, 300, "Desktop Study Cats", font(86), "#ffffff")
    centred(d, 420, "Two cats keep you company while you study", font(34, bold=False), "#dfe7f3")
    centred(d, 480, "Word lookup · study time · daily reports · pomodoros", font(28, bold=False), ACCENT)
    a, b = cat_frame("B_adult", "sit", 210), cat_frame("G_kitten", "sit", 150)
    im.alpha_composite(a, (W // 2 - a.width - 30, H - a.height - 20))
    im.alpha_composite(b, (W // 2 + 40, H - b.height - 20))
    im.convert("RGB").save(path)


def end_card(path):
    import appicon
    im = backdrop()
    paw = appicon.paw(120).convert("RGBA")
    im.alpha_composite(paw, ((W - 120) // 2, 110))
    d = ImageDraw.Draw(im)
    centred(d, 250, "Desktop Study Cats", font(72), "#ffffff")
    centred(d, 350, "Free and open source · Windows 10/11", font(32, bold=False), "#dfe7f3")
    pill = font(34)
    w = d.textlength(REPO, font=pill)
    x0, y0 = (W - w) / 2 - 28, 430
    d.rounded_rectangle((x0, y0, x0 + w + 56, y0 + 70), radius=35, fill=ACCENT)
    d.text((x0 + 28, y0 + 12), REPO, font=pill, fill=INK)
    a, b = cat_frame("B_adult", "blink", 200), cat_frame("G_kitten", "sit", 140)
    im.alpha_composite(a, (W // 2 - a.width - 30, H - a.height - 20))
    im.alpha_composite(b, (W // 2 + 40, H - b.height - 20))
    im.convert("RGB").save(path)


def esc(text):
    return text.replace("\\", "").replace("'", "\u2019").replace(":", "\\:").replace(",", "\\,")


def caption(text, number):
    """The section's one line in a pill near the top, its number first."""
    f = FONT.replace("\\", "/").replace(":", r"\:")
    line = f"{number}  ·  {text}" if number else text
    return (f"drawtext=fontfile='{f}':text='{esc(line)}':fontsize=34:fontcolor=white:box=1:boxcolor=0x1f2430@0.92:"
            f"boxborderw=18:x=(w-tw)/2:y=22")


def build(out_mp4, out_gif=None, gif_width=640, gif_fps=8):
    title, end = os.path.join(WORK, "card_title.png"), os.path.join(WORK, "card_end.png")
    title_card(title)
    end_card(end)
    inputs, chains, labels, lengths = [], [], [], []
    sections = [sec for sec in SECTIONS if all(os.path.exists(c[0]) for c in sec[2])]   # a reel not filmed yet: skip
    for si, (text, number, clips) in enumerate(sections):
        if text in CARD_SECONDS:
            inputs += ["-loop", "1", "-t", str(CARD_SECONDS[text]), "-framerate", str(FPS), "-i", title if text == "TITLE" else end]
            inputs_index = sum(1 for a in inputs if a == "-i") - 1
            chains.append(f"[{inputs_index}:v]fps={FPS},scale={W}:{H},format=yuv420p,setsar=1,fps={FPS},settb=1/{FPS}[s{si}]")
            lengths.append(CARD_SECONDS[text])
            labels.append(f"s{si}")
            continue
        parts = []
        for ci, (src, t0, t1, zoom) in enumerate(clips):
            inputs += ["-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}", "-i", src]
            inputs_index = sum(1 for a in inputs if a == "-i") - 1
            f = f"[{inputs_index}:v]fps={FPS},setpts=PTS-STARTPTS"
            if zoom:
                cx, cy, k = zoom
                cw, ch = int(W / k), int(H / k)
                x, y = min(max(0, int(cx - cw / 2)), W - cw), min(max(0, int(cy - ch / 2)), H - ch)
                f += f",crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos"
            f += f",format=yuv420p,setsar=1[c{si}_{ci}]"
            chains.append(f)
            parts.append(f"[c{si}_{ci}]")
        chains.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0," + caption(text, number) + f",fps={FPS},settb=1/{FPS}[s{si}]")
        lengths.append(sum(t1 - t0 for _, t0, t1, _ in clips))
        labels.append(f"s{si}")
    # crossfades between sections
    cur, offset = labels[0], lengths[0]
    for i in range(1, len(labels)):
        nxt = f"x{i}"
        offset -= FADE
        chains.append(f"[{cur}][{labels[i]}]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[{nxt}]")
        cur, offset = nxt, offset + lengths[i]
    chains.append(f"[{cur}]null[out]")
    graph = os.path.join(WORK, "promo_graph.txt")
    open(graph, "w", encoding="utf-8").write(";\n".join(chains))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex_script", graph, "-map", "[out]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    out_mp4], check=True)
    print("promo", out_mp4, round(offset, 1), "s", flush=True)
    if out_gif:
        pal = os.path.join(WORK, "promo_palette.png")
        vf = f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", out_mp4, "-vf", vf + ",palettegen=max_colors=112:stats_mode=diff",
                        pal], check=True)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", out_mp4, "-i", pal, "-lavfi",
                        vf + " [x]; [x][1:v] paletteuse=dither=sierra2_4a:diff_mode=rectangle", out_gif], check=True)
        print("gif", out_gif, os.path.getsize(out_gif) // 1024, "KB", flush=True)


if __name__ == "__main__":
    os.chdir(ROOT)
    build(os.path.join(DOCS, "promo.mp4"), os.path.join(DOCS, "demo.gif"), gif_width=540, gif_fps=6)

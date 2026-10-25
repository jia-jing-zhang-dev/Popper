"""Turn the raw recordings from record.py into docs/demo.mp4 and docs/demo.gif.

Crops each segment to 16:9, burns in captions and key-press badges, rebuilds the audio from
Word Popper's playback log (so every word is heard exactly when it was spoken), and adds a
title and end card.
"""

import json
import os
import re
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work")
DOCS = os.path.join(ROOT, "docs")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

W, H, FPS = 1920, 1080, 30
CROP = "crop=2560:1440:0:0"   # drop the bottom rows where the taskbar can flash in
SEGMENTS = ["1_english", "2_spanish", "3_review"]
REPO = "github.com/jia-jing-zhang-dev/Real-Time-Translate-MCP-"

PAPER = (247, 242, 232)
INK = (43, 38, 32)
MUTED = (138, 127, 112)
FONT_DIR = r"C:\Windows\Fonts"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


CAPTION_FONT = font("seguisb.ttf", 40)
KEY_FONT = font("seguisb.ttf", 34)


def run(args, **kw):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **kw)


def start_time(path):
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    return float(re.search(r"start: ([\d.]+)", out).group(1))


# ---------------------------------------------------------------- overlays

def fade(t, start, dur, edge=0.25):
    """0..1 opacity of an overlay shown from `start` for `dur` seconds."""
    if t < start or t > start + dur:
        return 0.0
    return max(0.0, min(1.0, (t - start) / edge, (start + dur - t) / edge))


def draw_caption(img, text, alpha):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    tw = d.textlength(text, font=CAPTION_FONT)
    x, y = (W - tw) / 2, H - 120
    d.rounded_rectangle((x - 34, y - 18, x + tw + 34, y + 62), radius=40,
                        fill=(20, 24, 33, int(225 * alpha)))
    d.text((x, y), text, font=CAPTION_FONT, fill=(255, 255, 255, int(255 * alpha)))
    img.alpha_composite(layer)


def draw_keys(img, text, alpha):
    keys = [k.strip() for k in text.split("+")]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    widths = [d.textlength(k, font=KEY_FONT) + 44 for k in keys]
    plus = d.textlength("+", font=KEY_FONT) + 28
    total = sum(widths) + plus * (len(keys) - 1)
    x, y = (W - total) / 2, H - 230
    for i, (k, kw) in enumerate(zip(keys, widths)):
        d.rounded_rectangle((x, y + 6, x + kw, y + 74), radius=14, fill=(160, 150, 135, int(255 * alpha)))
        d.rounded_rectangle((x, y, x + kw, y + 66), radius=14, fill=(255, 255, 255, int(250 * alpha)),
                            outline=(200, 190, 175, int(255 * alpha)), width=2)
        d.text((x + 22, y + 10), k, font=KEY_FONT, fill=(*INK, int(255 * alpha)))
        x += kw
        if i < len(keys) - 1:
            d.text((x + 14, y + 10), "+", font=KEY_FONT, fill=(*INK, int(255 * alpha)))
            x += plus
    img.alpha_composite(layer)


# ---------------------------------------------------------------- segments

def process_segment(name, marks, events):
    src = os.path.join(WORK, f"{name}.mkv")
    t0 = start_time(src)
    seg_marks = [dict(m, t=m["t"] - t0) for m in marks if m["t"] >= t0 - 1]
    silent = os.path.join(WORK, f"{name}_video.mp4")

    decoder = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", src,
         "-vf", f"{CROP},scale={W}:{H}:flags=lanczos,fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)
    encoder = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    frame_bytes = W * H * 3
    n = 0
    while True:
        raw = decoder.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        t = n / FPS
        img = Image.frombytes("RGB", (W, H), raw).convert("RGBA")
        for m in seg_marks:
            if m["kind"] == "caption":
                a = fade(t, m["t"], m["dur"])
                if a:
                    draw_caption(img, m["text"], a)
            elif m["kind"] == "keys":
                a = fade(t, m["t"], 1.5, edge=0.15)
                if a:
                    draw_keys(img, m["text"], a)
        encoder.stdin.write(img.convert("RGB").tobytes())
        n += 1
    encoder.stdin.close()
    encoder.wait()
    decoder.wait()
    duration = n / FPS

    # Audio: every word exactly when Word Popper started playing it
    clips = [(t - t0, path) for t, path in events if 0 <= t - t0 < duration]
    out = os.path.join(WORK, f"{name}.mp4")
    inputs, filters = ["-i", silent], []
    for i, (offset, path) in enumerate(clips):
        inputs += ["-i", path]
        ms = int(offset * 1000)
        filters.append(f"[{i + 1}:a]adelay={ms}:all=1,aresample=48000[a{i}]")
    if clips:
        mix = "".join(f"[a{i}]" for i in range(len(clips)))
        filters.append(f"{mix}amix=inputs={len(clips)}:normalize=0,apad[mixed]")
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        filters.append("[1:a]anull[mixed]")
    filters.append(f"[mixed]afade=t=in:d=0.3,afade=t=out:st={duration - 0.4:.2f}:d=0.4[aout]")
    filters.append(f"[0:v]fade=t=in:d=0.35,fade=t=out:st={duration - 0.4:.2f}:d=0.4[vout]")
    run([*inputs, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
         "-t", f"{duration:.2f}", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", out])
    return out


# ---------------------------------------------------------------- cards

def card(name, lines, seconds):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    total = sum(h for _, _, h, _ in lines)
    y = (H - total) / 2
    for text, fnt, height, color in lines:
        d.text(((W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=color)
        y += height
    png = os.path.join(WORK, f"{name}.png")
    img.save(png)
    out = os.path.join(WORK, f"{name}.mp4")
    run(["-loop", "1", "-i", png, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"fps={FPS},format=yuv420p,fade=t=in:d=0.5,fade=t=out:st={seconds - 0.6}:d=0.6",
         "-t", str(seconds), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-ac", "2", "-shortest", out])
    return out


def main():
    os.makedirs(DOCS, exist_ok=True)
    marks = json.load(open(os.path.join(WORK, "marks.json"), encoding="utf-8"))
    events = []
    with open(os.path.join(WORK, "events.tsv"), encoding="utf-8") as f:
        for line in f:
            t, path, _ = line.rstrip("\n").split("\t", 2)
            events.append((float(t), path))

    title = card("title", [
        ("Word Popper", font("georgia.ttf", 112), 150, INK),
        ("Learn words inside the book you're already reading.", font("georgiai.ttf", 46), 110, INK),
        ("select  ·  tap Ctrl+Shift  ·  hear it  ·  keep reading", font("segoeui.ttf", 32), 60, MUTED),
    ], 4.0)
    parts = [title] + [process_segment(s, marks, events) for s in SEGMENTS]
    end = card("end", [
        ("No dictionary tab. No flash-card deck to build.", font("georgiai.ttf", 50), 90, INK),
        ("Just keep reading.", font("georgia.ttf", 84), 170, INK),
        (REPO, font("seguisb.ttf", 40), 64, INK),
        ("Windows 10/11  ·  12 languages", font("segoeui.ttf", 30), 50, MUTED),
    ], 5.5)
    parts.append(end)

    listing = os.path.join(WORK, "parts.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p.replace(os.sep, '/')}'\n" for p in parts)
    mp4 = os.path.join(DOCS, "demo.mp4")
    run(["-f", "concat", "-safe", "0", "-i", listing, "-c:v", "libx264", "-crf", "22", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", mp4])

    # README GIF: the English segment only, smaller and without sound
    gif = os.path.join(DOCS, "demo.gif")
    palette = os.path.join(WORK, "palette.png")
    seg = os.path.join(WORK, "1_english_video.mp4")
    scale = "fps=10,scale=900:-1:flags=lanczos"
    run(["-i", seg, "-vf", f"{scale},palettegen=max_colors=128:stats_mode=diff", palette])
    run(["-i", seg, "-i", palette, "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4", gif])
    for p in (mp4, gif):
        print(f"{p}: {os.path.getsize(p) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

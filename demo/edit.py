"""Turn the raw recordings from record.py into docs/demo.mp4 and docs/demo.gif.

Crops each segment to 16:9, burns in captions and key-press badges, adds a voice-over, rebuilds
the word audio from Word Popper's playback log (so every word is heard exactly when it was
spoken), and adds a title and end card. Where a narration line needs more time than the gap
before the next spoken word, the picture holds still until the narrator is done, so the
voice-over never talks over a word.
"""

import json
import os
import re
import subprocess
import sys
import time

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work")
DOCS = os.path.join(ROOT, "docs")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
sys.path.insert(0, ROOT)
from speech import Speaker  # noqa: E402  (reuses Word Popper's Edge TTS cache)

W, H, FPS = 1920, 1080, 30
CROP = "crop=2560:1440:0:0"   # drop the bottom rows where the taskbar can flash in
SEGMENTS = ["1_english", "2_spanish", "3_review"]
REPO = "github.com/jia-jing-zhang-dev/Real-Time-Translate-MCP-"

NARRATOR = "en-US-AndrewNeural"   # a different voice from the words being looked up
NARRATOR_RATE = "+0%"
GAP = 0.25                        # breathing room between narration and a spoken word

# Voice-over. Each line is anchored to a caption (by its text) or to the end of a spoken word.
TITLE_LINE = "Meet Word Popper. It lets you learn new words inside whatever you're already reading."
END_LINE = "No dictionary tab. No flash-card deck to build. Just keep reading."
NARRATION = {
    "1_english": [
        (("caption", "Reading Pride and Prejudice"), "Here I'm reading Pride and Prejudice. "
                                                     "English isn't my first language."),
        (("caption", "Select a word"), "When I hit a word I don't know, I select it, and tap Control Shift."),
        (("caption", "Translation, IPA"), "A card pops up with the translation and the IPA, "
                                          "and I hear the word right away."),
        (("caption", "Phrases work too"), "Phrases work too."),
        (("caption", "Click the card"), "Click the card to hear it again."),
        (("caption", "Can't select it"), "Text inside an image? Snip it with Windows Shift S, "
                                         "and Word Popper reads it right on your computer."),
        (("after", "synonymously"), "No browser tab, no copy and paste. I never leave the page."),
    ],
    "2_spanish": [
        (("caption", "12 languages"), "Learning a different language? Pick from twelve in Settings: "
                                      "the one you're learning, and the one you speak."),
        (("caption", "Reading Don Quijote"), "Now I'm an English speaker, reading Don Quijote in Spanish."),
        (("after", "hidalgo"), "Every word is read by a native Spanish voice."),
    ],
    "3_review": [
        (("caption", "Every word you look up"), "Every word I look up is saved to my word list."),
        (("caption", "Review later"), "Later, I review them with spaced-repetition flash cards. "
                                      "The ones I forget come back sooner."),
    ],
}

PAPER = (247, 242, 232)
INK = (43, 38, 32)
MUTED = (138, 127, 112)
FONT_DIR = r"C:\Windows\Fonts"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


CAPTION_FONT = font("seguisb.ttf", 40)
KEY_FONT = font("seguisb.ttf", 34)
speaker = Speaker()


def run(args, **kw):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **kw)


def probe(path):
    return subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True).stderr


def start_time(path):
    return float(re.search(r"start: ([\d.]+)", probe(path)).group(1))


def duration_of(path):
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe(path)).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def recorded_length(path):
    """Length of a recording (its container duration is meaningless because of -copyts)."""
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-map", "0:v", "-c", "copy", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", err)[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def narration_clip(text, attempts=4):
    for attempt in range(attempts):
        try:
            path = speaker._synthesize(text, NARRATOR, NARRATOR_RATE)
            return path, duration_of(path)
        except Exception:  # the Edge TTS service occasionally returns nothing; just ask again
            if attempt == attempts - 1:
                raise
            time.sleep(2 + 2 * attempt)


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


# ---------------------------------------------------------------- timing

class Timeline:
    """Maps recording time to video time once freeze-frames ("holds") are inserted."""

    def __init__(self):
        self.holds = {}  # recording time -> seconds to hold that frame

    def add_hold(self, t, seconds):
        self.holds[t] = self.holds.get(t, 0) + seconds

    def out(self, t):
        """Video time of recording time `t` (a hold exactly at `t` comes after it)."""
        return t + sum(d for h, d in self.holds.items() if h < t)


def plan_narration(name, seg_marks, words, length):
    """Place each narration line and add holds so it never overlaps a spoken word.

    `words` are (recording time, duration) of Word Popper's own playback.
    Returns (timeline, [(video time, mp3 path)]).
    """
    tl = Timeline()
    placed = []
    prev_end = 0.0
    for (kind, key), text in NARRATION.get(name, []):
        if kind == "caption":
            anchor = next(m["t"] for m in seg_marks if m["kind"] == "caption" and m["text"].startswith(key))
        else:
            anchor = next(t + d for t, d, w in words if w == key) + GAP
        # don't start while a word is still being spoken
        for t, d, _ in words:
            if t <= anchor < t + d + GAP:
                anchor = t + d + GAP
        path, dur = narration_clip(text)
        start = tl.out(anchor)
        if start < prev_end + GAP:  # previous line still playing: hold this frame until it ends
            tl.add_hold(anchor, prev_end + GAP - start)
            start = prev_end + GAP
        next_word = min((t for t, _, _ in words if t > anchor), default=length)
        room = tl.out(next_word) - start
        if dur + GAP > room:
            tl.add_hold(anchor, dur + GAP - room)
        placed.append((start, path))
        prev_end = start + dur
    # let the last line finish before the segment ends
    end_out = tl.out(length)
    if prev_end + 0.6 > end_out:
        tl.add_hold(length - 1 / FPS, prev_end + 0.6 - end_out)
    return tl, placed


# ---------------------------------------------------------------- segments

def process_segment(name, marks, events):
    src = os.path.join(WORK, f"{name}.mkv")
    t0 = start_time(src)
    length = recorded_length(src)
    seg_marks = [dict(m, t=m["t"] - t0) for m in marks if m["t"] >= t0 - 1]

    words = [(t - t0, duration_of(path), word) for t, path, word in events if 0 <= t - t0 < length]
    tl, narration = plan_narration(name, seg_marks, words, length)
    holds = {round(h * FPS): round(d * FPS) for h, d in tl.holds.items()}

    overlays = []
    for m in seg_marks:
        if m["kind"] == "caption":  # a caption stays up through any hold inside it
            start, end = tl.out(m["t"]), tl.out(m["t"] + m["dur"])
            overlays.append(("caption", m["text"], start, end - start))
        elif m["kind"] == "keys":
            overlays.append(("keys", m["text"], tl.out(m["t"]), 1.5))

    silent = os.path.join(WORK, f"{name}_video.mp4")
    encoder = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    decoder = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", src,
         "-vf", f"{CROP},scale={W}:{H}:flags=lanczos,fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)
    frame_bytes = W * H * 3
    out_frame = 0

    def emit(raw, count):
        nonlocal out_frame
        for _ in range(count):
            t = out_frame / FPS
            img = Image.frombytes("RGB", (W, H), raw).convert("RGBA")
            for kind, text, start, dur in overlays:
                a = fade(t, start, dur, edge=0.25 if kind == "caption" else 0.15)
                if a:
                    (draw_caption if kind == "caption" else draw_keys)(img, text, a)
            encoder.stdin.write(img.convert("RGB").tobytes())
            out_frame += 1

    i, last = 0, None
    while True:
        raw = decoder.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        emit(raw, 1 + holds.pop(i, 0))
        i, last = i + 1, raw
    emit(last, sum(holds.values()))  # holds scheduled past the last decoded frame
    encoder.stdin.close()
    encoder.wait()
    decoder.wait()
    duration = out_frame / FPS

    clips = [(tl.out(t), path) for t, path in
             ((t - t0, p) for t, p, _ in events) if 0 <= t < length]
    clips += narration
    out = os.path.join(WORK, f"{name}.mp4")
    mix_audio(silent, clips, duration, out)
    print(f"{name}: {length:.1f}s recorded -> {duration:.1f}s with {len(tl.holds)} hold(s)")
    return out


def mix_audio(video, clips, duration, out, video_fades=True):
    inputs, filters = ["-i", video], []
    for i, (offset, path) in enumerate(clips):
        inputs += ["-i", path]
        filters.append(f"[{i + 1}:a]adelay={int(offset * 1000)}:all=1,aresample=48000[a{i}]")
    if clips:
        mix = "".join(f"[a{i}]" for i in range(len(clips)))
        filters.append(f"{mix}amix=inputs={len(clips)}:normalize=0,apad[mixed]")
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        filters.append("[1:a]anull[mixed]")
    filters.append(f"[mixed]afade=t=in:d=0.3,afade=t=out:st={duration - 0.4:.2f}:d=0.4[aout]")
    vf = f"fade=t=in:d=0.35,fade=t=out:st={duration - 0.4:.2f}:d=0.4" if video_fades else "null"
    filters.append(f"[0:v]{vf}[vout]")
    run([*inputs, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
         "-t", f"{duration:.2f}", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", out])


# ---------------------------------------------------------------- cards

def card(name, lines, narration, min_seconds):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    total = sum(h for _, _, h, _ in lines)
    y = (H - total) / 2
    for text, fnt, height, color in lines:
        d.text(((W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=color)
        y += height
    png = os.path.join(WORK, f"{name}.png")
    img.save(png)
    path, dur = narration_clip(narration)
    seconds = max(min_seconds, 0.6 + dur + 1.0)
    still = os.path.join(WORK, f"{name}_video.mp4")
    run(["-loop", "1", "-i", png, "-vf", f"fps={FPS},format=yuv420p,fade=t=in:d=0.5,"
         f"fade=t=out:st={seconds - 0.6:.2f}:d=0.6", "-t", f"{seconds:.2f}", "-c:v", "libx264",
         "-crf", "18", still])
    out = os.path.join(WORK, f"{name}.mp4")
    mix_audio(still, [(0.6, path)], seconds, out, video_fades=False)
    return out


def main():
    os.makedirs(DOCS, exist_ok=True)
    marks = json.load(open(os.path.join(WORK, "marks.json"), encoding="utf-8"))
    events = []
    with open(os.path.join(WORK, "events.tsv"), encoding="utf-8") as f:
        for line in f:
            t, path, word = line.rstrip("\n").split("\t", 2)
            events.append((float(t), path, word))

    title = card("title", [
        ("Word Popper", font("georgia.ttf", 112), 150, INK),
        ("Learn words inside the book you're already reading.", font("georgiai.ttf", 46), 110, INK),
        ("select  ·  tap Ctrl+Shift  ·  hear it  ·  keep reading", font("segoeui.ttf", 32), 60, MUTED),
    ], TITLE_LINE, 4.0)
    parts = [title] + [process_segment(s, marks, events) for s in SEGMENTS]
    end = card("end", [
        ("No dictionary tab. No flash-card deck to build.", font("georgiai.ttf", 50), 90, INK),
        ("Just keep reading.", font("georgia.ttf", 84), 170, INK),
        (REPO, font("seguisb.ttf", 40), 64, INK),
        ("Windows 10/11  ·  12 languages", font("segoeui.ttf", 30), 50, MUTED),
    ], END_LINE, 5.5)
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
        print(f"{p}: {os.path.getsize(p) / 1e6:.1f} MB, {duration_of(p):.1f}s")


if __name__ == "__main__":
    main()

"""Turn the Blender renders into the app's cat frames.

    python tools/cat_render/make_cat_frames.py RENDER_DIR

RENDER_DIR is what render_all.py wrote: one folder per skin (<coat>_<type>/<frame>.png, 360 px renders from a
fixed orthographic camera) and anchors_<type>.json (head and ear positions, 0..1 of the render). Every frame of
every skin is cropped to the same box, so all cats share one scale and one ground line, scaled to CANVAS_H and
saved as WebP (small, keeps alpha) in assets/cats/. meta.json gets the canvas size and the anchors in pixels.
"""

import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "assets", "cats")
CANVAS_H = 200   # stored frame height; the app scales it to the screen
PAD = 6


def main(src):
    skins = sorted(d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d)))
    # one crop box for everything: the union of what any frame covers
    box = None
    for skin in skins:
        for f in os.listdir(os.path.join(src, skin)):
            bb = Image.open(os.path.join(src, skin, f)).getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
            if bb:
                box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    box = (max(0, box[0] - PAD), max(0, box[1] - PAD), box[2] + PAD, box[3] + PAD)
    render = Image.open(os.path.join(src, skins[0], "sit.png")).size
    k = CANVAS_H / (box[3] - box[1])
    canvas = (round((box[2] - box[0]) * k), CANVAS_H)
    os.makedirs(OUT, exist_ok=True)
    for skin in skins:
        os.makedirs(os.path.join(OUT, skin), exist_ok=True)
        for f in sorted(os.listdir(os.path.join(src, skin))):
            im = Image.open(os.path.join(src, skin, f)).convert("RGBA").crop(box).resize(canvas, Image.LANCZOS)
            im.save(os.path.join(OUT, skin, os.path.splitext(f)[0] + ".webp"), "WEBP", quality=82, method=6)

    def px(p):
        return [round((p[0] * render[0] - box[0]) * k, 1), round((p[1] * render[1] - box[1]) * k, 1)]

    anchors = {}
    for name in os.listdir(src):
        if name.startswith("anchors_") and name.endswith(".json"):
            ty = name[len("anchors_"):-len(".json")]
            data = json.load(open(os.path.join(src, name)))
            anchors[ty] = {fr: {"head": px(a["head"]), "ear_l": px(a["ear_l"]), "ear_r": px(a["ear_r"]),
                                "side": a["side"]} for fr, a in data.items()}
    json.dump({"canvas": canvas, "anchors": anchors}, open(os.path.join(OUT, "meta.json"), "w"), indent=1)
    print("canvas", canvas, "skins", len(skins))


if __name__ == "__main__":
    main(sys.argv[1])

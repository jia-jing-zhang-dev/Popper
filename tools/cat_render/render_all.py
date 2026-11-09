# Run with: blender -b catrig.blend --python render_all.py -- OUT_DIR [types...]
# Renders every frame the app uses, for every body type and coat, plus where the head is in each frame.
import json
import os
import sys
import time

import bpy
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
ONLY = argv[1:]

ns = {}
exec(bpy.data.texts["catpose.py"].as_string(), ns)
fur = {}
exec(bpy.data.texts["catfur.py"].as_string(), fur)
COATS = eval(bpy.data.texts["coats.py"].as_string())

FRONT = ["sit", "blink", "think", "talk", "talk2", "worried", "wave1", "wave2", "yawn", "lick1", "lick2", "sleep"]
SIDE = ["sit_s", "blink_s", "boop", "groom1", "groom2", "groomed"] + [f"walk{i}" for i in range(6)] + \
       [f"run{i}" for i in range(4)] + ["sleep_s"]
FRAMES = FRONT + SIDE

sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 16
sc.render.resolution_x = sc.render.resolution_y = 360
sc.render.film_transparent = True
cam = sc.camera
body = bpy.data.objects["Object_12"]
skin = fur["skin_material"]("A")
body.data.materials[0] = skin
tex = next(n for n in skin.node_tree.nodes if n.type == "TEX_IMAGE")


def project(p):
    v = world_to_camera_view(sc, cam, p)
    return [round(v.x, 4), round(1 - v.y, 4)]   # image coords: 0..1 from the top-left


t0 = time.time()
for ty in (ONLY or list(ns["TYPES"])):
    spec = ns["TYPES"][ty]
    fur["add_fur"](body, length=spec["fur"], fluff=spec["fluff"])
    ns["apply_type"](ty)
    meta = {}
    for frame in FRAMES:
        ns["pose"](frame)
        ns["head_size"](ty)
        arm = ns["arm"]()
        ears = [arm.matrix_world @ arm.pose.bones[ns["B"][k]].head for k in ("l_ear", "r_ear")]
        top = (ears[0] + ears[1]) / 2
        meta[frame] = {"head": project(top), "ear_l": project(ears[0]), "ear_r": project(ears[1]),
                       "side": frame in SIDE}
        for coat in COATS:
            tex.image = bpy.data.images[f"coat_{coat}"]
            d = os.path.join(OUT, f"{coat}_{ty}")
            os.makedirs(d, exist_ok=True)
            sc.render.filepath = os.path.join(d, frame + ".png")
            bpy.ops.render.render(write_still=True)
        print(f"{ty} {frame} done, {time.time() - t0:.0f}s", flush=True)
    with open(os.path.join(OUT, f"anchors_{ty}.json"), "w") as f:
        json.dump(meta, f, indent=1)
print("ALL DONE", round(time.time() - t0), flush=True)

# Rendering the desktop cats

The cats in `assets/cats/` are renders of **"An Animated Cat"** by **Evil_Katz**
(https://sketchfab.com/3d-models/an-animated-cat-aec25699660043a29595f9572149d1e8, CC-BY-4.0), re-posed and
re-coloured in Blender 5.1. The model itself is not in this repository; these scripts are, so the frames can be
made again.

| File | What it does |
| --- | --- |
| `catpose.py` | Poses the model's rig: `sit`, `stand_gait` (walk, run), `loaf` (sleep), expressions (`face`: eyelids, jaw, tongue, ears, head), and `pose(name)` for every frame Popper uses. `TYPES` are the four body types (scale, head size, fur). |
| `catmats.py` | The coat as a procedural material: mackerel stripes, the forehead "M", white bib/muzzle/paws, calico patches; read from each vertex's rest position (`rest` attribute) so the pattern stays on the body in every pose. |
| `coats.py`, `realcoat.py` | The 8 coats (A brown tabby, B orange, C silver tabby, D British blue, E black, F tuxedo, G calico, H white) and the settings for this model. |
| `catfur.py` | Bakes nothing itself; makes the skin material from a baked coat texture (`coat_<key>` images) and grows the fur (particle hair, kept off the eyes, nose, inner ears and paw pads). |
| `render_all.py` | `blender -b catrig.blend --python render_all.py -- OUT_DIR` renders every frame for every body type and coat, and writes where the head and ears are in each frame. |
| `make_cat_frames.py` | Crops all renders to one shared box, scales them, saves WebP to `assets/cats/<coat>_<type>/`, and writes `assets/cats/meta.json` (canvas size, anchors). |

Steps: import the model's glTF, parent it under an empty `Real_root` (scale 0.0085, rotated -90 degrees about Z), store
each vertex's rest position in a `rest` attribute, bake each coat from `catmats.py` into a `coat_<key>` image on
the model's UVs (Cycles, Diffuse colour), set up an orthographic camera `CatCam`, then run `render_all.py` and
`make_cat_frames.py`.

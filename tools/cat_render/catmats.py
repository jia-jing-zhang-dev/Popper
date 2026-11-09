
import bpy

def _node(nt, kind, loc, **kw):
    n = nt.nodes.new(kind); n.location = loc
    for k, v in kw.items():
        setattr(n, k, v)
    return n

def _math(nt, op, a, b=None, loc=(0, 0), clamp=False):
    n = _node(nt, "ShaderNodeMath", loc, operation=op, use_clamp=clamp)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]

def _bsdf(nt):
    return next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")

def smooth_band(nt, v, lo, hi, loc):
    """0 below lo, 1 above hi, smooth in between."""
    mr = _node(nt, "ShaderNodeMapRange", loc, interpolation_type="SMOOTHSTEP")
    nt.links.new(v, mr.inputs["Value"])
    mr.inputs["From Min"].default_value = lo
    mr.inputs["From Max"].default_value = hi
    return mr.outputs["Result"]

COAT = {"base": (0.46, 0.28, 0.12), "tick": (0.26, 0.15, 0.07), "stripe": (0.035, 0.026, 0.020), "stripes": 1.0,
        "white": (0.78, 0.75, 0.70), "white_amt": 1.0, "patch": None}

def fur_material(coat=None, name="CatFur"):
    coat = dict(COAT, **(coat or {}))
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type not in ("OUTPUT_MATERIAL", "BSDF_PRINCIPLED"):
            nt.nodes.remove(n)
    if not any(n.type == "BSDF_PRINCIPLED" for n in nt.nodes):
        nt.nodes.new("ShaderNodeBsdfPrincipled")
    b = _bsdf(nt); b.location = (900, 0)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"); out.location = (1150, 0)
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    tc = _node(nt, "ShaderNodeTexCoord", (-1200, 0))
    co = tc.outputs["Object"]
    if coat.get("coord") == "rest":   # the rigged model: pattern stays glued to the body in every pose
        ra = _node(nt, "ShaderNodeAttribute", (-1200, 200), attribute_type="GEOMETRY", attribute_name="rest")
        co = ra.outputs["Vector"]
    xyz = _node(nt, "ShaderNodeSeparateXYZ", (-1000, 0)); nt.links.new(co, xyz.inputs[0])
    X, Y, Z = xyz.outputs
    # wobble the coordinates so stripes aren't ruler straight
    noise = _node(nt, "ShaderNodeTexNoise", (-1000, 300)); noise.inputs["Scale"].default_value = 60
    noise.inputs["Detail"].default_value = 6
    nt.links.new(co, noise.inputs["Vector"])
    # mackerel stripes: on the body they run down the sides (vary along Y and Z), on legs and tail around them
    wave = _node(nt, "ShaderNodeTexWave", (-700, 300), wave_type="BANDS", bands_direction="Y",
                 wave_profile="SIN")
    wave.inputs["Scale"].default_value = 20.0
    wave.inputs["Distortion"].default_value = 7.0
    wave.inputs["Detail"].default_value = 3.5
    wave.inputs["Detail Scale"].default_value = 2.0
    mp = _node(nt, "ShaderNodeMapping", (-850, 300))
    mp.inputs["Rotation"].default_value = (0.35, 0.0, 0.0)
    nt.links.new(co, mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], wave.inputs["Vector"])
    body_st = smooth_band(nt, wave.outputs["Fac"], 0.55, 0.95, (-450, 300))
    lw = _node(nt, "ShaderNodeTexWave", (-700, 500), wave_type="BANDS", bands_direction="Z", wave_profile="SIN")
    lw.inputs["Scale"].default_value = 28.0; lw.inputs["Distortion"].default_value = 2.0
    nt.links.new(co, lw.inputs["Vector"])
    leg_st = smooth_band(nt, lw.outputs["Fac"], 0.58, 0.92, (-450, 500))
    limb = _math(nt, "SUBTRACT", 1.0, smooth_band(nt, Z, coat.get("limb_z", (0.030, 0.050))[0], coat.get("limb_z", (0.030, 0.050))[1], (-450, 650)), (-300, 650))
    stripes = _node(nt, "ShaderNodeMix", (-250, 400), data_type="FLOAT")
    nt.links.new(limb, stripes.inputs["Factor"]); nt.links.new(body_st, stripes.inputs["A"]); nt.links.new(leg_st, stripes.inputs["B"])
    stripes = stripes.outputs["Result"]
    # base coat: warm grey-brown with darker ticking from the noise
    base = _node(nt, "ShaderNodeMix", (-200, 200), data_type="RGBA", blend_type="MIX")
    base.inputs["A"].default_value = (*coat["base"], 1)
    base.inputs["B"].default_value = (*coat["tick"], 1)
    nt.links.new(noise.outputs["Fac"], base.inputs["Factor"])
    tab = _node(nt, "ShaderNodeMix", (50, 200), data_type="RGBA", blend_type="MIX")
    nt.links.new(base.outputs["Result"], tab.inputs["A"])
    tab.inputs["B"].default_value = (*coat["stripe"], 1)
    TAB_LINK = (stripes, tab)
    tab.inputs["B"].default_value = tuple(0.55 * c + 0.45 * k for c, k in zip(coat["stripe"], (coat["tick"][0] * 0.35, coat["tick"][1] * 0.35, coat["tick"][2] * 0.35))) + (1,)
    # white markings, placed per pose: the body object carries cat_head, cat_chest_c/r and cat_foot0..3
    def prop(name, loc):
        a = _node(nt, "ShaderNodeAttribute", loc, attribute_type="OBJECT", attribute_name=name)
        return a.outputs["Vector"]
    def vsub(a, b, loc):
        n = _node(nt, "ShaderNodeVectorMath", loc, operation="SUBTRACT"); nt.links.new(a, n.inputs[0]); nt.links.new(b, n.inputs[1]); return n.outputs[0]
    def vdiv(a, b, loc):
        n = _node(nt, "ShaderNodeVectorMath", loc, operation="DIVIDE"); nt.links.new(a, n.inputs[0]); nt.links.new(b, n.inputs[1]); return n.outputs[0]
    def vlen(a, loc):
        n = _node(nt, "ShaderNodeVectorMath", loc, operation="LENGTH"); nt.links.new(a, n.inputs[0]); return n.outputs["Value"]
    # chest: inside an ellipsoid
    chest_d = vlen(vdiv(vsub(co, prop("cat_chest_c", (-1000, -200)), (-800, -200)), prop("cat_chest_r", (-1000, -350)), (-650, -250)), (-500, -250))
    chest = _math(nt, "SUBTRACT", 1.0, smooth_band(nt, chest_d, 0.8, 1.0, (-350, -250)), (-200, -250))
    # muzzle and chin, relative to the head centre and in head size
    hs = _node(nt, "ShaderNodeAttribute", (-1000, -700), attribute_type="OBJECT", attribute_name="cat_head_s")
    inv = _math(nt, "DIVIDE", 1.0, hs.outputs["Fac"], (-850, -700))
    sc = _node(nt, "ShaderNodeVectorMath", (-700, -600), operation="SCALE")
    nt.links.new(vsub(co, prop("cat_head", (-1000, -600)), (-850, -600)), sc.inputs[0]); nt.links.new(inv, sc.inputs["Scale"])
    rel = sc.outputs[0]
    rxyz = _node(nt, "ShaderNodeSeparateXYZ", (-550, -600)); nt.links.new(rel, rxyz.inputs[0])
    RX, RY, RZ = rxyz.outputs
    muzzle_z = _math(nt, "MULTIPLY", smooth_band(nt, RZ, -0.034, -0.028, (-450, -650)),
                     _math(nt, "SUBTRACT", 1.0, smooth_band(nt, RZ, -0.008, -0.002, (-450, -800)), (-300, -800)), (-150, -700))
    muzzle_y = smooth_band(nt, _math(nt, "MULTIPLY", RY, -1.0, (-450, -950)), 0.028, 0.036, (-300, -950))
    muzzle = _math(nt, "MULTIPLY", muzzle_z, muzzle_y, (0, -800))
    # tabby face: "M" lines on the forehead and a dark line back from each eye
    fw = _node(nt, "ShaderNodeTexWave", (-300, 1000), wave_type="BANDS", bands_direction="X", wave_profile="SIN")
    fw.inputs["Scale"].default_value = 6.0; fw.inputs["Distortion"].default_value = 1.5
    nt.links.new(rel, fw.inputs["Vector"])
    fl = smooth_band(nt, fw.outputs["Fac"], 0.70, 0.86, (-100, 1000))
    fzone = _math(nt, "MULTIPLY", smooth_band(nt, RZ, 0.010, 0.016, (-300, 850)),
                  smooth_band(nt, _math(nt, "MULTIPLY", RY, -1.0, (-450, 750)), 0.010, 0.020, (-300, 750)), (-100, 850))
    forehead = _math(nt, "MULTIPLY", fl, fzone, (100, 900))
    cz = _math(nt, "MULTIPLY", smooth_band(nt, RZ, -0.006, -0.003, (-300, 650)),
               _math(nt, "SUBTRACT", 1.0, smooth_band(nt, RZ, -0.001, 0.002, (-300, 550)), (-150, 550)), (0, 600))
    cx = smooth_band(nt, _math(nt, "ABSOLUTE", RX, None, (-450, 450)), 0.028, 0.032, (-300, 450))
    cheek = _math(nt, "MULTIPLY", cz, cx, (150, 550))
    face_marks = forehead
    # paws: close to one of the four feet
    feet = None
    for i in range(4):
        d = vlen(vsub(co, prop(f"cat_foot{i}", (-1000, -1100 - 150 * i)), (-800, -1100 - 150 * i)), (-650, -1100 - 150 * i))
        pr = coat.get("paw_r", (0.020, 0.028))
        near = _math(nt, "SUBTRACT", 1.0, smooth_band(nt, d, pr[0], pr[1], (-500, -1100 - 150 * i)), (-350, -1100 - 150 * i))
        feet = near if feet is None else _math(nt, "MAXIMUM", feet, near, (-200, -1100 - 150 * i))
    paws = feet
    st, tb = TAB_LINK
    nt.links.new(_math(nt, "MULTIPLY", _math(nt, "MAXIMUM", st, face_marks, (450, 650)), coat["stripes"], (600, 650)), tb.inputs["Factor"])
    white = _math(nt, "MAXIMUM", _math(nt, "MAXIMUM", chest, muzzle, (100, -500)), paws, (250, -500), clamp=True)
    fin = _node(nt, "ShaderNodeMix", (450, 100), data_type="RGBA", blend_type="MIX")
    nt.links.new(tab.outputs["Result"], fin.inputs["A"])
    fin.inputs["B"].default_value = (*coat["white"], 1)
    nt.links.new(_math(nt, "MULTIPLY", white, coat["white_amt"], (350, -500)), fin.inputs["Factor"])
    if coat["patch"]:   # calico: big orange and black patches on white
        pn = _node(nt, "ShaderNodeTexNoise", (100, 600)); pn.inputs["Scale"].default_value = 9.0
        pn.inputs["Detail"].default_value = 2.0
        nt.links.new(co, pn.inputs["Vector"])
        o = smooth_band(nt, pn.outputs["Fac"], 0.52, 0.56, (300, 650))
        k = _math(nt, "SUBTRACT", 1.0, smooth_band(nt, pn.outputs["Fac"], 0.40, 0.44, (300, 500)), (450, 500))
        c1 = _node(nt, "ShaderNodeMix", (500, 700), data_type="RGBA"); c1.inputs["A"].default_value = (*coat["white"], 1)
        c1.inputs["B"].default_value = (*coat["patch"][0], 1); nt.links.new(o, c1.inputs["Factor"])
        c2 = _node(nt, "ShaderNodeMix", (650, 700), data_type="RGBA"); nt.links.new(c1.outputs["Result"], c2.inputs["A"])
        c2.inputs["B"].default_value = (*coat["patch"][1], 1); nt.links.new(k, c2.inputs["Factor"])
        keep = _math(nt, "SUBTRACT", 1.0, _math(nt, "MULTIPLY", white, coat["white_amt"], (500, 400)), (650, 400))
        c3 = _node(nt, "ShaderNodeMix", (800, 600), data_type="RGBA"); c3.inputs["A"].default_value = (*coat["white"], 1)
        nt.links.new(c2.outputs["Result"], c3.inputs["B"]); nt.links.new(keep, c3.inputs["Factor"])
        fin = c3
    # inside of the ears: pink skin with little fur, on the front face of each ear
    ear_z = smooth_band(nt, RZ, 0.030, 0.038, (200, -900))
    ear_y = smooth_band(nt, _math(nt, "MULTIPLY", RY, -1.0, (0, -1050)), 0.002, 0.006, (200, -1050))
    ear_x = smooth_band(nt, _math(nt, "ABSOLUTE", RX, None, (0, -1200)), 0.014, 0.020, (200, -1200))
    inner = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", ear_z, ear_y, (400, -950)), ear_x, (550, -1000))
    ear = _node(nt, "ShaderNodeMix", (650, 100), data_type="RGBA", blend_type="MIX")
    nt.links.new(fin.outputs["Result"], ear.inputs["A"])
    ear.inputs["B"].default_value = (0.62, 0.36, 0.36, 1)
    nt.links.new(inner, ear.inputs["Factor"])
    final = ear.outputs["Result"]
    if coat.get("detail"):
        img = bpy.data.images.get(coat["detail"])
        tx = _node(nt, "ShaderNodeTexImage", (500, 400)); tx.image = img
        uv = _node(nt, "ShaderNodeUVMap", (300, 400)); uv.uv_map = "UVMap"
        nt.links.new(uv.outputs[0], tx.inputs["Vector"])
        bw = _node(nt, "ShaderNodeRGBToBW", (700, 400)); nt.links.new(tx.outputs["Color"], bw.inputs[0])
        mr = _node(nt, "ShaderNodeMapRange", (850, 400))
        nt.links.new(bw.outputs[0], mr.inputs["Value"])
        mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = 0.01, 0.12
        mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.70, 1.35
        mul = _node(nt, "ShaderNodeMix", (1000, 200), data_type="RGBA", blend_type="MULTIPLY")
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(final, mul.inputs["A"])
        cc = _node(nt, "ShaderNodeCombineColor", (900, 300))
        for k in ("Red", "Green", "Blue"):
            nt.links.new(mr.outputs["Result"], cc.inputs[k])
        nt.links.new(cc.outputs[0], mul.inputs["B"])
        final = mul.outputs["Result"]
    nt.links.new(final, b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.85
    try:
        b.inputs["Subsurface Weight"].default_value = 0.15
        b.inputs["Subsurface Radius"].default_value = (0.004, 0.002, 0.0015)
    except KeyError:
        pass
    try:
        b.inputs["Sheen Weight"].default_value = 0.12
        b.inputs["Sheen Roughness"].default_value = 0.5
        b.inputs["Specular IOR Level"].default_value = 0.25
    except KeyError:
        pass
    bump = _node(nt, "ShaderNodeBump", (600, -200)); bump.inputs["Strength"].default_value = 0.25
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs[0], b.inputs["Normal"])
    return m

def eye_material(iris_cols=((0.55, 0.42, 0.06), (0.32, 0.38, 0.08))):
    m = bpy.data.materials.get("CatEye") or bpy.data.materials.new("CatEye")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type not in ("OUTPUT_MATERIAL", "BSDF_PRINCIPLED"):
            nt.nodes.remove(n)
    b = _bsdf(nt)
    tc = _node(nt, "ShaderNodeTexCoord", (-1000, 0))
    xyz = _node(nt, "ShaderNodeSeparateXYZ", (-800, 0)); nt.links.new(tc.outputs["Object"], xyz.inputs[0])
    X, Y, Z = xyz.outputs
    r = _math(nt, "SQRT", _math(nt, "ADD", _math(nt, "POWER", X, 2, (-600, 100)), _math(nt, "POWER", Z, 2, (-600, -50)), (-450, 0)), None, (-300, 0))
    # vertical slit pupil: an ellipse 3.5 times taller than wide
    slit = _math(nt, "SQRT", _math(nt, "ADD", _math(nt, "POWER", _math(nt, "MULTIPLY", X, 3.5, (-600, -250)), 2, (-450, -250)),
                                   _math(nt, "POWER", Z, 2, (-450, -400)), (-300, -300)), None, (-150, -300))
    pupil = _math(nt, "SUBTRACT", 1.0, smooth_band(nt, slit, 0.0072, 0.0082, (0, -300)), (150, -300))
    iris_grad = smooth_band(nt, r, 0.002, 0.0095, (0, 100))
    iris = _node(nt, "ShaderNodeMix", (200, 100), data_type="RGBA")
    iris.inputs["A"].default_value = (*iris_cols[0], 1)
    iris.inputs["B"].default_value = (*iris_cols[1], 1)
    nt.links.new(iris_grad, iris.inputs["Factor"])
    rim = smooth_band(nt, r, 0.0098, 0.0108, (200, -100))
    c1 = _node(nt, "ShaderNodeMix", (400, 0), data_type="RGBA")
    nt.links.new(iris.outputs["Result"], c1.inputs["A"]); c1.inputs["B"].default_value = (0.02, 0.02, 0.02, 1)
    nt.links.new(rim, c1.inputs["Factor"])
    c2 = _node(nt, "ShaderNodeMix", (600, 0), data_type="RGBA")
    nt.links.new(c1.outputs["Result"], c2.inputs["A"]); c2.inputs["B"].default_value = (0.005, 0.005, 0.005, 1)
    nt.links.new(pupil, c2.inputs["Factor"])
    nt.links.new(c2.outputs["Result"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.05
    try:
        b.inputs["Coat Weight"].default_value = 1.0
        b.inputs["Coat Roughness"].default_value = 0.02
    except KeyError:
        pass
    return m

def nose_material():
    m = bpy.data.materials.get("CatNose") or bpy.data.materials.new("CatNose")
    m.use_nodes = True
    b = _bsdf(m.node_tree)
    b.inputs["Base Color"].default_value = (0.55, 0.25, 0.25, 1)
    b.inputs["Roughness"].default_value = 0.45
    return m

def all_materials():
    return {"fur": fur_material(), "eye": eye_material(), "nose": nose_material()}


def whisker_material():
    m = bpy.data.materials.get("CatWhisker") or bpy.data.materials.new("CatWhisker")
    m.use_nodes = True
    b = _bsdf(m.node_tree)
    b.inputs["Base Color"].default_value = (0.95, 0.94, 0.9, 1)
    b.inputs["Roughness"].default_value = 0.3
    return m

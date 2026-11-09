
import bpy, math
from mathutils import Vector, Matrix, Quaternion

ARM = "GLTF_created_0"
B = {  # short names for the rig's bones
    "body": "j_body_00_12", "hips": "j_hips_049_60", "s1": "j_spine_1_02_13", "s2": "j_spine_2_03_14", "s3": "j_spine_3_04_15",
    "s4": "j_spine_4_05_16", "neckb": "j_neck_base_06_17", "neck": "j_neck_1_07_18", "head": "j_head_08_19",
    "jaw": "j_jaw_09_20", "tongue1": "j_tongue_back_010_21", "tongue2": "j_tongue_mid_011_22", "tongue3": "j_tongue_tip_012_23",
    "l_ear": "j_l_ear_020_31", "r_ear": "j_r_ear_027_38", "l_eye": "j_l_eye_014_25", "r_eye": "j_r_eye_021_32",
    "l_ulid": "j_l_upper_eyelid_015_26", "l_llid": "j_l_lower_eyelid_016_27", "r_ulid": "j_r_upper_eyelid_022_33", "r_llid": "j_r_lower_eyelid_023_34",
    "chest": "j_chest_028_39",
    "l_scap": "j_l_scap_029_40", "l_hum": "j_l_humerous_031_42", "l_elb": "j_l_elbow_032_43", "l_wri": "j_l_wrist_033_44", "l_palm": "j_l_palm_034_45",
    "r_scap": "j_r_scap_030_41", "r_hum": "j_r_humerous_037_48", "r_elb": "j_r_elbow_038_49", "r_wri": "j_r_wrist_039_50", "r_palm": "j_r_palm_040_51",
    "l_fem": "j_l_femur_050_61", "l_knee": "j_l_knee_051_62", "l_ank": "j_l_ankle_052_63", "l_ball": "j_l_ball_053_64",
    "r_fem": "j_r_femur_055_66", "r_knee": "j_r_knee_056_67", "r_ank": "j_r_ankle_057_68", "r_ball": "j_r_ball_058_69",
    "t1": "j_tail_1_043_54", "t2": "j_tail_2_044_55", "t3": "j_tail_3_045_56", "t4": "j_tail_4_046_57", "t5": "j_tail_5_047_58", "t6": "j_tail_6_048_59",
}

def arm():
    return bpy.data.objects[ARM]

def reset():
    a = arm()
    if a.animation_data:
        a.animation_data.action = None
    for pb in a.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()

def from_action(frame, action="Take 001"):
    """Start from a frame of the model's own animation."""
    a = arm()
    act = bpy.data.actions[action]
    a.animation_data.action = act
    bpy.context.scene.frame_set(frame)
    basis = {pb.name: pb.matrix_basis.copy() for pb in a.pose.bones}
    a.animation_data.action = None
    for pb in a.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.matrix_basis = basis[pb.name]
    bpy.context.view_layer.update()

def rot(bone, axis, deg):
    """Rotate a bone (and everything below it) about a world axis through its head."""
    a = arm()
    pb = a.pose.bones[B.get(bone, bone)]
    aw = a.matrix_world.to_3x3().normalized()
    ax = (aw.inverted() @ Vector(axis)).normalized()
    head = pb.head.copy()
    R = Matrix.Translation(head) @ Matrix.Rotation(math.radians(deg), 4, ax) @ Matrix.Translation(-head)
    pb.matrix = R @ pb.matrix
    bpy.context.view_layer.update()

def head_world(bone="head"):
    a = arm()
    return a.matrix_world @ a.pose.bones[B[bone]].head


def lowest():
    dg = bpy.context.evaluated_depsgraph_get()
    z = 1e9
    for name in ("Object_12",):
        ob = bpy.data.objects[name]
        ev = ob.evaluated_get(dg)
        mw = ob.matrix_world
        z = min(z, min((mw @ v.co).z for v in ev.data.vertices))
    return z

def ground_on(bones, lift=0.004):
    """Put these bones' heads (paws) on the ground."""
    root = bpy.data.objects["Real_root"]
    root.location.z -= min(head_world(b).z for b in bones) - lift
    bpy.context.view_layer.update()

def ground():
    root = bpy.data.objects["Real_root"]
    root.location.z -= lowest()
    bpy.context.view_layer.update()

X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)

def bone_z(k):
    return head_world(k).z

def mesh_min_z(pred):
    dg = bpy.context.evaluated_depsgraph_get()
    ob = bpy.data.objects["Object_12"]
    ev = ob.evaluated_get(dg)
    mw = ob.matrix_world
    zs = [(mw @ v.co).z for v in ev.data.vertices if pred(mw @ v.co)]
    return min(zs) if zs else 1e9

def _sit_body(a, P):
    reset()
    root = bpy.data.objects["Real_root"]; root.location = (0, 0, 0)
    bpy.context.view_layer.update()
    rot("s1", X, -a)                        # torso up, pivoting at the hips
    for s in ("l", "r"):
        rot(f"{s}_hum", X, a - 6)           # front legs back to straight down
        rot(f"{s}_wri", X, 6)
        rot(f"{s}_fem", X, -70)             # thighs forward, knees beside the chest
        rot(f"{s}_knee", X, 120)            # shins fold back under
        rot(f"{s}_ank", X, -50)             # hind feet flat, toes forward
    rot("neckb", X, a * 0.75)               # head level again
    rot("neck", X, P.get("nod", 0) * 0.4)
    rot("head", X, P.get("nod", 0) * 0.6)

def sit(P=None):
    P = P or {}
    a = P.get("spine", 45)
    _sit_body(a, P)
    # tail: back along the ground, then round the side to the front paws
    rot("t1", X, 42)
    rot("t1", Z, -55)                      # round the cat's side...
    for i, d in enumerate((-42, -42, -40, -38, -34)):
        rot(f"t{i + 2}", Z, d)             # ...and curling forward to the paws
    ground_on(["l_palm", "r_palm"])
    return a


def face(P):
    """Expression on top of a body pose: eyelids, jaw, tongue, ears, head look."""
    if P.get("turn"):
        rot("neck", Z, P["turn"] * 0.4); rot("head", Z, P["turn"] * 0.6)
    if P.get("tilt"):
        rot("head", Y, P["tilt"])
    if P.get("look_up"):
        rot("head", X, -P["look_up"])
    close = P.get("eyes", 0.0)          # 0 open, 1 shut
    if close:
        for s in ("l", "r"):
            rot(f"{s}_ulid", X, 38 * close)
            rot(f"{s}_llid", X, -12 * close)
    if P.get("wide"):
        for s in ("l", "r"):
            rot(f"{s}_ulid", X, -10)
    if P.get("jaw"):
        rot("jaw", X, 26 * P["jaw"])
    if P.get("tongue"):
        rot("tongue1", X, 10); rot("tongue2", X, -10); rot("tongue3", X, -20)
    ears = P.get("ears", 0.0)           # + forward and alert, - flattened back
    if ears:
        for s, sx in (("l", 1), ("r", -1)):
            rot(f"{s}_ear", X, -40 * ears if ears < 0 else 15 * ears)
            if ears < 0:
                rot(f"{s}_ear", Y, sx * 35 * -ears)


BASE_YAW = -90.0
LIFE = {"eat1": lambda: eat(1), "eat2": lambda: eat(2), "drink1": lambda: drink(1), "drink2": lambda: drink(2),
        "scratch1": lambda: scratch(1), "scratch2": lambda: scratch(2), "arch": lambda: arch(),
        "tail1": lambda: tail_swish(1), "tail2": lambda: tail_swish(2), "rub1": lambda: rub(1), "rub2": lambda: rub(2)}
FRONT_LIFE = ("tail1", "tail2")
PLAY = {"crouch": lambda: crouch(), "pounce": lambda: pounce(), "bat1": lambda: swat(1), "bat2": lambda: swat(2),
        "stretch": lambda: stretch(), "roll1": lambda: roll(1), "roll2": lambda: roll(2)}   # the model's own orientation fix; poses add their yaw on top

def set_yaw(deg):
    root = bpy.data.objects["Real_root"]
    root.rotation_euler.y = 0
    root.rotation_euler.z = math.radians(BASE_YAW + deg)     # keeps a roll (x) if a pose set one
    bpy.context.view_layer.update()

def paw_up(side="l", up=1.0, lick=0.0):
    """Raise a front paw: a wave (up) or to the mouth (lick)."""
    sx = 1 if side == "l" else -1
    rot(f"{side}_hum", X, -(55 + 25 * lick) * up)
    rot(f"{side}_elb", X, (35 + 60 * lick) * up)
    rot(f"{side}_wri", X, (25 + 20 * lick) * up)
    if lick:
        rot(f"{side}_hum", Z, -sx * 18 * lick)

def stand_gait(phase=0.0, gait="walk"):
    """Standing on four legs (the rig's rest pose), legs swinging for a walk or a run."""
    reset()
    run = gait == "run"
    amp = 32 if run else 20
    pairs = ({"l_hum": 0.0, "r_hum": 0.08, "l_fem": 0.5, "r_fem": 0.58} if run else
             {"l_hum": 0.0, "r_hum": 0.5, "l_fem": 0.5, "r_fem": 0.0})
    for bone, off in pairs.items():
        a = 2 * math.pi * (phase + off)
        swing = amp * math.sin(a)
        lift = max(0.0, math.cos(a))
        rot(bone, X, -swing)                        # forward / back
        if bone.endswith("hum"):
            rot(bone.replace("hum", "elb"), X, 45 * lift)       # front foot folds up while it swings forward
            rot(bone.replace("hum", "wri"), X, -25 * lift)
        else:
            rot(bone.replace("fem", "knee"), X, -40 * lift)
            rot(bone.replace("fem", "ank"), X, 35 * lift)
    if run:
        flex = 10 * math.sin(2 * math.pi * phase)
        rot("s2", X, flex); rot("neckb", X, 8)
    else:
        rot("neckb", X, 6)
    # tail held up in a relaxed curve
    rot("t1", X, 35 if not run else 15)
    for i in range(2, 7):
        rot(f"t{i}", X, 10 if not run else 4)
    ground()

def loaf():
    """Lying down with the paws tucked under, ready to doze."""
    reset()
    for s in ("l", "r"):
        rot(f"{s}_hum", X, 65); rot(f"{s}_elb", X, -120); rot(f"{s}_wri", X, 60)
        rot(f"{s}_fem", X, -55); rot(f"{s}_knee", X, 115); rot(f"{s}_ank", X, -55)
    rot("neckb", X, 24); rot("head", X, 14)
    rot("t1", X, -12); rot("t1", Z, -60)
    for i, d in enumerate((-35, -35, -32, -30, -25)):
        rot(f"t{i + 2}", Z, d)
    ground()

def pose(name, P=None):
    """Every frame Popper uses, by name."""
    P = dict(P or {})
    bpy.data.objects["Real_root"].rotation_euler.x = 0
    set_yaw(0)          # pose in the model's own frame; the turn to the side comes last
    side = name.endswith("_s") or name.startswith(("walk", "run", "boop", "groom"))
    if name in LIFE:
        bpy.data.objects["Real_root"].rotation_euler.x = 0
        LIFE[name]()
        F = {"eat1": {"eyes": 0.5}, "eat2": {"eyes": 0.6, "jaw": 0.5}, "drink1": {"eyes": 0.6, "jaw": 0.2},
             "drink2": {"eyes": 0.6, "jaw": 0.35, "tongue": 1}, "scratch1": {"ears": 0.5}, "scratch2": {"ears": 0.5, "eyes": 0.3},
             "arch": {"ears": -1, "wide": 1, "jaw": 0.6}, "tail1": {}, "tail2": {"eyes": 0.2},
             "rub1": {"eyes": 1}, "rub2": {"eyes": 1}}[name]
        face(F)
        side = name not in FRONT_LIFE
        set_yaw(-90 if side else 0)
        if name.startswith("scratch"):
            ground_on(["l_ball", "r_ball"])
        else:
            ground()
        return side
    if name in PLAY:
        root = bpy.data.objects["Real_root"]
        root.rotation_euler.x = 0
        PLAY[name]()
        if name in ("crouch", "bat1", "bat2"):
            face({"ears": 1, "wide": 1})
        elif name == "stretch":
            face({"eyes": 0.6, "jaw": 0.2})
        elif name.startswith("roll"):
            face({"eyes": 0.5, "jaw": 0.3})
        set_yaw(0 if name.startswith("roll") else -90)
        ground()
        return not name.startswith("roll")
    if name.startswith("walk") or name.startswith("run"):
        gait = "run" if name.startswith("run") else "walk"
        n = 4 if gait == "run" else 6
        stand_gait(int(name[-1]) / n, gait)
    elif name.startswith("sleep"):
        loaf(); face({"eyes": 1})
    else:
        sit(P)
        F = {"sit": {}, "sit_s": {}, "blink": {"eyes": 1}, "blink_s": {"eyes": 1},
             "think": {"tilt": 18, "turn": -15, "look_up": 10}, "talk": {"jaw": 0.7, "ears": 0.5},
             "talk2": {"jaw": 0.3, "ears": 0.5}, "worried": {"ears": -1, "wide": 1},
             "yawn": {"jaw": 1.6, "eyes": 1, "tongue": 1, "look_up": 15},
             "wave1": {"jaw": 0.4, "ears": 0.6}, "wave2": {"jaw": 0.4, "ears": 0.6},
             "lick1": {"eyes": 0.7, "tongue": 1, "jaw": 0.3}, "lick2": {"eyes": 1, "tongue": 1, "jaw": 0.4},
             "boop": {"ears": 0.6, "eyes": 0.3}, "groom1": {"eyes": 0.6, "tongue": 1, "jaw": 0.3},
             "groom2": {"eyes": 0.8, "tongue": 1, "jaw": 0.35}, "groomed": {"eyes": 1, "tilt": -12}}[name]
        if name.startswith("wave"):
            paw_up("l", 0.6 if name == "wave1" else 1.0)
        if name.startswith("lick"):
            rot("neckb", X, 14); rot("head", X, 14); rot("head", Z, 12)
            paw_up("l", 1.0, lick=0.7 if name == "lick1" else 1.0)
        if name == "boop":
            rot("neckb", X, -14); rot("neck", X, -8)          # neck stretched forward to touch noses
        if name.startswith("groom") and name != "groomed":
            rot("neckb", X, 22 if name == "groom1" else 30); rot("head", X, 10)
        face(F)
        if name.startswith(("wave", "lick")):
            ground_on(["r_palm"])
    set_yaw(-90 if side else 0)
    return side


# body types: root scale in the root's own axes (X = length, Y = width, Z = height), head size, fur
TYPES = {
    "adult":  {"scale": (1.00, 1.00, 1.00), "head": 1.00, "fur": 0.0040, "fluff": 0.0},
    "kitten": {"scale": (0.70, 0.72, 0.70), "head": 1.28, "fur": 0.0045, "fluff": 0.35},
    "slim":   {"scale": (1.05, 0.85, 1.06), "head": 0.95, "fur": 0.0030, "fluff": 0.0},
    "fluffy": {"scale": (1.02, 1.10, 1.00), "head": 1.05, "fur": 0.0110, "fluff": 1.0},
}
BASE_SCALE = 0.0085

def apply_type(name):
    t = TYPES[name]
    root = bpy.data.objects["Real_root"]
    root.scale = tuple(BASE_SCALE * s for s in t["scale"])
    bpy.context.view_layer.update()

def head_size(name):
    pb = arm().pose.bones[B["head"]]
    k = TYPES[name]["head"]
    pb.scale = (k, k, k)
    bpy.context.view_layer.update()


# ---------- play: stalking, pouncing, swatting, stretching, rolling

def crouch(ears=1.0):
    """Low to the ground, hind legs bunched: stalking a toy."""
    reset()
    for s in ("l", "r"):
        rot(f"{s}_hum", X, 35); rot(f"{s}_elb", X, -70); rot(f"{s}_wri", X, 35)
        rot(f"{s}_fem", X, -30); rot(f"{s}_knee", X, 75); rot(f"{s}_ank", X, -45)
    rot("s1", X, 6)
    rot("neckb", X, -4); rot("head", X, 8)
    rot("t1", X, -18)
    for i in range(2, 7):
        rot(f"t{i}", X, -3)

def pounce():
    """Mid-leap: front legs reaching, hind legs pushing off."""
    reset()
    rot("s1", X, -12)
    for s in ("l", "r"):
        rot(f"{s}_hum", X, -60); rot(f"{s}_elb", X, 25); rot(f"{s}_wri", X, 20)
        rot(f"{s}_fem", X, 45); rot(f"{s}_knee", X, -25); rot(f"{s}_ank", X, 30)
    rot("neckb", X, 4)
    rot("t1", X, 5)

def swat(stage):
    """Crouched, one front paw out at a toy: stage 1 lifting, stage 2 striking low and forward."""
    crouch()
    if stage == 1:     # paw drawn up high, ready
        rot("l_hum", X, -115); rot("l_elb", X, 120); rot("l_wri", X, -20)
    else:              # striking forward and down
        rot("l_hum", X, -100); rot("l_elb", X, 45); rot("l_wri", X, -25)

def stretch():
    """The play bow: front legs straight out along the ground, chest down, rear up."""
    reset()
    rot("s1", X, 18)
    for s in ("l", "r"):
        rot(f"{s}_hum", X, -70); rot(f"{s}_elb", X, 10); rot(f"{s}_wri", X, 25)
    rot("neckb", X, -22); rot("head", X, -8)
    rot("t1", X, 40)
    for i in range(2, 7):
        rot(f"t{i}", X, 6)

def roll(stage):
    """Rolling about: on its side (1), on its back with paws up (2)."""
    loaf()
    for s in ("l", "r"):
        rot(f"{s}_hum", X, -60); rot(f"{s}_elb", X, 70)
        rot(f"{s}_fem", X, 30); rot(f"{s}_knee", X, -50)
    root = bpy.data.objects["Real_root"]
    root.rotation_euler.x = math.radians(80 if stage == 1 else 150)
    bpy.context.view_layer.update()
    ground()


# ---------- daily life: eating, drinking, scratching, arching, tail swish, face rubbing

def eat(stage):
    """Standing over a bowl, head down in it; stage 2 chewing (jaw open)."""
    reset()
    for s in ("l", "r"):
        rot(f"{s}_hum", X, 12); rot(f"{s}_elb", X, -22); rot(f"{s}_wri", X, 12)
    rot("s4", X, 10)
    rot("neckb", X, 48); rot("neck", X, 12); rot("head", X, 18 if stage == 1 else 12)
    rot("t1", X, 10)
    for i in range(2, 7):
        rot(f"t{i}", X, -6)

def drink(stage):
    """Crouched by the water bowl, head low and forward, lapping (tongue out on stage 2)."""
    reset()
    for s in ("l", "r"):
        rot(f"{s}_hum", X, 28); rot(f"{s}_elb", X, -55); rot(f"{s}_wri", X, 30)
        rot(f"{s}_fem", X, -35); rot(f"{s}_knee", X, 85); rot(f"{s}_ank", X, -50)
    rot("neckb", X, 30); rot("head", X, 20)
    rot("t1", X, -15)
    for i in range(2, 7):
        rot(f"t{i}", Z, -12)

def scratch(stage):
    """Up on the hind legs, front paws high on the post, pulling down (stage 2 lower)."""
    reset()
    rot("body", X, -62)                       # the whole cat rears up, pivoting at the hips
    for s in ("l", "r"):
        rot(f"{s}_fem", X, 55); rot(f"{s}_knee", X, -20); rot(f"{s}_ank", X, -10)
        up = -40 if stage == 1 else -20
        rot(f"{s}_hum", X, up); rot(f"{s}_elb", X, 20 if stage == 1 else 45); rot(f"{s}_wri", X, -30)
    rot("neckb", X, 35); rot("head", X, 10)
    rot("t1", X, 75)                          # tail back along the floor behind it
    for i in range(2, 7):
        rot(f"t{i}", X, 4)

def arch():
    """Startled: back humped high in the middle, legs straight and drawn together, tail up."""
    reset()
    rot("s2", X, -28)                         # the back rises from the hips...
    rot("s4", X, 40)                          # ...and comes down again to the shoulders: a hump
    for s in ("l", "r"):
        rot(f"{s}_hum", X, -20); rot(f"{s}_elb", X, 6)     # front legs straight, pulled back under
        rot(f"{s}_fem", X, -14); rot(f"{s}_knee", X, 10)   # hind legs straight, pulled forward
    rot("neckb", X, -6); rot("head", X, 18)
    rot("t1", X, 70)
    for i in range(2, 7):
        rot(f"t{i}", X, 4)

def tail_swish(stage):
    """Sitting, the tail lifted off the ground and swept to one side or the other."""
    sit({})
    side = -1 if stage == 1 else 1
    rot("t2", X, 25); rot("t3", Z, side * 25); rot("t4", Z, side * 25); rot("t5", X, 15)

def rub(stage):
    """Sitting side-on, head tilted and pushed forward to rub cheeks with the other cat, eyes closed."""
    sit({})
    rot("neckb", X, -10); rot("neck", X, -6)
    rot("head", Y, 22 if stage == 1 else 10); rot("head", Z, 10 if stage == 1 else -6)

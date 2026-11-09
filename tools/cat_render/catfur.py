
import bpy
from mathutils import Vector

EYES = [Vector((0.0102, -0.1072, 0.1436)), Vector((-0.0102, -0.1072, 0.1436))]
NOSE = Vector((0.0, -0.1218, 0.1364))

def skin_material(coat_key):
    m = bpy.data.materials.get("RealSkin") or bpy.data.materials.new("RealSkin")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (200, 0)
    tx = nt.nodes.new("ShaderNodeTexImage"); tx.location = (-200, 0); tx.image = bpy.data.images[f"coat_{coat_key}"]
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.location = (-400, 0); uv.uv_map = "UVMap"
    nt.links.new(uv.outputs[0], tx.inputs["Vector"]); nt.links.new(tx.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    b.inputs["Roughness"].default_value = 0.8
    b.inputs["Specular IOR Level"].default_value = 0.3
    b.inputs["Sheen Weight"].default_value = 0.15
    return m

def fur_groups(ob):
    """Where fur grows and how long, from each vertex's rest position."""
    me = ob.data
    rest = [Vector(d.vector) for d in me.attributes["rest"].data]
    for g in ("fur_density", "fur_length"):
        if g in ob.vertex_groups:
            ob.vertex_groups.remove(ob.vertex_groups[g])
    dens = ob.vertex_groups.new(name="fur_density"); ln = ob.vertex_groups.new(name="fur_length")
    for i, p in enumerate(rest):
        d = 1.0
        for c, r in [(EYES[0], 0.0085), (EYES[1], 0.0085), (NOSE, 0.0050)]:
            d = min(d, max(0.0, min(1.0, ((p - c).length - r) / 0.003)))
        if p.z > 0.158 and p.y < -0.088:     # inside of the ears
            d = min(d, 0.15)
        if p.z < 0.004:                      # paw pads
            d = 0.0
        l = 1.0
        fd = (p - NOSE).length
        if fd < 0.035:
            l = 0.35 + 0.65 * fd / 0.035     # short fur on the face
        if p.z > 0.150 and abs(p.x) > 0.008 and p.y > -0.11:
            l = min(l, 0.4)                  # ears
        if p.z < 0.03:
            l = min(l, 0.6)                  # paws
        dens.add([i], d, "REPLACE"); ln.add([i], l, "REPLACE")

def add_fur(ob, length=0.0040, fluff=0.0, count=260000):
    for m in list(ob.modifiers):
        if m.type == "PARTICLE_SYSTEM":
            ob.modifiers.remove(m)
    fur_groups(ob)
    mod = ob.modifiers.new("fur", "PARTICLE_SYSTEM")
    ps = mod.particle_system
    s = ps.settings
    s.type = "HAIR"; s.count = count; s.hair_length = length
    s.use_advanced_hair = True; s.emit_from = "FACE"; s.use_emit_random = True
    # measured: strand length (world metres) ~= emission velocity / 0.2424; thickness and roughness are in the
    # rig's own units, which are 1/0.0085 of a metre
    k = 1.0 / 0.0085
    v = length * 0.2424
    s.normal_factor = v * (1.0 + 0.3 * fluff); s.factor_random = v * 0.25
    s.tangent_factor = 0.0
    s.child_type = "INTERPOLATED"; s.child_percent = 4; s.rendered_child_count = 6 + int(6 * fluff)
    s.child_length = 0.9; s.child_length_threshold = 0.3; s.clump_factor = 0.08 + 0.25 * fluff
    s.roughness_1 = 0.00025 * k * (1 + 2 * fluff); s.roughness_endpoint = 0.0002 * k * (1 + 3 * fluff)
    s.root_radius = 1.0; s.tip_radius = 0.05; s.radius_scale = 0.000055 * k * (1 + 0.4 * fluff)
    s.display_step = 3; s.render_step = 4
    s.material_slot = ob.data.materials[0].name
    ps.vertex_group_density = "fur_density"
    ps.vertex_group_length = "fur_length"
    return ps

"""Shared pipeline for the forest_ruins asset set.

Builders make mid-poly meshes with procedural materials; produce() bakes those
materials to an albedo + normal texture set, exports one .glb per asset and
renders a preview. Run through build.py.
"""

import math
import os

import bmesh
import bpy
from mathutils import Vector, noise

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.dirname(SRC_DIR)
TEX_DIR = os.path.join(SRC_DIR, "textures")
PREVIEW_DIR = os.path.join(SRC_DIR, "previews")


# --- palette (sRGB hex, sampled from the reference painting) -----------------

def lin(hex_str):
    """sRGB hex -> linear RGBA tuple for node sockets."""
    h = hex_str.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


STONE = ("#4f565d", "#77766f", "#a3a197", "#c2bfb2")   # dark (blue-grey) .. highlight
MOSS = ("#33501f", "#577f2b", "#7ea43a", "#a8c858")
BARK = ("#35261f", "#5e4334", "#87654c", "#a88a6a")
LEAF = ("#22401d", "#3c6b27", "#74a83a", "#b8dc62", "#d9ee8c")
FERN = ("#253f1d", "#3f6a2c", "#6b9a3e", "#a3c85a")
GRASS = ("#33561f", "#5d8e2d", "#a2c84c", "#d2e47e")
DIRT = ("#5b3f29", "#8a6442", "#b48a5c", "#d2ab78")
VINE = ("#3a3a1e", "#5b6a2c", "#7f8f3c")
FLOWER = ("#e8b72c", "#f6dc4a", "#fff3a0", "#d98a24")


# --- scene ------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.unit_settings.system = "METRIC"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    sc.cycles.device = "CPU"
    for kind in ("OPTIX", "CUDA"):
        devices = prefs.get_devices_for_type(kind)
        if any(d.type != "CPU" for d in devices):
            prefs.compute_device_type = kind
            for d in devices:
                d.use = d.type != "CPU"
            sc.cycles.device = "GPU"
            break
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = lin("#c9d6dc")
    bg.inputs["Strength"].default_value = 0.9
    sc.world = world


def collection(name):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def obj_from_bm(name, bm, coll, mat=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if mat:
        me.materials.append(mat)
    return ob


def to_mesh(ob, name=None):
    """Evaluate a curve, metaball or modified object into a plain mesh object."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
    me.transform(ob.matrix_world)
    new = bpy.data.objects.new(name or ob.name + "_m", me)
    for c in ob.users_collection:
        c.objects.link(new)
    bpy.data.objects.remove(ob)
    return new


def select_only(obs):
    bpy.context.view_layer.update()
    for o in bpy.context.scene.objects:
        if o:
            o.select_set(False)
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]


def join(obs, name):
    obs = [o for o in obs if o and o.type == "MESH" and len(o.data.vertices)]
    select_only(obs)
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return ob


def smooth(ob, angle=60):
    me = ob.data
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if hasattr(me, "set_sharp_from_angle"):
        me.set_sharp_from_angle(angle=math.radians(angle))
    me.update()


def decimate(ob, ratio):
    if ratio >= 1:
        return ob
    m = ob.modifiers.new("dec", "DECIMATE")
    m.ratio = ratio
    return apply_mods(ob)


def apply_mods(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def jitter(verts, amount, scale, seed=0.0):
    """Coherent noise displacement: same world point always moves the same way."""
    off = Vector((seed * 7.31, seed * 3.17, seed * 5.71))
    for v in verts:
        v.co += Vector(noise.noise_vector(v.co * scale + off)) * amount


def bevel_sharp(bm, offset, segments=2, min_angle=0.5):
    edges = [e for e in bm.edges if e.is_manifold and e.calc_face_angle(0) > min_angle]
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=offset, segments=segments, profile=0.5,
                        affect="EDGES", clamp_overlap=True)


def box(size, bevel=0.03, segments=2):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if bevel:
        bevel_sharp(bm, bevel, segments)
    return bm


def metaball_mesh(name, coll, elements, resolution, mat, shaggy=0.0):
    """elements: (co, radius) or (co, radius, (sx, sy, sz)) ellipsoids."""
    mb = bpy.data.metaballs.new(name)
    mb.resolution = mb.render_resolution = resolution
    mb.threshold = 0.6
    for el in elements:
        e = mb.elements.new(type="ELLIPSOID" if len(el) > 2 else "BALL")
        e.co = el[0]
        e.radius = el[1]
        if len(el) > 2:
            e.size_x, e.size_y, e.size_z = el[2]
    ob = bpy.data.objects.new(name, mb)
    coll.objects.link(ob)
    mb.materials.append(mat)
    ob = to_mesh(ob, name)
    if shaggy:                         # break up the smooth metaball surface
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        jitter(bm.verts, shaggy, 1.0 / max(resolution * 2.5, 0.01))
        bm.to_mesh(ob.data)
        bm.free()
    return ob


def tube(name, coll, pts, radius, mat, radii=None, bevel_res=2, res_u=3):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = bevel_res
    cu.resolution_u = res_u
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for i, (bp, p) in enumerate(zip(sp.bezier_points, pts)):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
        bp.radius = radii[i] if radii else 1.0
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    return to_mesh(ob, name)


def set_attr(ob, name, values):
    """Per-vertex float attribute, read by shaders through an Attribute node."""
    me = ob.data
    a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
    a.data.foreach_set("value", values)


# --- shader node helpers ----------------------------------------------------

def _sock(sockets, key):
    for s in sockets:
        if s.identifier == key:
            return s
    return sockets[key]


def node(nt, kind, inputs=None, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    for k, v in (inputs or {}).items():
        _sock(n.inputs, k).default_value = v
    return n


def link(nt, out, inp):
    nt.links.new(out, inp)


def ramp(nt, fac, stops, interp="EASE"):
    r = node(nt, "ShaderNodeValToRGB")
    r.color_ramp.interpolation = interp
    els = r.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, col) in zip(els, stops):
        el.position = pos
        el.color = lin(col) if isinstance(col, str) else col
    link(nt, fac, r.inputs["Fac"])
    return r.outputs["Color"]


def mix(nt, fac, a, b, blend="MIX"):
    m = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type=blend)
    for key, v in (("Factor_Float", fac), ("A_Color", a), ("B_Color", b)):
        s = _sock(m.inputs, key)
        if isinstance(v, (int, float, tuple)):
            s.default_value = v
        elif isinstance(v, str):
            s.default_value = lin(v)
        else:
            link(nt, v, s)
    return _sock(m.outputs, "Result_Color")


def math_op(nt, op, a, b=0.0, clamp=False):
    m = node(nt, "ShaderNodeMath", operation=op, use_clamp=clamp)
    for s, v in zip(m.inputs, (a, b)):
        if isinstance(v, (int, float)):
            s.default_value = v
        else:
            link(nt, v, s)
    return m.outputs[0]


def map_range(nt, val, a, b, c=0.0, d=1.0):
    m = node(nt, "ShaderNodeMapRange", inputs={"From Min": a, "From Max": b, "To Min": c,
                                               "To Max": d})
    m.clamp = True
    link(nt, val, m.inputs["Value"])
    return m.outputs["Result"]


def tex_noise(nt, co, scale, detail=4.0, rough=0.55, distortion=0.0, stretch=None):
    if stretch:
        mp = node(nt, "ShaderNodeMapping", inputs={"Scale": stretch})
        link(nt, co, mp.inputs["Vector"])
        co = mp.outputs["Vector"]
    n = node(nt, "ShaderNodeTexNoise", inputs={"Scale": scale, "Detail": detail,
                                              "Roughness": rough, "Distortion": distortion})
    link(nt, co, n.inputs["Vector"])
    return n


def tex_voronoi(nt, co, scale, feature="F1", randomness=1.0):
    v = node(nt, "ShaderNodeTexVoronoi", feature=feature,
             inputs={"Scale": scale, "Randomness": randomness})
    link(nt, co, v.inputs["Vector"])
    return v


def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial")
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", inputs={"Roughness": 0.9})
    link(nt, bsdf.outputs["BSDF"], out.inputs["Surface"])
    co = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    geo = node(nt, "ShaderNodeNewGeometry")
    return mat, nt, bsdf, co, geo


def ao(nt, distance, lo=0.45):
    a = node(nt, "ShaderNodeAmbientOcclusion", samples=16, inputs={"Distance": distance})
    return map_range(nt, a.outputs["AO"], 0.0, 1.0, lo, 1.0)


def finish(nt, bsdf, color, height=None, strength=0.35, distance=0.02):
    link(nt, color, bsdf.inputs["Base Color"])
    if height is not None:
        b = node(nt, "ShaderNodeBump", inputs={"Strength": strength, "Distance": distance})
        link(nt, height, b.inputs["Height"])
        link(nt, b.outputs["Normal"], bsdf.inputs["Normal"])


def up_mask(nt, geo, lo, hi):
    z = node(nt, "ShaderNodeSeparateXYZ")
    link(nt, geo.outputs["Normal"], z.inputs["Vector"])
    return map_range(nt, z.outputs["Z"], lo, hi)


# --- materials --------------------------------------------------------------

def mat_stone(name="stone", moss=0.8, moss_low=0.0, cracks=0.0, scale=1.0):
    """Weathered blue-grey stone; moss creeps over up-facing surfaces (and the base)."""
    mat, nt, bsdf, co, geo = new_material(name)
    if scale != 1.0:
        sc = node(nt, "ShaderNodeVectorMath", operation="SCALE", inputs={"Scale": scale})
        link(nt, co, sc.inputs[0])
        co = sc.outputs["Vector"]
    n1 = tex_noise(nt, co, 1.8, detail=6, rough=0.6)
    base = ramp(nt, n1.outputs["Fac"], [(0.3, STONE[0]), (0.56, STONE[1]), (0.8, STONE[2])])
    blot = node(nt, "ShaderNodeSeparateColor")
    link(nt, tex_voronoi(nt, co, 2.5).outputs["Color"], blot.inputs["Color"])
    blot_col = ramp(nt, blot.outputs[0], [(0.0, STONE[0]), (1.0, STONE[2])], "LINEAR")
    base = mix(nt, 0.25, base, blot_col)
    edge = map_range(nt, geo.outputs["Pointiness"], 0.5, 0.58)
    base = mix(nt, math_op(nt, "MULTIPLY", edge, 0.45), base, STONE[3])
    streak = tex_noise(nt, co, 3.0, detail=3, stretch=(1.0, 1.0, 0.18))
    base = mix(nt, map_range(nt, streak.outputs["Fac"], 0.55, 0.75, 0.0, 0.35), base,
               STONE[0], "MULTIPLY")
    if moss:
        mn = tex_noise(nt, co, 1.2, detail=2)
        fringe = tex_noise(nt, co, 9.0, detail=4)
        mval = math_op(nt, "ADD", mn.outputs["Fac"],
                       math_op(nt, "MULTIPLY", fringe.outputs["Fac"], 0.25))
        patch = map_range(nt, mval, 0.48, 0.54)
        mask = math_op(nt, "MULTIPLY", up_mask(nt, geo, 0.32, 0.55), patch)
        if moss_low:
            pz = node(nt, "ShaderNodeSeparateXYZ")
            link(nt, geo.outputs["Position"], pz.inputs["Vector"])
            low = math_op(nt, "MULTIPLY", map_range(nt, pz.outputs["Z"], 0.0, moss_low, 1.0, 0.0),
                          patch)
            mask = math_op(nt, "MAXIMUM", mask, low)
        mcol = ramp(nt, tex_noise(nt, co, 9.0, detail=6).outputs["Fac"],
                    [(0.35, MOSS[1]), (0.55, MOSS[2]), (0.7, MOSS[3])])
        base = mix(nt, math_op(nt, "MULTIPLY", mask, moss, clamp=True), base, mcol)
    base = mix(nt, 1.0, base, ao(nt, 0.4), "MULTIPLY")
    h = n1.outputs["Fac"]
    if cracks:
        cr = tex_voronoi(nt, tex_noise(nt, co, 0.8, detail=2, distortion=1.5).outputs["Color"],
                         1.4, feature="DISTANCE_TO_EDGE")
        line = map_range(nt, cr.outputs["Distance"], 0.0, 0.025, 1.0, 0.0)
        base = mix(nt, math_op(nt, "MULTIPLY", line, cracks), base, STONE[0])
        h = math_op(nt, "SUBTRACT", h, math_op(nt, "MULTIPLY", line, cracks * 0.6))
    finish(nt, bsdf, base, h, 0.3, 0.03)
    return mat


def mat_moss(name="moss"):
    mat, nt, bsdf, co, geo = new_material(name)
    n = tex_noise(nt, co, 7.0, detail=8, rough=0.65)
    col = ramp(nt, n.outputs["Fac"], [(0.3, MOSS[0]), (0.48, MOSS[1]), (0.62, MOSS[2])])
    col = mix(nt, math_op(nt, "MULTIPLY", up_mask(nt, geo, 0.2, 0.95), 0.75), col, MOSS[3],
              "SCREEN")
    col = mix(nt, 1.0, col, ao(nt, 0.3, 0.35), "MULTIPLY")
    fuzz = tex_noise(nt, co, 40.0, detail=4)
    finish(nt, bsdf, col, math_op(nt, "ADD", n.outputs["Fac"], fuzz.outputs["Fac"]), 0.6, 0.02)
    bsdf.inputs["Roughness"].default_value = 1.0
    return mat


def mat_bark(name="bark", moss=0.0, moss_low=0.0, palette=BARK):
    mat, nt, bsdf, co, geo = new_material(name)
    fib = tex_noise(nt, co, 4.0, detail=8, distortion=0.4, stretch=(5.0, 5.0, 0.6))
    col = ramp(nt, fib.outputs["Fac"],
               [(0.32 + 0.48 * i / (len(palette) - 1), p) for i, p in enumerate(palette)])
    if moss or moss_low:
        pz = node(nt, "ShaderNodeSeparateXYZ")
        link(nt, geo.outputs["Position"], pz.inputs["Vector"])
        patch = map_range(nt, tex_noise(nt, co, 1.6, detail=4).outputs["Fac"], 0.38, 0.55)
        mask = math_op(nt, "MULTIPLY", up_mask(nt, geo, 0.1, 0.6), moss)
        if moss_low:
            mask = math_op(nt, "MAXIMUM", mask, map_range(nt, pz.outputs["Z"], 0.0, moss_low,
                                                          1.0, 0.0))
        mask = math_op(nt, "MULTIPLY", mask, patch, clamp=True)
        mcol = ramp(nt, tex_noise(nt, co, 10.0, detail=6).outputs["Fac"],
                    [(0.35, MOSS[0]), (0.55, MOSS[1]), (0.72, MOSS[2])])
        col = mix(nt, mask, col, mcol)
    col = mix(nt, 1.0, col, ao(nt, 0.5, 0.35), "MULTIPLY")
    finish(nt, bsdf, col, fib.outputs["Fac"], 0.6, 0.03)
    return mat


def mat_canopy(name="canopy", palette=LEAF):
    """Puffy painted foliage: light tops, cool shadowed undersides, leaf-cell pattern."""
    mat, nt, bsdf, co, geo = new_material(name)
    cells = tex_voronoi(nt, co, 7.0)
    cell_rand = node(nt, "ShaderNodeSeparateColor")
    link(nt, cells.outputs["Color"], cell_rand.inputs["Color"])
    up = up_mask(nt, geo, -0.7, 0.95)
    key = node(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")   # painted key light
    link(nt, geo.outputs["Normal"], key.inputs[0])
    key.inputs[1].default_value = Vector((-0.45, -0.35, 0.82)).normalized()
    sun = map_range(nt, key.outputs["Value"], -0.2, 0.95)
    shade = math_op(nt, "ADD", math_op(nt, "MULTIPLY", up, 0.55),
                    math_op(nt, "MULTIPLY", sun, 0.3))
    shade = math_op(nt, "ADD", shade, math_op(nt, "MULTIPLY", cell_rand.outputs[0], 0.15))
    # overlapping leaf scales: each cell is lit at its top and shadowed at its lower edge
    leaf_scale = 5.5
    lv = tex_voronoi(nt, co, leaf_scale)
    rel = node(nt, "ShaderNodeVectorMath", operation="SUBTRACT")
    link(nt, co, rel.inputs[0])
    link(nt, lv.outputs["Position"], rel.inputs[1])
    rz = node(nt, "ShaderNodeSeparateXYZ")
    link(nt, rel.outputs["Vector"], rz.inputs["Vector"])
    leaf = map_range(nt, math_op(nt, "MULTIPLY", rz.outputs["Z"], leaf_scale), -0.6, 0.6,
                     -0.12, 0.12)
    shade = math_op(nt, "ADD", shade, leaf)
    gaps = tex_voronoi(nt, co, leaf_scale, feature="DISTANCE_TO_EDGE")
    shade = math_op(nt, "MULTIPLY", shade,
                    map_range(nt, gaps.outputs["Distance"], 0.0, 0.07, 0.8, 1.0))
    a = node(nt, "ShaderNodeAmbientOcclusion", samples=16, inputs={"Distance": 0.9})
    shade = math_op(nt, "MULTIPLY", shade, map_range(nt, a.outputs["AO"], 0, 1, 0.25, 1.05))
    col = ramp(nt, shade, [(0.08, palette[0]), (0.3, palette[1]), (0.52, palette[2]),
                           (0.74, palette[3]), (0.92, palette[4])])
    leafy = tex_voronoi(nt, co, 22.0)
    h = math_op(nt, "ADD", math_op(nt, "MULTIPLY", cells.outputs["Distance"], -1.0),
                math_op(nt, "MULTIPLY", leafy.outputs["Distance"], -0.4))
    finish(nt, bsdf, col, h, 0.5, 0.05)
    bsdf.inputs["Roughness"].default_value = 0.8
    return mat


def mat_gradient(name, stops, attr="grad", ao_dist=0.15, vein=0.0):
    """Plants: colour runs base -> tip along a per-vertex 'grad' attribute."""
    mat, nt, bsdf, co, geo = new_material(name)
    g = node(nt, "ShaderNodeAttribute", attribute_name=attr)
    n = tex_noise(nt, co, 6.0, detail=3)
    val = math_op(nt, "ADD", g.outputs["Fac"],
                  math_op(nt, "MULTIPLY", math_op(nt, "SUBTRACT", n.outputs["Fac"], 0.5), 0.25))
    col = ramp(nt, val, stops)
    if vein:
        v = node(nt, "ShaderNodeAttribute", attribute_name="vein")
        col = mix(nt, math_op(nt, "MULTIPLY", v.outputs["Fac"], vein), col, stops[-1][1])
    col = mix(nt, 1.0, col, ao(nt, ao_dist, 0.4), "MULTIPLY")
    finish(nt, bsdf, col, n.outputs["Fac"], 0.2, 0.01)
    bsdf.inputs["Roughness"].default_value = 0.7
    return mat


def mat_dirt(name="dirt"):
    mat, nt, bsdf, co, geo = new_material(name)
    n = tex_noise(nt, co, 1.2, detail=6)
    col = ramp(nt, n.outputs["Fac"], [(0.35, DIRT[1]), (0.55, DIRT[2]), (0.7, DIRT[3])])
    peb = tex_voronoi(nt, co, 14.0)
    pmask = map_range(nt, peb.outputs["Distance"], 0.18, 0.1)
    col = mix(nt, math_op(nt, "MULTIPLY", pmask, 0.6), col, "#9a8d7c")
    edge = node(nt, "ShaderNodeAttribute", attribute_name="edge")
    col = mix(nt, math_op(nt, "MULTIPLY", edge.outputs["Fac"], 0.85), col, DIRT[0])
    grassy = math_op(nt, "MULTIPLY", edge.outputs["Fac"],
                     map_range(nt, tex_noise(nt, co, 3.0).outputs["Fac"], 0.45, 0.6))
    col = mix(nt, grassy, col, GRASS[1])
    col = mix(nt, 1.0, col, ao(nt, 0.2, 0.6), "MULTIPLY")
    h = math_op(nt, "ADD", n.outputs["Fac"], math_op(nt, "MULTIPLY", pmask, 0.6))
    finish(nt, bsdf, col, h, 0.5, 0.02)
    bsdf.inputs["Roughness"].default_value = 1.0
    return mat


def mat_flat(name, hex_col, rough=0.8):
    mat, nt, bsdf, co, geo = new_material(name)
    finish(nt, bsdf, mix(nt, 1.0, lin(hex_col), ao(nt, 0.1, 0.6), "MULTIPLY"))
    bsdf.inputs["Roughness"].default_value = rough
    return mat


# --- bake / export / preview -----------------------------------------------

def uv_unwrap(ob, margin=0.003):
    select_only([ob])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin,
                             scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def bake(ob, name, size, double_sided=False):
    """Bake every procedural material on ob into one albedo + normal pair."""
    sc = bpy.context.scene
    uv_unwrap(ob)
    mats = [m for m in ob.data.materials if m]
    images = {}
    for kind, samples in (("albedo", 24), ("normal", 6)):
        img = bpy.data.images.new(f"{name}_{kind}", size, size)
        if kind == "normal":
            img.colorspace_settings.name = "Non-Color"
        for m in mats:
            nt = m.node_tree
            tn = nt.nodes.get("BAKE") or nt.nodes.new("ShaderNodeTexImage")
            tn.name = "BAKE"
            tn.image = img
            nt.nodes.active = tn
        sc.cycles.samples = samples
        select_only([ob])
        if kind == "albedo":
            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=16,
                                use_clear=True)
        else:
            bpy.ops.object.bake(type="NORMAL", margin=16, use_clear=True)
        img.filepath_raw = os.path.join(TEX_DIR, f"{name}_{kind}.png")
        img.file_format = "PNG"
        img.save()
        images[kind] = img

    mat, nt, bsdf, co, geo = new_material(f"{name}_mat")
    alb = node(nt, "ShaderNodeTexImage", image=images["albedo"])
    link(nt, alb.outputs["Color"], bsdf.inputs["Base Color"])
    nrm = node(nt, "ShaderNodeTexImage", image=images["normal"])
    nmap = node(nt, "ShaderNodeNormalMap")
    link(nt, nrm.outputs["Color"], nmap.inputs["Color"])
    link(nt, nmap.outputs["Normal"], bsdf.inputs["Normal"])
    mat.use_backface_culling = not double_sided
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    for m in mats:
        if m.users == 0:
            bpy.data.materials.remove(m)


def export_glb(ob, name):
    select_only([ob])
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT_DIR, name + ".glb"),
                              export_format="GLB", use_selection=True, export_apply=True,
                              export_yup=True)


def preview(ob, name, view=(1.0, -1.6, 0.65), samples=48):
    sc = bpy.context.scene
    hidden = [o for o in sc.objects if o is not ob and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center, radius = (lo + hi) / 2, (hi - lo).length / 2
    cam_data = bpy.data.cameras.new("pcam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("pcam", cam_data)
    sc.collection.objects.link(cam)
    d = Vector(view).normalized()
    fov = 2 * math.atan(18 / cam_data.lens)
    cam.location = center + d * (radius / math.tan(fov / 2) * 1.05)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sun_data = bpy.data.lights.new("psun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(8)
    sun = bpy.data.objects.new("psun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-18), math.radians(-35))
    sc.collection.objects.link(sun)
    sc.camera = cam
    sc.render.resolution_x = sc.render.resolution_y = 900
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
    sc.render.filepath = os.path.join(PREVIEW_DIR, name + ".png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)
    bpy.data.objects.remove(sun)
    for o in hidden:
        o.hide_render = False


def produce(name, builder, tex_size, double_sided=False, slot=0, view=None):
    """Build -> bake -> export -> preview one asset; returns the final object."""
    coll = collection(name)
    ob = builder(coll)
    ob.name = ob.data.name = name
    bake(ob, name, tex_size, double_sided)
    export_glb(ob, name)
    preview(ob, name, view or (1.0, -1.6, 0.65))
    print(f"ASSET {name}: {tris(ob)} tris, {tex_size}px, "
          f"{(ob.dimensions.x, ob.dimensions.y, ob.dimensions.z)}")
    ob.location = ((slot % 5) * 12.0, -(slot // 5) * 12.0, 0)   # .blend layout only, after export
    bpy.data.orphans_purge(do_recursive=True)
    return ob

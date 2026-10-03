"""Broadleaf trees with puffy clumped canopies (reference: refs/tree_*.png, trunk_right.png).

Trunk and branches are a skin-modifier skeleton; the canopy is fused metaball clumps
with smaller lumps on their outer faces, like the painted cauliflower canopies.
"""

import math
import random

import bmesh
import bpy
from mathutils import Vector

import common as c


def skeleton(rng, height_fork, r_base, r_fork, n_branch, branch_len, n_roots, lean=0.06):
    verts, radii, edges = [], [], []

    def add(p, r, parent=None):
        verts.append(p.copy())
        radii.append(r)
        if parent is not None:
            edges.append((parent, len(verts) - 1))
        return len(verts) - 1

    def limb(i, p, d, length, r0, r1, segs, bend):
        for s in range(1, segs + 1):
            d = (d + Vector([rng.uniform(-bend, bend) for _ in range(3)])).normalized()
            p = p + d * (length / segs)
            i = add(p, r0 + (r1 - r0) * s / segs, i)
        return i, p, d

    root = add(Vector((0, 0, -0.12)), r_base * 1.2)
    collar = add(Vector((0, 0, r_base * 0.9)), r_base * 1.08, root)   # roots spring from here
    for k in range(n_roots):                                   # buttress roots
        a = 2 * math.pi * (k + rng.uniform(-0.2, 0.2)) / n_roots
        d = Vector((math.cos(a), math.sin(a), -0.5)).normalized()
        limb(collar, Vector((0, 0, r_base * 0.9)), d, r_base * rng.uniform(2.2, 3.0),
             r_base * 0.62, r_base * 0.18, 3, 0.08)
    trunk_dir = Vector((rng.uniform(-lean, lean), rng.uniform(-lean, lean), 1)).normalized()
    fork, top, _ = limb(collar, Vector((0, 0, r_base * 0.9)), trunk_dir,
                        height_fork - r_base * 0.9, r_base, r_fork, 5, 0.05)
    tips = []
    for k in range(n_branch):
        a = 2 * math.pi * (k + rng.uniform(-0.15, 0.15)) / n_branch
        elev = math.radians(rng.uniform(42, 62))
        d = Vector((math.cos(a) * math.cos(elev), math.sin(a) * math.cos(elev),
                    math.sin(elev)))
        bi, bp, bd = limb(fork, top, d, branch_len, r_fork * 0.72, r_fork * 0.4, 3, 0.12)
        for side in (-1, 1):                                   # each branch forks once
            sd = (bd + Vector((-bd.y, bd.x, 0)) * 0.55 * side + Vector((0, 0, 0.3))).normalized()
            _, tp, _ = limb(bi, bp, sd, branch_len * 0.6, r_fork * 0.35, r_fork * 0.1, 2, 0.1)
            tips.append(tp)
    return verts, edges, radii, tips


def trunk_mesh(coll, rng, mat, trunk_tris=2500, **kw):
    verts, edges, radii, tips = skeleton(rng, **kw)
    me = bpy.data.meshes.new("trunk")
    me.from_pydata([tuple(v) for v in verts], edges, [])
    ob = bpy.data.objects.new("trunk", me)
    coll.objects.link(ob)
    skin = ob.modifiers.new("skin", "SKIN")
    skin.branch_smoothing = 0.6
    for sv, r in zip(me.skin_vertices[0].data, radii):
        sv.radius = (r, r)
    me.skin_vertices[0].data[0].use_root = True
    ob.modifiers.new("sub", "SUBSURF").levels = 1
    ob = c.apply_mods(ob)
    ob = c.decimate(ob, trunk_tris / max(c.tris(ob), 1))
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    c.jitter(bm.verts, kw["r_base"] * 0.12, 1.6 / kw["r_base"])
    bm.to_mesh(ob.data)
    bm.free()
    me = ob.data
    me.materials.append(mat)
    return ob, tips


def canopy(coll, rng, center, radii, tips, mat, res, target_tris, clumps=26, core=0.85):
    els = []
    rx, ry, rz = radii
    base = min(radii)
    for k in range(4):                                         # core fill
        els.append((center + Vector((rng.uniform(-0.3, 0.3) * rx, rng.uniform(-0.3, 0.3) * ry,
                                     rng.uniform(-0.2, 0.2) * rz)), base * core))
    golden = math.pi * (3 - math.sqrt(5))
    for k in range(clumps):                                    # clumps on a shell
        z = 1 - 2 * (k + 0.5) / clumps
        z = z * 0.9 + 0.1 if z < 0 else z                      # flatter underside
        r = math.sqrt(max(0.0, 1 - z * z))
        a = golden * k + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(a) * r, math.sin(a) * r, z))
        p = center + Vector((d.x * rx, d.y * ry, d.z * rz)) * rng.uniform(0.55, 0.7)
        cr = base * rng.uniform(0.42, 0.55)
        els.append((p, cr))
        for _ in range(rng.randint(2, 3)):                     # soft cauliflower lumps
            j = (d + Vector([rng.uniform(-0.5, 0.5) for _ in range(3)])).normalized()
            els.append((p + j * cr * 0.55, cr * rng.uniform(0.5, 0.65)))
    for tp in tips:                                            # make sure branches end inside
        els.append((tp, base * 0.4))
    ob = c.metaball_mesh("canopy", coll, els, res, mat, shaggy=res * 0.35)
    return c.decimate(ob, target_tris / max(c.tris(ob), 1))


def make_tree(seed, fork, r_base, r_fork, n_branch, branch_len, n_roots, crown_z, crown,
              res, canopy_tris, moss_low=0.3, palette=c.LEAF, clumps=26):
    def build(coll):
        rng = random.Random(seed)
        bark = c.mat_bark(f"bark_{seed}", moss=0.25, moss_low=moss_low)
        trunk, tips = trunk_mesh(coll, rng, bark, height_fork=fork, r_base=r_base,
                                 r_fork=r_fork, n_branch=n_branch, branch_len=branch_len,
                                 n_roots=n_roots)
        cen = Vector((sum(t.x for t in tips) / len(tips), sum(t.y for t in tips) / len(tips),
                      crown_z))
        crn = canopy(coll, rng, cen, crown, tips, c.mat_canopy(f"leaf_{seed}", palette), res,
                     canopy_tris, clumps)
        ob = c.join([trunk, crn], "tree")
        c.smooth(ob, 180)
        return ob
    return build


ASSETS = {
    "tree_broadleaf_large": (make_tree(101, fork=3.6, r_base=0.36, r_fork=0.26, n_branch=3,
                                       branch_len=2.2, n_roots=5, crown_z=7.0,
                                       crown=(3.3, 3.1, 2.6), res=0.13, canopy_tris=9000,
                                       clumps=30), 2048, False),
    "tree_broadleaf_medium": (make_tree(202, fork=2.6, r_base=0.28, r_fork=0.2, n_branch=3,
                                        branch_len=1.5, n_roots=0, crown_z=5.0,
                                        crown=(2.4, 2.2, 2.0), res=0.1, canopy_tris=7000),
                              2048, False),
    "tree_broadleaf_small": (make_tree(303, fork=1.5, r_base=0.16, r_fork=0.12, n_branch=2,
                                       branch_len=0.9, n_roots=0, crown_z=3.2,
                                       crown=(1.45, 1.35, 1.3), res=0.065, canopy_tris=4500,
                                       clumps=18), 1024, False),
    "tree_ancient": (make_tree(404, fork=5.5, r_base=1.1, r_fork=0.65, n_branch=4,
                               branch_len=3.0, n_roots=7, crown_z=10.5,
                               crown=(4.6, 4.3, 3.4), res=0.17, canopy_tris=11000,
                               moss_low=3.0, palette=("#1f3a1b", "#33602a", "#5f9636",
                                                      "#9cc955", "#c8e47c"), clumps=36),
                     2048, False),
}

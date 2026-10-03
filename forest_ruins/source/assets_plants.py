"""Plants and ground pieces: ferns, broad-leaf plant, grass, flowers, bush, hanging vine,
dirt path. Reference: refs/fern_*.png, plant_broad.png, grass_flowers.png, path.png.

Foliage is real geometry (no alpha cards), coloured base -> tip through a 'grad' vertex
attribute that the baked material reads.
"""

import math
import random

import bmesh
import bpy
from mathutils import Vector, noise

import common as c
from assets_rocks import rock_mesh
from assets_trees import canopy

UP = Vector((0, 0, 1))


class MeshBuilder:
    """Collects verts/faces plus per-vertex 'grad' and 'vein' values."""

    def __init__(self):
        self.v, self.f, self.grad, self.vein = [], [], [], []

    def vert(self, co, grad=0.0, vein=0.0):
        self.v.append(tuple(co))
        self.grad.append(grad)
        self.vein.append(vein)
        return len(self.v) - 1

    def face(self, *idx):
        self.f.append(idx)

    def object(self, name, coll, mat):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.update()
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        me.materials.append(mat)
        c.set_attr(ob, "grad", self.grad)
        c.set_attr(ob, "vein", self.vein)
        return ob


def frame(az):
    return Vector((math.cos(az), math.sin(az), 0)), Vector((-math.sin(az), math.cos(az), 0))


# --- fern ---------------------------------------------------------------------

def frond(mb, rng, az, length, pitch, droop, pairs, pinna_len, pinna_w):
    hdir, side = frame(az)

    def rachis(t):
        return hdir * (length * t * math.cos(pitch)) + UP * (length * (t * math.sin(pitch)
                                                                         - droop * t * t))

    for i in range(1, pairs + 1):
        t = i / (pairs + 1)
        p = rachis(t)
        tan = (rachis(min(1.0, t + 0.01)) - rachis(max(0.0, t - 0.01))).normalized()
        plen = pinna_len * (1 - t) ** 0.6 * min(1.0, t * 5)
        if plen < 0.01:
            continue
        for sgn in (-1, 1):
            axis = (side * sgn * 0.85 + tan * 0.55 - UP * 0.12).normalized()
            wv = (tan - axis * tan.dot(axis)).normalized()
            nrm = axis.cross(wv).normalized()
            w = pinna_w * plen
            outline = [(0.0, 0.0), (0.22, 1.0), (0.5, 0.85), (0.78, 0.5), (1.0, 0.0),
                       (0.78, -0.5), (0.5, -0.85), (0.22, -1.0)]
            idx = []
            for s, k in outline:
                k *= rng.uniform(0.88, 1.1)
                idx.append(mb.vert(p + axis * (s * plen) + wv * (k * w),
                                   0.55 * t + 0.45 * s))
            ctr = mb.vert(p + axis * (0.45 * plen) + nrm * (sgn * 0.12 * w), 0.55 * t + 0.2)
            for a, b in zip(idx, idx[1:] + idx[:1]):
                mb.face(ctr, a, b)
    return [rachis(t) for t in (0.0, 0.25, 0.5, 0.75, 1.0)]


def make_fern(seed, fronds, length, upright=(0.95, 1.3), droop=(0.35, 0.6), pairs=13):
    def build(coll):
        rng = random.Random(seed)
        mb, stems = MeshBuilder(), []
        mat = c.mat_gradient("fern", [(0.05, c.FERN[0]), (0.4, c.FERN[1]), (0.75, c.FERN[2]),
                                      (1.0, c.FERN[3])])
        for k in range(fronds):
            az = 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / fronds
            ln = length * rng.uniform(0.75, 1.1)
            pts = frond(mb, rng, az, ln, rng.uniform(*upright), rng.uniform(*droop), pairs,
                        0.2 * ln, 0.24)
            stems.append(c.tube("rachis", coll, pts, 0.008, mat, radii=[1, 0.8, 0.6, 0.4, 0.2],
                                bevel_res=0, res_u=2))
        ob = c.join([mb.object("fern", coll, mat)] + stems, "fern")
        c.smooth(ob, 180)
        return ob
    return build


# --- broad-leaf plant -----------------------------------------------------------

def broad_leaf(mb, rng, az, length, pitch, droop, width, segs=14):
    hdir, side = frame(az)
    phase = rng.uniform(0, 6)

    def ctr(s):
        return hdir * (length * s * math.cos(pitch)) + UP * (length * (s * math.sin(pitch)
                                                                        - droop * s * s))

    rows = []
    for i in range(segs + 1):
        s = i / segs
        cp = ctr(s)
        tan = (ctr(min(1.0, s + 0.01)) - ctr(max(0.0, s - 0.01))).normalized()
        wv = tan.cross(UP).normalized()
        nrm = wv.cross(tan).normalized()
        w = width * max(0.06, math.sin(math.pi * s ** 0.85) ** 0.9)
        wave = 0.07 * w * math.sin(s * 16 + phase)
        rows.append((mb.vert(cp + wv * w + nrm * (wave - 0.1 * w), s),
                     mb.vert(cp, s, 1.0),
                     mb.vert(cp - wv * w + nrm * (-wave - 0.1 * w), s)))
    for (l0, m0, r0), (l1, m1, r1) in zip(rows, rows[1:]):
        mb.face(l0, m0, m1, l1)
        mb.face(m0, r0, r1, m1)


def build_broadleaf(coll):
    rng = random.Random(55)
    mb = MeshBuilder()
    for k in range(9):
        az = 2 * math.pi * (k + rng.uniform(-0.25, 0.25)) / 9
        broad_leaf(mb, rng, az, rng.uniform(0.7, 0.95), math.radians(rng.uniform(48, 72)),
                   rng.uniform(0.35, 0.6), rng.uniform(0.1, 0.14))
    mat = c.mat_gradient("broadleaf", [(0.0, "#2e5222"), (0.35, "#4f8530"), (0.7, "#7fb244"),
                                       (1.0, "#a6cf62")], vein=0.6)
    ob = mb.object("broadleaf", coll, mat)
    c.smooth(ob, 180)
    return ob


# --- grass & flowers -------------------------------------------------------------

def blades(mb, rng, n, h_range, radius, width, lean=(0.15, 0.55), segs=4):
    for _ in range(n):
        a = rng.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(rng.random())
        base = Vector((r * math.cos(a), r * math.sin(a), -0.02))
        out = Vector((math.cos(a), math.sin(a), 0)) + Vector((rng.uniform(-0.4, 0.4),
                                                               rng.uniform(-0.4, 0.4), 0))
        face = rng.uniform(0, math.pi)
        sd = Vector((-math.sin(face), math.cos(face), 0))
        h, ln, w = rng.uniform(*h_range), rng.uniform(*lean), width * rng.uniform(0.75, 1.25)
        row = []
        for k in range(segs + 1):
            s = k / segs
            p = base + out * (ln * h * s * s) + UP * (h * s * (1 - 0.25 * ln * s))
            half = w * (1 - s) ** 0.8 / 2
            row.append((mb.vert(p + sd * half, s), mb.vert(p - sd * half, s)) if k < segs
                       else (mb.vert(p, 1.0),))
        for (a0, b0), nxt in zip(row[:-2], row[1:-1]):
            mb.face(a0, b0, nxt[1], nxt[0])
        mb.face(row[-2][0], row[-2][1], row[-1][0])


def make_grass(seed, n, h_range, radius, width, tips="#d2e47e"):
    def build(coll):
        rng = random.Random(seed)
        mb = MeshBuilder()
        blades(mb, rng, n, h_range, radius, width)
        mat = c.mat_gradient("grass", [(0.0, c.GRASS[0]), (0.45, c.GRASS[1]), (0.8, c.GRASS[2]),
                                       (1.0, tips)], ao_dist=0.08)
        ob = mb.object("grass", coll, mat)
        c.smooth(ob, 180)
        return ob
    return build


def build_flowers(coll):
    rng = random.Random(66)
    leaves, petals = MeshBuilder(), MeshBuilder()
    blades(leaves, rng, 16, (0.12, 0.28), 0.12, 0.03)
    green = c.mat_gradient("flower_leaf", [(0.0, c.GRASS[0]), (0.6, c.GRASS[1]),
                                           (1.0, c.GRASS[2])], ao_dist=0.06)
    centre_mat = c.mat_flat("flower_centre", "#c9741f")
    parts = []
    for _ in range(9):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0.0, 0.14)
        base = Vector((r * math.cos(a), r * math.sin(a), -0.01))
        h = rng.uniform(0.14, 0.3)
        head = base + Vector((rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), h))
        parts.append(c.tube("stem", coll, [base, base.lerp(head, 0.5) + Vector((0.01, 0, 0)),
                                           head], 0.003, green, bevel_res=0, res_u=2))
        tilt = Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 1)).normalized()
        u = tilt.cross(Vector((1, 0, 0))).normalized()
        v = tilt.cross(u)
        n_pet = rng.choice((5, 6))
        for k in range(n_pet):
            ang = 2 * math.pi * k / n_pet
            d = u * math.cos(ang) + v * math.sin(ang)
            sd = tilt.cross(d)
            ln = rng.uniform(0.05, 0.07)
            i0 = petals.vert(head + tilt * 0.004, 0.0)
            i1 = petals.vert(head + d * ln * 0.45 + sd * ln * 0.32 + tilt * 0.008, 0.5)
            i2 = petals.vert(head + d * ln + tilt * 0.015, 1.0)
            i3 = petals.vert(head + d * ln * 0.45 - sd * ln * 0.32 + tilt * 0.008, 0.5)
            petals.face(i0, i1, i2, i3)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.011)
        bmesh.ops.translate(bm, vec=head + tilt * 0.008, verts=bm.verts)
        parts.append(c.obj_from_bm("centre", bm, coll, centre_mat))
    pet_mat = c.mat_gradient("petal", [(0.0, c.FLOWER[0]), (0.3, c.FLOWER[1]),
                                       (1.0, c.FLOWER[2])], ao_dist=0.02)
    parts += [leaves.object("leaves", coll, green), petals.object("petals", coll, pet_mat)]
    ob = c.join(parts, "flowers")
    c.smooth(ob, 180)
    return ob


# --- bush, vine, path ------------------------------------------------------------------

def build_bush(coll):
    rng = random.Random(77)
    mat = c.mat_canopy("bush", ("#1d391a", "#33602a", "#5f9636", "#9cc955", "#c4e07c"))
    return canopy(coll, rng, Vector((0, 0, 0.55)), (0.95, 0.9, 0.7), [], mat, 0.045, 3500,
                  clumps=22, core=1.15)


def build_vine(coll):
    """Hanging vine curtain to drape over ledges, branches or the ruins (hangs from z=0)."""
    rng = random.Random(88)
    vine_mat = c.mat_bark("vine", palette=c.VINE)
    leaf_mat = c.mat_gradient("vine_leaf", [(0.0, c.FERN[0]), (0.5, c.FERN[2]),
                                            (1.0, c.GRASS[2])], ao_dist=0.05)
    parts, leaves = [], MeshBuilder()
    for k in range(5):
        x = -0.4 + 0.2 * k + rng.uniform(-0.05, 0.05)
        ln = rng.uniform(0.9, 1.9)
        pts = [Vector((x + 0.06 * math.sin(t * 5 + k), rng.uniform(-0.02, 0.02), -ln * t))
               for t in (0, 0.25, 0.5, 0.75, 1.0)]
        parts.append(c.tube("strand", coll, pts, 0.02, vine_mat, radii=[1, 0.85, 0.7, 0.5, 0.3],
                            bevel_res=1, res_u=3))
        z = -0.12
        while z > -ln + 0.05:                                   # alternating leaves
            t = -z / ln
            p = Vector((x + 0.06 * math.sin(t * 5 + k), 0, z))
            d = Vector((rng.choice((-1, 1)) * 0.8, rng.uniform(-0.5, 0.5), -0.4)).normalized()
            sd = d.cross(UP).normalized()
            s = rng.uniform(0.09, 0.13)
            i0 = leaves.vert(p, 0.2)
            i1 = leaves.vert(p + d * s * 0.5 + sd * s * 0.35, 0.6)
            i2 = leaves.vert(p + d * s, 1.0)
            i3 = leaves.vert(p + d * s * 0.5 - sd * s * 0.35, 0.6)
            leaves.face(i0, i1, i2, i3)
            z -= rng.uniform(0.07, 0.11)
    parts.append(leaves.object("vine_leaves", coll, leaf_mat))
    els = [(Vector((-0.55 + 0.07 * k + rng.uniform(-0.03, 0.03), rng.uniform(-0.08, 0.08), 0.02)),
            rng.uniform(0.13, 0.18), (1.4, 1.1, 0.75)) for k in range(17)]
    moss = c.metaball_mesh("vine_moss", coll, els, 0.035, c.mat_moss("vine_moss"), shaggy=0.012)
    parts.append(c.decimate(moss, 1200 / max(c.tris(moss), 1)))
    ob = c.join(parts, "vine_hanging")
    c.smooth(ob, 180)
    return ob


def build_path(coll):
    """4 x 2.4 m dirt path patch with soft, noisy edges that sink into the terrain."""
    rng = random.Random(99)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=48, y_segments=28, size=1.0)
    bmesh.ops.scale(bm, vec=(2.2, 1.35, 1), verts=bm.verts)

    def inside(x, y):
        hw = 1.0 + 0.14 * noise.noise(Vector((x * 0.9, 3.1, 0)))
        hl = 2.0 + 0.12 * noise.noise(Vector((7.7, y * 1.2, 0)))
        return ((abs(x) / hl) ** 4 + (abs(y) / hw) ** 4) ** 0.25

    gone = [f for f in bm.faces if inside(*f.calc_center_median().xy) > 1.0]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    for _ in range(3):                                        # snap the outline smooth
        for v in bm.verts:
            if v.is_boundary:
                v.co.xy = v.co.xy / inside(*v.co.xy)
    edge = []
    for v in bm.verts:
        e = min(1.0, max(0.0, (inside(v.co.x, v.co.y) - 0.7) / 0.3))
        v.co.z = 0.02 - 0.05 * e * e + 0.012 * noise.noise(v.co * 2.5) - 0.02 * (
            1 - abs(v.co.y)) * (1 - e)                        # worn rut down the middle
        edge.append(e)
    ob = c.obj_from_bm("path", bm, coll, c.mat_dirt())
    c.set_attr(ob, "edge", edge)
    parts = [ob]
    peb_mat = c.mat_stone("pebble", moss=0.0, scale=4.0)
    for _ in range(14):
        peb = rock_mesh((rng.uniform(0.06, 0.14), rng.uniform(0.05, 0.11), 0.05),
                        rng.randint(0, 999), subdiv=2, cuts=3, sink=0.3)
        bmesh.ops.translate(peb, vec=(rng.uniform(-1.8, 1.8), rng.uniform(-0.8, 0.8), 0.01),
                            verts=peb.verts)
        parts.append(c.obj_from_bm("pebble", peb, coll, peb_mat))
    ob = c.join(parts, "path")
    c.smooth(ob, 50)
    return ob


ASSETS = {
    "fern_a": (make_fern(12, fronds=10, length=0.95), 1024, True),
    "fern_b": (make_fern(34, fronds=7, length=0.6, upright=(1.1, 1.4), droop=(0.25, 0.45),
                         pairs=11), 1024, True),
    "plant_broadleaf": (build_broadleaf, 1024, True),
    "grass_tuft_a": (make_grass(5, 60, (0.35, 0.7), 0.25, 0.035), 512, True),
    "grass_tuft_b": (make_grass(8, 38, (0.18, 0.38), 0.2, 0.045, tips="#e4ea8c"), 512, True),
    "flowers_yellow": (build_flowers, 512, True),
    "bush_round": (build_bush, 1024, False),
    "vine_hanging": (build_vine, 1024, True, (1.0, -1.6, 0.1)),
    "path_dirt_segment": (build_path, 1024, False, (0.6, -1.0, 0.9)),
}

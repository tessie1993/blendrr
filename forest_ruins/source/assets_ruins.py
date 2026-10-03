"""Ruins: the mossy Celtic stone arch and broken wall pieces.

Reference: refs/arch.png, arch_top.png, arch_base_*.png, ai_arch_sheet.jpg.
Axes: X = width, Y = depth (you walk through the arch along Y), Z = up.
"""

import math
import random

import bmesh
from mathutils import Matrix, Vector

import common as c

# Arch proportions (metres): ~4.4 m tall, 2.2 m clear opening.
PILLAR_X = 1.42
SHAFT = 0.62
PLINTH = (0.9, 0.88, 0.42)
SHAFT_TOP = 2.35
CAP_TOP = 2.7
R_IN, R_OUT, DEPTH = 1.11, 1.68, 0.6


def place(bm, loc, rot_z=0.0, tilt=(0.0, 0.0)):
    m = (Matrix.Translation(loc) @ Matrix.Rotation(rot_z, 4, "Z")
         @ Matrix.Rotation(tilt[0], 4, "X") @ Matrix.Rotation(tilt[1], 4, "Y"))
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def block(size, panel=False, bevel=0.03):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if panel:
        faces = [f for f in bm.faces if abs(f.normal.y) > 0.9]
        bmesh.ops.inset_individual(bm, faces=faces, thickness=0.07, depth=-0.022)
    c.bevel_sharp(bm, bevel, 2)
    return bm


def voussoir(a0, a1, ri, ro, y0, y1, steps=4, bevel=0.028):
    """One wedge stone of the arch ring, centred on the arch axis at the origin."""
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        ca, sa = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((r * ca, y, r * sa))
                      for r, y in ((ri, y0), (ro, y0), (ro, y1), (ri, y1))])
    for i in range(steps):
        for k in range(4):
            bm.faces.new((rings[i][k], rings[i][(k + 1) % 4], rings[i + 1][(k + 1) % 4],
                          rings[i + 1][k]))
    bm.faces.new(rings[0])
    bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    c.bevel_sharp(bm, bevel, 2)
    return bm


def stone(coll, bm, mat, jit=0.012):
    c.jitter(bm.verts, jit, 2.2)
    return c.obj_from_bm("stone", bm, coll, mat)


def pillar(coll, x, mat, rng, courses=3, top=SHAFT_TOP, capital=True):
    parts = [stone(coll, place(block(PLINTH), (x, 0, PLINTH[2] / 2 - 0.05)), mat)]
    z, h = PLINTH[2] - 0.05, (top - PLINTH[2] + 0.05) / courses
    for i in range(courses):
        s = SHAFT + rng.uniform(-0.025, 0.02)
        bm = block((s, s, h - 0.014), panel=(i % 2 == 0))
        parts.append(stone(coll, place(bm, (x + rng.uniform(-0.012, 0.012), 0, z + h / 2),
                                       math.radians(rng.uniform(-1.5, 1.5))), mat))
        z += h
    if capital:
        parts.append(stone(coll, place(block((0.78, 0.74, 0.13)), (x, 0, top + 0.065)), mat))
        parts.append(stone(coll, place(block((0.9, 0.84, 0.22), bevel=0.035),
                                       (x, 0, top + 0.13 + 0.11)), mat))
    return parts


def wall(coll, x0, x1, y, mat, rng, profile, depth=0.5, z0=-0.04):
    """Stacked-stone wall; profile(t) gives how many courses survive at t in 0..1."""
    parts, z, ci = [], z0, 0
    while ci < 6:
        h = rng.uniform(0.26, 0.33)
        x = x0 - (0.22 if ci % 2 else 0.0)
        while x < x1:
            xe = min(x + rng.uniform(0.42, 0.68), x1)
            t = ((x + xe) / 2 - x0) / (x1 - x0)
            alive = ci < profile(t) - (1 if rng.random() < 0.15 else 0)
            if alive and xe - max(x, x0) > 0.18:
                xa = max(x, x0)
                bm = block((xe - xa - 0.016, depth * rng.uniform(0.9, 1.0), h - 0.014))
                place(bm, ((xa + xe) / 2, y + rng.uniform(-0.03, 0.03), z + h / 2),
                      math.radians(rng.uniform(-2, 2)))
                parts.append(stone(coll, bm, mat))
            x = xe
        z += h
        ci += 1
    return parts


def arch_ring(coll, mat, rng, n=9):
    parts, zc, gap = [], CAP_TOP, 0.012
    step = math.pi / n
    for i in range(n):
        key = i == n // 2
        ro = R_OUT + (0.1 if key else 0.0)
        y0, y1 = (-DEPTH / 2 - (0.04 if key else 0), DEPTH / 2 + (0.04 if key else 0))
        bm = voussoir(i * step + gap, (i + 1) * step - gap, R_IN, ro, y0, y1)
        parts.append(stone(coll, place(bm, (0, 0, zc)), mat))
        # raised archivolt band on the front and back faces
        if not key:
            band = voussoir(i * step + gap, (i + 1) * step - gap, R_OUT - 0.14, R_OUT + 0.03,
                            -DEPTH / 2 - 0.035, DEPTH / 2 + 0.035, bevel=0.02)
            parts.append(stone(coll, place(band, (0, 0, zc)), mat))
    return parts


# --- moss & vines -------------------------------------------------------------

def arch_point(theta, r, y=0.0):
    return Vector((r * math.cos(theta), y, CAP_TOP + r * math.sin(theta)))


def moss_elements(rng):
    els = []

    def density(theta):              # heavy on the left half and crown, lighter right
        return 1.0 if theta > 0.5 * math.pi else 0.55 + 0.4 * theta / (0.5 * math.pi)

    theta = 0.08
    while theta < math.pi - 0.02:
        d = density(theta)
        if rng.random() < d:
            for y in (-0.2, 0.0, 0.2):
                els.append((arch_point(theta, R_OUT - 0.02, y + rng.uniform(-0.05, 0.05)),
                            rng.uniform(0.19, 0.27)))
            for side in (-1, 1):                    # curtains pouring over both faces
                if rng.random() < 0.6 * d:
                    top = arch_point(theta, R_OUT - 0.04, side * 0.33)
                    for k in range(rng.randint(1, 2 + int(3 * d))):
                        els.append((top - Vector((0, 0, 0.17 * k + rng.uniform(0, 0.06))),
                                    rng.uniform(0.11, 0.16) * (1 - 0.12 * k),
                                    (0.9, 0.5, rng.uniform(1.3, 1.9))))
        theta += 0.05
    for x, amount in ((-PILLAR_X, 1.0), (PILLAR_X, 0.55)):     # capitals and pillar sides
        for _ in range(int(14 * amount)):
            els.append((Vector((x + rng.uniform(-0.38, 0.38), rng.uniform(-0.35, 0.35),
                                CAP_TOP - 0.02)), rng.uniform(0.17, 0.26)))
        outer = x + math.copysign(0.37, x)
        for y in (-0.24, -0.04, 0.16):                          # curtain down the outer side
            if rng.random() < amount:
                bottom = rng.uniform(0.9, 2.0)
                z = CAP_TOP - 0.05
                while z > bottom:
                    els.append((Vector((outer, y + rng.uniform(-0.05, 0.05), z)),
                                rng.uniform(0.13, 0.18), (0.6, 0.9, 1.5)))
                    z -= 0.16
        for a in (0.6, 2.4, 4.0, 5.4):                          # cushions round the plinths
            p = Vector((x + 0.52 * math.cos(a), 0.52 * math.sin(a), 0.03))
            els += cushion(rng, p, 3, 0.15, 0.22)
    return els


def cushion(rng, center, n, r0, r1, spread=0.16):
    """A few overlapping flattened balls that fuse into one moss cushion."""
    return [(center + Vector((rng.uniform(-spread, spread), rng.uniform(-spread, spread),
                              rng.uniform(-0.03, 0.03))),
             rng.uniform(r0, r1), (1.35, 1.2, 0.7)) for _ in range(n)]


def wall_moss(rng, x0, x1, y, top_at):
    els = []
    x = x0 + rng.uniform(0.0, 0.25)
    while x < x1:
        els += cushion(rng, Vector((x, y + rng.uniform(-0.12, 0.12), top_at(x))), 4, 0.16, 0.25)
        if rng.random() < 0.5:                                  # spill over a face
            side = rng.choice((-1, 1))
            for k in range(rng.randint(1, 3)):
                els.append((Vector((x, y + side * 0.28, top_at(x) - 0.1 - 0.15 * k)),
                            rng.uniform(0.11, 0.15), (0.9, 0.5, 1.6)))
        x += rng.uniform(0.25, 0.6)
    return els


def hanging_strand(coll, top, length, rng, mat, radius=0.045):
    sway = Vector((rng.uniform(-0.12, 0.12), rng.uniform(-0.08, 0.08), 0))
    pts = [top + sway * (t * t) + Vector((0, 0, -length * t)) for t in (0, 0.33, 0.66, 1.0)]
    return c.tube("strand", coll, pts, radius, mat, radii=[1.0, 0.75, 0.45, 0.2])


def vine(coll, pts, mat, rng, radius=0.055):
    radii = [1.0 - 0.45 * i / (len(pts) - 1) for i in range(len(pts))]
    return c.tube("vine", coll, pts, radius, mat, radii=radii, bevel_res=2, res_u=4)


def helix_vine(cx, top_z, bottom_z, r, turns, rng, a0=0.0):
    pts = []
    n = int(turns * 8) + 2
    for i in range(n):
        t = i / (n - 1)
        a = a0 + t * turns * 2 * math.pi
        z = top_z + (bottom_z - top_z) * t
        rr = r + (0.16 if z < PLINTH[2] + 0.05 else 0.0) + rng.uniform(-0.02, 0.02)
        pts.append(Vector((cx + rr * math.cos(a), rr * math.sin(a), z)))
    return pts


def sag_vine(theta_a, theta_b, sag, y):
    pa, pb = arch_point(theta_a, R_IN + 0.02, y), arch_point(theta_b, R_IN + 0.02, y)
    return [pa.lerp(pb, t) + Vector((0, 0, -sag * math.sin(math.pi * t))) for t in
            (0, 0.2, 0.4, 0.6, 0.8, 1.0)]


# --- assets ------------------------------------------------------------------

def build_arch(coll):
    rng = random.Random(7)
    st = c.mat_stone("arch_stone", moss=0.55, moss_low=0.5, cracks=0.25)
    mo, vi = c.mat_moss("arch_moss"), c.mat_bark("arch_vine", palette=c.VINE)
    parts = arch_ring(coll, st, rng)
    for x in (-PILLAR_X, PILLAR_X):
        parts += pillar(coll, x, st, rng)
    left = lambda t: 5 - 3.2 * t     # noqa: E731  tall at the pillar, crumbling outward
    right = lambda t: 3.2 - 2.2 * t  # noqa: E731
    parts += wall(coll, -3.3, -PILLAR_X - 0.2, 0.12, st, rng, lambda t: left(1 - t))
    parts += wall(coll, PILLAR_X + 0.2, 2.75, 0.1, st, rng, right)
    fallen = place(block((0.55, 0.45, 0.3)), (-3.05, -0.75, 0.1), 0.5, (0.12, -0.2))
    parts.append(stone(coll, fallen, st))

    els = moss_elements(rng)
    els += wall_moss(rng, -3.2, -1.9, 0.12, lambda x: -0.04 + 0.3 * (5 - 3.2 * (-x - 1.62) / 1.68))
    els += wall_moss(rng, 1.9, 2.7, 0.1, lambda x: -0.04 + 0.3 * (3.2 - 2.2 * (x - 1.62) / 1.13))
    moss = c.metaball_mesh("arch_moss", coll, els, 0.045, mo, shaggy=0.035)
    moss = c.decimate(moss, 7000 / max(c.tris(moss), 1))
    parts.append(moss)

    for _ in range(13):
        theta = rng.choice((rng.uniform(0.55, 0.92), rng.uniform(0.12, 0.42))) * math.pi
        top = arch_point(theta, R_IN + 0.04, rng.uniform(-0.25, 0.25))
        parts.append(hanging_strand(coll, top, rng.uniform(0.3, 1.25), rng, mo))
    parts.append(vine(coll, helix_vine(PILLAR_X, CAP_TOP + 0.05, 0.02, 0.37, 1.3, rng, 4.2),
                      vi, rng))
    parts.append(vine(coll, sag_vine(0.74 * math.pi, 0.6 * math.pi, 0.75, -0.18), vi, rng, 0.045))
    parts.append(vine(coll, sag_vine(0.36 * math.pi, 0.22 * math.pi, 1.0, 0.15), vi, rng, 0.05))
    parts.append(vine(coll, [arch_point(0.45 * math.pi, R_OUT + 0.05, -0.37),
                             arch_point(0.3 * math.pi, R_OUT + 0.02, -0.38),
                             arch_point(0.12 * math.pi, R_OUT - 0.05, -0.39),
                             Vector((PILLAR_X + 0.2, -0.36, 2.4)),
                             Vector((PILLAR_X + 0.15, -0.37, 1.6))], vi, rng, 0.045))
    ob = c.join(parts, "ruin_arch")
    c.smooth(ob, 40)
    return ob


def build_wall_a(coll):
    rng = random.Random(21)
    st = c.mat_stone("wall_stone", moss=0.6, moss_low=0.45, cracks=0.25)
    parts = wall(coll, -1.25, 1.25, 0.0, st, rng, lambda t: 1.6 + 3.6 * math.sin(math.pi * t) ** 0.7)
    top = lambda x: -0.04 + 0.3 * (1.6 + 3.6 * math.sin(math.pi * (x + 1.25) / 2.5) ** 0.7)  # noqa
    moss = c.metaball_mesh("wall_moss", coll, wall_moss(rng, -1.15, 1.15, 0.0, top), 0.05,
                           c.mat_moss("wall_moss"))
    parts.append(c.decimate(moss, 2500 / max(c.tris(moss), 1)))
    ob = c.join(parts, "ruin_wall_a")
    c.smooth(ob, 40)
    return ob


def build_wall_b(coll):
    """Rubble: a broken pillar stump and a few fallen blocks."""
    rng = random.Random(33)
    st = c.mat_stone("rubble_stone", moss=0.7, moss_low=0.35, cracks=0.25)
    parts = pillar(coll, 0.0, st, rng, courses=2, top=1.15, capital=False)
    for loc, size, rz, tilt in (((0.9, 0.35, 0.12), (0.62, 0.5, 0.3), 0.4, (0.1, -0.15)),
                                ((-0.75, -0.45, 0.1), (0.5, 0.45, 0.28), -0.7, (-0.2, 0.1)),
                                ((0.55, -0.7, 0.06), (0.4, 0.32, 0.2), 1.1, (0.05, 0.3))):
        parts.append(stone(coll, place(block(size), loc, rz, tilt), st))
    els = [(Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 1.12)),
            rng.uniform(0.13, 0.2)) for _ in range(7)]
    els += [(Vector((0.9 + rng.uniform(-0.2, 0.2), 0.35, 0.3)), 0.14) for _ in range(3)]
    moss = c.metaball_mesh("rubble_moss", coll, els, 0.045, c.mat_moss("rubble_moss"))
    parts.append(c.decimate(moss, 1500 / max(c.tris(moss), 1)))
    ob = c.join(parts, "ruin_rubble")
    c.smooth(ob, 40)
    return ob


ASSETS = {
    "ruin_arch": (build_arch, 2048, False, (-0.45, -1.6, 0.3)),
    "ruin_wall_a": (build_wall_a, 1024, False),
    "ruin_rubble": (build_wall_b, 1024, False),
}

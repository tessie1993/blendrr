"""Rocks: chiselled, rounded stones with moss caps (reference: refs/boulder_l.png, rock_r.png)."""

import random

import bmesh
from mathutils import Vector, noise

import common as c


def rock_mesh(dims, seed, subdiv=5, lumpy=0.12, cuts=8, sink=0.06):
    """Icosphere (subdiv 5 = 5120 faces), low-frequency lumps, then soft chisel planes
    for the painted facet look."""
    rng = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    off = Vector((seed * 1.3, seed * 2.1, seed * 0.7))
    for v in bm.verts:
        v.co *= 1.0 + lumpy * noise.fractal(v.co * 1.2 + off, 0.6, 2.0, 3)
    for _ in range(cuts):
        n = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.2, 1))).normalized()
        d = rng.uniform(0.78, 0.92)
        for v in bm.verts:
            t = v.co.dot(n) - d
            if t > 0:
                v.co -= n * t
    for v in bm.verts:
        v.co.z = max(v.co.z, -0.55)           # flat-ish underside
        v.co = Vector((v.co.x * dims[0], v.co.y * dims[1], v.co.z * dims[2])) / 2
    low = min(v.co.z for v in bm.verts)
    for v in bm.verts:
        v.co.z -= low + sink * dims[2]       # sits slightly sunk into the ground
    c.jitter(bm.verts, 0.012 * max(dims), 3.0, seed)
    return bm


def _rock(dims, seed, moss, subdiv=5, keep=1.0, **kw):
    def build(coll):
        ob = c.obj_from_bm("rock", rock_mesh(dims, seed, subdiv, **kw), coll,
                           c.mat_stone(moss=moss, scale=max(1.0, 1.6 / max(dims))))
        ob = c.decimate(ob, keep)
        c.smooth(ob, 38)
        return ob
    return build


ASSETS = {
    "rock_boulder_mossy": (_rock((2.3, 1.8, 1.5), 11, moss=1.0, keep=0.5), 1024, False),
    "rock_small_a": (_rock((0.75, 0.6, 0.48), 23, moss=0.55, subdiv=4), 512, False),
    "rock_small_b": (_rock((0.5, 0.42, 0.36), 37, moss=0.25, subdiv=4, cuts=9), 512, False),
    "rock_flat": (_rock((1.1, 0.85, 0.24), 41, moss=0.4, subdiv=4, cuts=4, lumpy=0.08),
                  512, False),
}

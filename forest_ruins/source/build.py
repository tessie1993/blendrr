"""Build the forest_ruins assets into ../*.glb (+ previews/, textures/).

    blender -b --factory-startup --python build.py -- [asset ...]

With no asset names it builds everything and saves forest_ruins.blend.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import assets_plants  # noqa: E402
import assets_rocks  # noqa: E402
import assets_ruins  # noqa: E402
import assets_trees  # noqa: E402
import common  # noqa: E402

ASSETS = {**assets_ruins.ASSETS, **assets_rocks.ASSETS, **assets_trees.ASSETS,
          **assets_plants.ASSETS}

names = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
unknown = [n for n in names if n not in ASSETS]
if unknown:
    sys.exit(f"Unknown assets {unknown}; choose from {sorted(ASSETS)}")

common.reset()
for slot, name in enumerate(names or ASSETS):
    builder, size, double_sided, *view = ASSETS[name]
    common.produce(name, builder, size, double_sided, slot, *view)

if not names:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(common.SRC_DIR, "forest_ruins.blend"),
                                relative_remap=True)

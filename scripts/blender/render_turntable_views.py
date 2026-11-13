r"""Render evenly spaced views of a Blender object on a transparent background, as TRELLIS multi-view input.

    # from a .blend: the object named Bear (default: every visible mesh)
    blender -b scenes/bear.blend -P scripts/blender/render_turntable_views.py -- --object Bear --out inputs/bear_views

    # from a mesh file (.glb / .gltf / .obj / .fbx / .ply)
    blender -b -P scripts/blender/render_turntable_views.py -- --import model.glb --out inputs/model_views

Writes view_00.png ... (view_00 = front, looking along +Y like Blender's front view, then the camera circles
counter-clockwise seen from above). Then:
    python scripts/generate_3d_asset.py --image inputs/bear_views/ --views 8 --export-splat

Nothing is saved back to the .blend: the camera and any fallback lights exist only for this render.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

IMPORTERS = {".glb": "import_scene.gltf", ".gltf": "import_scene.gltf", ".obj": "wm.obj_import",
             ".fbx": "import_scene.fbx", ".ply": "wm.ply_import"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="render_turntable_views.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="folder for view_NN.png")
    p.add_argument("--object", action="append", default=[],
                   help="object name to frame (repeatable; default: every visible mesh)")
    p.add_argument("--import", dest="import_path", type=Path, help="load this mesh file into an empty scene first")
    p.add_argument("--views", type=int, default=8, help="number of views around the subject (default 8)")
    p.add_argument("--elevation", type=float, default=10.0, help="camera height angle in degrees (default 10)")
    p.add_argument("--size", type=int, default=1024, help="square image size in pixels (default 1024)")
    p.add_argument("--engine", choices=("eevee", "cycles", "workbench"), default="eevee",
                   help="eevee (default) uses your materials and lights; workbench is fastest, flat colour")
    p.add_argument("--samples", type=int, default=64, help="render samples for eevee/cycles (default 64)")
    args = p.parse_args(argv)
    if not 1 <= args.views <= 64:
        p.error("--views must be 1-64")
    return args


def subjects(names: list[str]) -> list[bpy.types.Object]:
    if names:
        missing = [n for n in names if n not in bpy.data.objects]
        if missing:
            raise SystemExit(f"no object named {', '.join(missing)} (have: {', '.join(o.name for o in bpy.data.objects)})")
        return [bpy.data.objects[n] for n in names]
    found = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()]
    if not found:
        raise SystemExit("no visible mesh objects in the scene")
    return found


def bounds(objects) -> tuple[Vector, float]:
    """Centre and radius of a sphere around the objects' world-space bounding boxes."""
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    return (lo + hi) / 2, max((hi - lo).length / 2, 1e-6)


def setup_render(scene, args) -> None:
    engines = {"eevee": next(e for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
                             if e in {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}),
               "cycles": "CYCLES", "workbench": "BLENDER_WORKBENCH"}
    scene.render.engine = engines[args.engine]
    if args.engine == "eevee":
        scene.eevee.taa_render_samples = args.samples
    elif args.engine == "cycles":
        scene.cycles.samples = args.samples
    else:
        scene.display.shading.color_type = "TEXTURE"
    scene.render.resolution_x = scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True  # TRELLIS wants the subject cut out; alpha does that exactly
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"


def ensure_light(scene) -> None:
    """Imported meshes arrive with no lights; give them a soft key so EEVEE/Cycles aren't black."""
    if scene.render.engine == "BLENDER_WORKBENCH" or any(o.type == "LIGHT" for o in scene.objects):
        return
    if scene.world is None:
        scene.world = bpy.data.worlds.new("turntable_world")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (1, 1, 1, 1)
        bg.inputs["Strength"].default_value = 0.6
    sun = bpy.data.objects.new("turntable_key", bpy.data.lights.new("turntable_key", "SUN"))
    sun.data.energy = 2.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)


def main() -> int:
    args = parse_args()
    if args.import_path:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        op = IMPORTERS.get(args.import_path.suffix.lower())
        if op is None:
            raise SystemExit(f"--import: unsupported file type {args.import_path.suffix}")
        category, name = op.split(".")
        getattr(getattr(bpy.ops, category), name)(filepath=str(args.import_path.resolve()))
    scene = bpy.context.scene
    objects = subjects(args.object)
    centre, radius = bounds(objects)

    # Hide everything else in the scene from the render (the views must show only the subject).
    keep = set(objects) | {o for o in scene.objects if o.type == "LIGHT"}
    for o in scene.objects:
        if o not in keep and o.type != "CAMERA":
            o.hide_render = True

    setup_render(scene, args)
    ensure_light(scene)
    cam = bpy.data.objects.new("turntable_cam", bpy.data.cameras.new("turntable_cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.lens = 50
    cam.data.sensor_width = 36
    fov = 2 * math.atan(cam.data.sensor_width / (2 * cam.data.lens))
    distance = radius / math.sin(fov / 2) * 1.05
    cam.data.clip_start, cam.data.clip_end = distance / 100, distance + radius * 4

    args.out.mkdir(parents=True, exist_ok=True)
    elevation = math.radians(args.elevation)
    for i in range(args.views):
        azimuth = 2 * math.pi * i / args.views
        # View 0 sits at -Y looking toward +Y, like Blender's front view (numpad 1).
        offset = Vector((math.sin(azimuth) * math.cos(elevation), -math.cos(azimuth) * math.cos(elevation),
                         math.sin(elevation))) * distance
        cam.location = centre + offset
        cam.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str((args.out / f"view_{i:02d}.png").resolve())
        bpy.ops.render.render(write_still=True)
        print(f"[✓] {scene.render.filepath}  (azimuth {math.degrees(azimuth):.0f}°)")
    print(f"[*] {args.views} views of {', '.join(o.name for o in objects)} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

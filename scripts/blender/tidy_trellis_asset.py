r"""Tidy TRELLIS downloads for Blender kitbashing. Runs in Blender's own Python (no add-ons needed):

    blender -b -P scripts/blender/tidy_trellis_asset.py -- output/trellis-splat/
    blender -b -P scripts/blender/tidy_trellis_asset.py -- exports/3d/bear_trellis_42.glb --height 0.35

For each <name>.glb and/or <name>.ply (the splat with the same name) it writes <name>_tidy.glb / <name>_tidy.ply:
  - mesh: drops loose specks (pieces under --min-piece of the face count; UV seams don't count as gaps)
  - splat: rotated from TRELLIS's Y-up to Blender's Z-up, so it sits exactly on the mesh
  - both: optional real-world size (--height = finished height in metres; TRELLIS outputs fit a 1 m box),
    and the same move so the base sits on the ground at the origin (--no-ground keeps TRELLIS's centring)
Mesh and splat always get the identical scale and move, so they still line up after tidying.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aether_engine.utils.splat_tools import TRELLIS_TO_BLENDER, positions, read_ply, transform, write_ply  # noqa: E402


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="tidy_trellis_asset.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", type=Path, nargs="+", help=".glb / .ply files, or folders of them")
    p.add_argument("--height", type=float, help="finished height in metres (default: keep TRELLIS's 1 m box)")
    p.add_argument("--min-piece", type=float, default=0.01,
                   help="drop mesh pieces smaller than this fraction of the faces (default 0.01; 0 keeps all)")
    p.add_argument("--no-ground", action="store_true", help="don't move the base to Z=0 / centre on the origin")
    p.add_argument("--out-dir", type=Path, help="where to write the _tidy files (default: next to the inputs)")
    return p.parse_args(argv)


def collect(inputs: list[Path]) -> dict[Path, dict[str, Path]]:
    """Group files by name: {stem path: {".glb": path, ".ply": path}}; skips earlier _tidy outputs."""
    files = [f for i in inputs for f in (sorted(i.iterdir()) if i.is_dir() else [i])]
    jobs: dict[Path, dict[str, Path]] = {}
    for f in files:
        if f.suffix.lower() in (".glb", ".ply") and not f.stem.endswith("_tidy"):
            jobs.setdefault(f.with_suffix(""), {})[f.suffix.lower()] = f
    return jobs


def drop_specks(obj, min_piece: float) -> tuple[int, int]:
    """Delete faces in pieces smaller than ``min_piece`` x total faces. Pieces are found by vertex
    position, because the glTF importer splits vertices along UV seams. Returns (pieces, dropped faces)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    keys = {v.index: tuple(np.round(np.array(v.co), 6)) for v in bm.verts}
    parent: dict = {}

    def find(k):
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for face in bm.faces:
        roots = [find(keys[v.index]) for v in face.verts]
        for r in roots[1:]:
            parent[r] = roots[0]
    piece_of = [find(keys[face.verts[0].index]) for face in bm.faces]
    size_of = Counter(piece_of)
    limit = min_piece * len(bm.faces)
    doomed = [f for f, piece in zip(bm.faces, piece_of) if size_of[piece] < limit]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(obj.data)
    bm.free()
    return len(size_of), len(doomed)


def tidy_mesh(path: Path, args) -> tuple[bpy.types.Object, np.ndarray, np.ndarray]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"{path.name}: expected one mesh, found {len(meshes)}")
    obj = meshes[0]
    # Bake the importer's object transform into the vertices, so the bounds are world-space.
    obj.data.transform(obj.matrix_world)
    obj.matrix_world.identity()
    if args.min_piece > 0:
        pieces, dropped = drop_specks(obj, args.min_piece)
        print(f"  mesh: {pieces} piece(s), dropped {dropped} face(s) in specks")
    verts = np.array([v.co for v in obj.data.vertices])
    return obj, verts.min(0), verts.max(0)


def splat_bounds(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bounds of the visible Gaussians (opacity > 0.5, outer 0.5% trimmed) after rotating to Z-up."""
    xyz = positions(data) @ TRELLIS_TO_BLENDER.T
    if "opacity" in data.dtype.names:
        visible = 1 / (1 + np.exp(-data["opacity"].astype(np.float64))) > 0.5
        xyz = xyz[visible] if visible.any() else xyz
    return np.percentile(xyz, 0.5, axis=0), np.percentile(xyz, 99.5, axis=0)


def main() -> int:
    args = parse_args()
    if args.height is not None and args.height <= 0:
        raise SystemExit("--height must be positive")
    jobs = collect(args.inputs)
    if not jobs:
        raise SystemExit("no .glb or .ply files found")
    for stem, files in jobs.items():
        out = (args.out_dir or stem.parent) / f"{stem.name}_tidy"
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[*] {stem.name}: {' + '.join(sorted(files))}")
        splat = read_ply(files[".ply"]) if ".ply" in files else None
        if ".glb" in files:
            obj, lo, hi = tidy_mesh(files[".glb"], args)
        else:
            obj, (lo, hi) = None, splat_bounds(splat[0])

        # The mesh's bounds set the move/scale when there is one, so the splat follows it exactly.
        scale = args.height / (hi[2] - lo[2]) if args.height else 1.0
        offset = np.zeros(3) if args.no_ground else -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]]) * scale

        if obj is not None:
            obj.data.transform(_matrix(scale, offset))
            obj.data.update()
            bpy.ops.export_scene.gltf(filepath=str(out.with_suffix(".glb")), export_format="GLB",
                                      use_selection=False, export_apply=True)
            dims = (hi - lo) * scale
            print(f"[✓] {out.with_suffix('.glb')}  ({dims[0]:.3f} x {dims[1]:.3f} x {dims[2]:.3f} m)")
        if splat is not None:
            data, comments = splat
            tidied = transform(data, TRELLIS_TO_BLENDER, scale, offset)
            write_ply(out.with_suffix(".ply"), tidied, [*comments, b"comment tidied: Z-up, Blender coordinates"])
            print(f"[✓] {out.with_suffix('.ply')}  ({len(tidied):,} Gaussians, Z-up)")
    return 0


def _matrix(scale: float, offset: np.ndarray):
    from mathutils import Matrix
    m = Matrix.Diagonal((scale, scale, scale, 1.0))
    m.translation = tuple(offset)
    return m


if __name__ == "__main__":
    sys.exit(main())

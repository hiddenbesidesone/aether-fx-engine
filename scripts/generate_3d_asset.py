#!/usr/bin/env python3
r"""Single-view 2D concept -> 3D .glb mesh and/or Gaussian splat .ply (TRELLIS or Hunyuan3D-2) via ComfyUI.

    python scripts/generate_3d_asset.py --image ./inputs/doll_head.png --engine trellis \
        --steps 25 --output-dir ./exports/3d/

    # mesh + splat (.ply for Blender / SkySplat), high-quality texture bake
    python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --engine trellis \
        --export-splat --texture-mode opt --output-dir ./exports/3d/

    # splat only: skips the .glb texture bake and download
    python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --export-splat --splat-only
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_cuda_server, require_file, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402
from aether_engine.utils.image_tools import prepare_3d_input  # noqa: E402

TEMPLATES = {"trellis": "image_to_3d_api.json", "hunyuan": "image_to_3d_hunyuan_api.json"}
MESH_SUFFIXES = (".glb", ".gltf", ".obj")  # .ply here is the splat, fetched separately


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=Path, required=True, help="concept image (transparent PNG preferred)")
    p.add_argument("--engine", choices=sorted(TEMPLATES), default="trellis")
    p.add_argument("--steps", type=int, default=25,
                   help="TRELLIS ss_sampling_steps / Hunyuan diffusion steps (default 25)")
    p.add_argument("--slat-steps", type=int, default=20, help="TRELLIS slat_sampling_steps (default 20)")
    p.add_argument("--texture-size", type=int, choices=(512, 1024, 1536, 2048), default=1024,
                   help="TRELLIS texture resolution")
    p.add_argument("--texture-mode", choices=("fast", "opt"), default=None,
                   help="TRELLIS .glb texture bake: fast for iterations, opt for finals (default fast; "
                        "does not affect the splat)")
    p.add_argument("--export-splat", action="store_true",
                   help="TRELLIS: also download the 3D Gaussian Splat as .ply (for SkySplat in Blender)")
    p.add_argument("--splat-only", action="store_true",
                   help="TRELLIS: with --export-splat, skip the .glb texture bake and download only the .ply")
    p.add_argument("--max-faces", type=int, default=40000, help="Hunyuan face budget after reduction")
    p.add_argument("--padding", type=float, default=0.10, help="margin around the subject per side (default 0.10)")
    p.add_argument("--size", type=int, default=1024, help="side of the square input sent to the server")
    p.add_argument("--output-dir", type=Path, default=Path("exports/3d"))
    add_common_args(p)
    args = p.parse_args(argv)

    require_file(args.image, "--image")
    if args.engine != "trellis":
        for flag, given in (("--export-splat", args.export_splat), ("--splat-only", args.splat_only),
                            ("--texture-mode", args.texture_mode)):
            if given:
                raise CLIError(f"{flag} needs --engine trellis (Hunyuan3D-2 only produces meshes)")
    if args.splat_only and not args.export_splat:
        raise CLIError("--splat-only needs --export-splat")
    if args.splat_only and args.texture_mode:
        raise CLIError("--texture-mode only affects the .glb, which --splat-only skips")
    # save_glb must stay on: IF_TrellisImageTo3D crashes before writing the .ply when it is off
    # (generate_outputs logs texture_image.shape on None). "blank" skips the texture bake instead.
    args.texture_mode = "blank" if args.splat_only else args.texture_mode or "fast"
    in_range("--steps", args.steps, 1, 100)
    in_range("--slat-steps", args.slat_steps, 1, 100)
    in_range("--padding", args.padding, 0.0, 0.45)
    return args


def build(args: argparse.Namespace, image_name: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATES[args.engine])
    wf.set("source_image", image=image_name)
    if args.engine == "trellis":
        wf.set("trellis", seed=seed, ss_sampling_steps=args.steps, slat_sampling_steps=args.slat_steps,
               texture_size=args.texture_size, texture_mode=args.texture_mode, project_name=tag,
               save_glb=True, save_gaussian=args.export_splat)
    else:
        wf.set("hunyuan", seed=seed, steps=args.steps)
        wf.set("postprocess", max_facenum=args.max_faces)
        wf.set("save_mesh", filename_prefix=f"3D/{tag}")
    return wf


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    tag = job_tag(args.image.stem)

    with tempfile.TemporaryDirectory(prefix="aether3d_") as tmp:
        staged = prepare_3d_input(args.image, Path(tmp) / tag, padding=args.padding, size=args.size)
        print(f"[*] framed {args.image} -> {args.size}x{args.size} square, {args.padding:.0%} padding")

        if args.dry_run:
            dump_payload(build(args, staged.name, tag, seed), args.dump_payload)
            return 0

        client = make_client(args)
        if args.engine == "trellis":
            require_cuda_server(client, "TRELLIS (spconv / flash-attn voxel ops)")
        elif client.server_device_type() != "cuda":
            print("[!] Hunyuan3D on a non-CUDA server: flash VDM decode and the texture rasterizer may be "
                  "unavailable; shape generation will be slow.")
        image_name = upload_as(client, staged, staged.name, Path(tmp))

    wf = build(args, image_name, tag, seed)
    preflight(client, wf, args)
    outputs = "splat" if args.splat_only else "mesh + splat" if args.export_splat else "mesh"
    detail = f" texture={args.texture_mode}" if args.engine == "trellis" and not args.splat_only else ""
    print(f"[*] {args.engine}: {outputs}, steps={args.steps}{detail} seed={seed}")
    prompt_id = execute(client, wf, args)

    meshes = [] if args.splat_only else collect_outputs(client, prompt_id, args.output_dir, suffixes=MESH_SUFFIXES)
    if not meshes and args.engine == "trellis" and not args.splat_only:
        # IF_TrellisImageTo3D writes output/<project_name>/<project_name>.glb.
        meshes = [client.download(f"{tag}.glb", subfolder=tag, dest_dir=args.output_dir)]
    if not meshes and not args.splat_only:
        raise CLIError(f"prompt {prompt_id} finished but produced no mesh file")
    splat = download_splat(client, tag, args.output_dir) if args.export_splat else None

    base = args.output_dir / f"{args.image.stem}_{args.engine}_{seed}"
    for i, mesh in enumerate(meshes):
        suffix = f"_{i}" if len(meshes) > 1 else ""
        print(f"[✓] mesh  {move_to(mesh, base.with_name(base.name + suffix + mesh.suffix))}")
    if splat:
        print(f"[✓] splat {move_to(splat, base.with_name(base.name + '.ply'))}")
    return 0


def download_splat(client, tag: str, dest_dir: Path) -> Path:
    """Fetch the splat by its known path: IF_TrellisImageTo3D saves
    output/<project_name>/<project_name>.ply but never reports it in /history."""
    try:
        return client.download(f"{tag}.ply", subfolder=tag, dest_dir=dest_dir)
    except requests.HTTPError as exc:
        raise CLIError(f"TRELLIS finished but {tag}/{tag}.ply could not be downloaded ({exc}); "
                       f"check the node ran with save_gaussian=true and the server's output/ folder")


if __name__ == "__main__":
    sys.exit(main())

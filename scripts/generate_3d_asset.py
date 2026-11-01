#!/usr/bin/env python3
"""Single-view 2D concept -> 3D .glb mesh (TRELLIS or Hunyuan3D-2) via ComfyUI.

    python scripts/generate_3d_asset.py --image ./inputs/doll_head.png --engine trellis \
        --steps 25 --output-dir ./exports/3d/
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_cuda_server, require_file, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402
from aether_engine.utils.image_tools import prepare_3d_input  # noqa: E402

TEMPLATES = {"trellis": "image_to_3d_api.json", "hunyuan": "image_to_3d_hunyuan_api.json"}
MESH_SUFFIXES = (".glb", ".gltf", ".obj", ".ply")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=Path, required=True, help="concept image (transparent PNG preferred)")
    p.add_argument("--engine", choices=sorted(TEMPLATES), default="trellis")
    p.add_argument("--steps", type=int, default=25,
                   help="TRELLIS ss_sampling_steps / Hunyuan diffusion steps (default 25)")
    p.add_argument("--slat-steps", type=int, default=20, help="TRELLIS slat_sampling_steps (default 20)")
    p.add_argument("--texture-size", type=int, choices=(512, 1024, 1536, 2048), default=1024,
                   help="TRELLIS texture resolution")
    p.add_argument("--max-faces", type=int, default=40000, help="Hunyuan face budget after reduction")
    p.add_argument("--padding", type=float, default=0.10, help="margin around the subject per side (default 0.10)")
    p.add_argument("--size", type=int, default=1024, help="side of the square input sent to the server")
    p.add_argument("--output-dir", type=Path, default=Path("exports/3d"))
    add_common_args(p)
    args = p.parse_args(argv)

    require_file(args.image, "--image")
    in_range("--steps", args.steps, 1, 100)
    in_range("--slat-steps", args.slat_steps, 1, 100)
    in_range("--padding", args.padding, 0.0, 0.45)
    return args


def build(args: argparse.Namespace, image_name: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATES[args.engine])
    wf.set("source_image", image=image_name)
    if args.engine == "trellis":
        wf.set("trellis", seed=seed, ss_sampling_steps=args.steps, slat_sampling_steps=args.slat_steps,
               texture_size=args.texture_size, project_name=tag)
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
    print(f"[*] {args.engine}: steps={args.steps} seed={seed}")
    prompt_id = execute(client, wf, args)

    meshes = collect_outputs(client, prompt_id, args.output_dir, suffixes=MESH_SUFFIXES)
    if not meshes and args.engine == "trellis":
        # IF_TrellisImageTo3D writes output/<project_name>/<project_name>.glb.
        meshes = [client.download(f"{tag}.glb", subfolder=tag, dest_dir=args.output_dir)]
    if not meshes:
        raise CLIError(f"prompt {prompt_id} finished but produced no mesh file")

    for i, mesh in enumerate(meshes):
        suffix = f"_{i}" if len(meshes) > 1 else ""
        target = move_to(mesh, args.output_dir / f"{args.image.stem}_{args.engine}_{seed}{suffix}{mesh.suffix}")
        print(f"[✓] {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

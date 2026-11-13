#!/usr/bin/env python3
r"""2D concept (one view, or several of the same subject) -> 3D .glb mesh and/or Gaussian splat .ply (TRELLIS or Hunyuan3D-2) via ComfyUI.

    python scripts/generate_3d_asset.py --image ./inputs/doll_head.png --engine trellis \
        --steps 25 --output-dir ./exports/3d/

    # mesh + splat (.ply for Blender / SkySplat), high-quality texture bake
    python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --engine trellis \
        --export-splat --texture-mode opt --output-dir ./exports/3d/

    # splat only: skips the .glb texture bake and download
    python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --export-splat --splat-only

    # multi-view (TRELLIS): several photos/renders of the SAME subject, or a turntable folder
    # (6 evenly spaced frames are picked from it). The back and sides stop being guessed.
    python scripts/generate_3d_asset.py --image ./inputs/bear_turntable/ --views 6 --export-splat
    python scripts/generate_3d_asset.py --image front.png side.png back.png --export-splat

Tidy the downloads for Blender afterwards (drop specks, Z-up splat, real-world size, feet on the ground):
    blender -b -P scripts/blender/tidy_trellis_asset.py -- exports/3d/<name>_trellis_<seed>.glb --height 0.35
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
from aether_engine.payload_builder import WorkflowTemplate, combo_options  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402
from aether_engine.utils.image_tools import list_frames, prepare_3d_input  # noqa: E402

TEMPLATES = {"trellis": "image_to_3d_api.json", "hunyuan": "image_to_3d_hunyuan_api.json"}
MESH_SUFFIXES = (".glb", ".gltf", ".obj")  # .ply here is the splat, fetched separately
# The loader's combos list only backends installed on the server; first available wins.
LOADER_BACKENDS = {"attn_backend": ("flash_attn", "xformers", "sdpa"), "sparse_backend": ("spconv", "torchsparse")}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=Path, nargs="+", required=True,
                   help="concept image (transparent PNG, or a plain white/flat background). Give several images, "
                        "or a folder of turntable frames, of the SAME subject for TRELLIS multi-view")
    p.add_argument("--views", type=int, default=6,
                   help="multi-view: use at most this many images, evenly spaced through the list (default 6)")
    p.add_argument("--multimode", choices=("stochastic", "multidiffusion"), default="stochastic",
                   help="TRELLIS multi-view blending: stochastic (default) cycles the views across sampling steps; "
                        "multidiffusion averages them every step (slower, sometimes cleaner)")
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

    args.images = pick_views(args.image, args.views)
    if args.engine != "trellis":
        if len(args.images) > 1:
            raise CLIError("several --image views need --engine trellis (Hunyuan3D-2 here is single-view)")
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


def pick_views(paths: list[Path], views: int) -> list[Path]:
    """Expand folders into their frames, then keep ``views`` evenly spaced images (first one always kept)."""
    in_range("--views", views, 1, 16)
    images: list[Path] = []
    for path in paths:
        if path.is_dir():
            try:
                images += [f for f in list_frames(path) if f.suffix.lower() != ".exr"]
            except FileNotFoundError as exc:
                raise CLIError(f"--image: {exc}") from exc
        else:
            require_file(path, "--image")
            images.append(path)
    if not images:
        raise CLIError("--image: no usable images found")
    if len(images) > views:
        step = len(images) / views
        images = [images[int(i * step)] for i in range(views)]
    return images


def job_name(args: argparse.Namespace) -> str:
    """Output basename: the image's stem, or the folder's name for a turntable folder."""
    first = args.image[0]
    return first.name if first.is_dir() else first.stem


def build(args: argparse.Namespace, image_names: list[str], tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATES[args.engine])
    wf.set("source_image", image=image_names[0])
    if len(image_names) > 1:
        # One LoadImage per view, joined into a batch for background removal; all are the same square size.
        batch = [wf.node_id("source_image"), 0]
        for i, name in enumerate(image_names[1:], start=2):
            view = wf.add_node("LoadImage", {"image": name}, title=f"source_image_{i}")
            batch = [wf.add_node("ImageBatch", {"image1": batch, "image2": [view, 0]}, title=f"view_batch_{i}"), 0]
        wf.set("remove_background", image=batch)
        wf.set("trellis", mode="multi", multimode=args.multimode)
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
    name = job_name(args)
    tag = job_tag(name)

    with tempfile.TemporaryDirectory(prefix="aether3d_") as tmp:
        staged = [prepare_3d_input(image, Path(tmp) / (tag if i == 0 else f"{tag}_v{i + 1}"),
                                   padding=args.padding, size=args.size) for i, image in enumerate(args.images)]
        for image in args.images:
            print(f"[*] framed {image} -> {args.size}x{args.size} square, {args.padding:.0%} padding")
        if len(staged) > 1:
            print(f"[*] multi-view: {len(staged)} views, {args.multimode}")

        if args.dry_run:
            dump_payload(build(args, [s.name for s in staged], tag, seed), args.dump_payload)
            return 0

        client = make_client(args)
        if args.engine == "trellis":
            require_cuda_server(client, "TRELLIS (spconv / flash-attn voxel ops)")
        elif client.server_device_type() != "cuda":
            print("[!] Hunyuan3D on a non-CUDA server: flash VDM decode and the texture rasterizer may be "
                  "unavailable; shape generation will be slow.")
        image_names = [upload_as(client, s, s.name, Path(tmp)) for s in staged]

    wf = build(args, image_names, tag, seed)
    if args.engine == "trellis":
        match_trellis_backends(wf, client.object_info())
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

    # Rename each file as soon as it lands, so a failed splat download can't strand a <job-tag>.glb.
    base = args.output_dir / f"{name}_{args.engine}_{seed}"
    for i, mesh in enumerate(meshes):
        suffix = f"_{i}" if len(meshes) > 1 else ""
        print(f"[✓] mesh  {move_to(mesh, base.with_name(base.name + suffix + mesh.suffix))}")
    if args.export_splat:
        splat = download_splat(client, tag, args.output_dir)
        print(f"[✓] splat {move_to(splat, base.with_name(base.name + '.ply'))}")
    return 0


def match_trellis_backends(wf: WorkflowTemplate, object_info: dict) -> None:
    """Pick loader backends the server offers. The real choice is SPARSE_ATTN_BACKEND / SPCONV_ALGO,
    read when ComfyUI starts (scripts/runpod/start_comfy.sh); this only keeps the payload valid."""
    spec = object_info.get("IF_TrellisCheckpointLoader", {}).get("input", {}).get("required", {})
    for key, preferred in LOADER_BACKENDS.items():
        options = combo_options(spec.get(key)) or []
        if options and wf.node("trellis_loader")["inputs"][key] not in options:
            wf.set("trellis_loader", **{key: next((b for b in preferred if b in options), options[0])})


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

#!/usr/bin/env python3
"""Depth sequence -> AI world as a PNG sequence, frame for frame, with Wan 2.1 VACE via ComfyUI.

Built for the Police Bike brief (docs/gemini/05_police_bike_comfyui.md): Blender renders
depth_####.png (white = near) without the rider; this paints a world that follows that layout,
speed and camera, and writes world_####.png with the same frame numbers. Nothing is trimmed,
resampled or reframed.

    python scripts/render_world_vace.py --depth-frames shots/loop/depth \
        --prompt "rainy neon city street at night, cinematic" --loop --seed 42 \
        --output-dir exports/world/loop_neon

Long shots render in chunks (--chunk, 81 frames by default, Wan's native length). Each chunk
after the first starts with the last --overlap frames already generated, so the model continues
from them instead of starting fresh. --loop then regenerates the last --loop-frames frames so the
end leads back into frame 1. --prompt-at FRAME TEXT switches prompt from that frame on, taking
effect at the next chunk boundary.

Use --resume to carry on after an interruption: finished chunks in <output-dir>/_chunks are reused.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_dir, require_file, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, upload_as, upload_files  # noqa: E402
from aether_engine.utils.image_tools import frame_number, list_frames  # noqa: E402

TEMPLATE = "wan_vace_depth_to_video.json"
MODELS = {"1.3b": "wan2.1_vace_1.3B_fp16.safetensors", "14b": "wan2.1_vace_14B_fp16.safetensors"}


@dataclass
class Chunk:
    """``length`` frames from ``start``; the first ``keep`` are already generated (VACE mask 0)
    and the rest are generated from depth. ``tail`` frames after them are already generated too
    (used by the loop join). Frames past the end of the shot repeat its last depth frame."""
    name: str
    start: int
    length: int
    keep: int = 0
    tail: int = 0


def valid_length(n: int) -> int:
    """Round up to Wan's 4k+1 frame counts."""
    return n + (-(n - 1)) % 4


def plan_chunks(n_frames: int, chunk: int, overlap: int) -> list[Chunk]:
    chunks, end = [], 0
    while end < n_frames:
        start = end - overlap if chunks else 0
        length = min(chunk, valid_length(n_frames - start))
        chunks.append(Chunk(f"chunk_{len(chunks):02d}", start, length, overlap if chunks else 0))
        end = min(start + length, n_frames)
    return chunks


def plan_loop_join(n_frames: int, join: int, overlap: int) -> Chunk:
    """Regenerate the last ``join`` frames between ``overlap`` kept frames on each side of the seam
    (the end of the shot before it, frames 1.. after it), so the last frame leads into the first."""
    length = valid_length(overlap + join + overlap)
    join = length - 2 * overlap
    if n_frames < join + 2 * overlap:
        raise CLIError(f"--loop needs at least {join + 2 * overlap} frames (got {n_frames}); "
                       f"lower --loop-frames or --overlap")
    return Chunk("loop_join", n_frames - join - overlap, length, overlap, overlap)


def prompt_at(schedule: list[tuple[int, str]], frame: int) -> str:
    """``schedule`` is sorted (first frame, prompt) with frames counted from 1."""
    text = schedule[0][1]
    for first, prompt in schedule:
        if frame + 1 >= first:
            text = prompt
    return text


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--depth-frames", type=Path, required=True, help="folder of depth_####.png (white = near)")
    p.add_argument("--output-dir", type=Path, required=True, help="where world_####.png are written")
    p.add_argument("--prompt", required=True, help="prompt from frame 1")
    p.add_argument("--prompt-at", nargs=2, action="append", default=[], metavar=("FRAME", "PROMPT"),
                   help="switch to PROMPT from FRAME (1-based); repeatable")
    p.add_argument("--negative", default=None, help="negative prompt (default: template's)")
    p.add_argument("--reference-image", type=Path, help="optional style reference image")
    p.add_argument("--frames", type=int, help="only the first N frames (quick tests)")
    p.add_argument("--width", type=int, default=768, help="render width, multiple of 16 (default 768)")
    p.add_argument("--height", type=int, default=432, help="render height, multiple of 16 (default 432)")
    p.add_argument("--strength", type=float, default=1.0, help="how strictly the depth is followed (VACE strength)")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--cfg", type=float, default=6.0)
    p.add_argument("--shift", type=float, default=8.0, help="ModelSamplingSD3 shift")
    p.add_argument("--sampler", default="uni_pc")
    p.add_argument("--scheduler", default="simple")
    p.add_argument("--chunk", type=int, default=81, help="frames per generation, 4k+1 (default 81)")
    p.add_argument("--overlap", type=int, default=13, help="generated frames carried into the next chunk")
    p.add_argument("--loop", action="store_true", help="make the shot loop seamlessly (last frame -> first)")
    p.add_argument("--loop-frames", type=int, default=16, help="frames regenerated at the end for --loop")
    p.add_argument("--model", default="1.3b",
                   help="'1.3b' (fast tests), '14b' (quality), or a diffusion_models filename")
    p.add_argument("--weight-dtype", default="default", choices=["default", "fp8_e4m3fn", "fp8_e5m2"],
                   help="fp8_e4m3fn lets the 14B model fit on a 24 GB card")
    p.add_argument("--text-encoder", default=None, help="text_encoders filename (default: template's fp8 umt5)")
    p.add_argument("--vae", default=None, help="vae filename (default: wan_2.1_vae.safetensors)")
    p.add_argument("--resume", action="store_true", help="reuse finished chunks in <output-dir>/_chunks")
    add_common_args(p)
    args = p.parse_args(argv)

    require_dir(args.depth_frames, "--depth-frames")
    if args.reference_image:
        require_file(args.reference_image, "--reference-image")
    for name in ("width", "height"):
        if getattr(args, name) % 16:
            raise CLIError(f"--{name} must be a multiple of 16 (16:9 options: 768x432, 1024x576, 1280x720)")
    if (args.chunk - 1) % 4 or args.chunk < 5:
        raise CLIError("--chunk must be 4k+1 (e.g. 49, 81, 89)")
    if not 1 <= args.overlap <= args.chunk - 4:
        raise CLIError("--overlap must be at least 1 and leave at least 4 new frames per chunk")
    in_range("--strength", args.strength, 0, 10)
    in_range("--loop-frames", args.loop_frames, 4, 1000)
    if args.frames is not None:
        in_range("--frames", args.frames, 1, 100000)
    schedule = [(1, args.prompt)]
    for frame, text in args.prompt_at:
        if not frame.isdigit() or int(frame) < 1:
            raise CLIError(f"--prompt-at frame must be a positive number (got {frame!r})")
        schedule.append((int(frame), text))
    args.schedule = sorted(schedule, key=lambda item: item[0])
    args.model = MODELS.get(args.model.lower(), args.model)
    return args


def control_frames(chunk: Chunk, depth: list[Path], generated: dict[int, Path], size: tuple[int, int],
                   dst: Path) -> tuple[list[Path], list[Path]]:
    """Write the chunk's control video and mask (black = keep this generated frame, white = generate)."""
    dst.mkdir(parents=True, exist_ok=True)
    n = len(depth)
    controls, masks = [], []
    black, white = Image.new("RGB", size, 0), Image.new("RGB", size, (255, 255, 255))
    for i in range(chunk.length):
        frame = chunk.start + i
        kept = i < chunk.keep or i >= chunk.length - chunk.tail
        if kept:
            src = generated[frame % n]
        else:
            src = depth[min(frame, n - 1)]
        with Image.open(src) as img:
            img = img.convert("RGB")
            if img.size != size:
                img = img.resize(size, Image.Resampling.LANCZOS)
            path = dst / f"control_{i:05d}.png"
            img.save(path)
        controls.append(path)
        mask = dst / f"mask_{i:05d}.png"
        (black if kept else white).save(mask)
        masks.append(mask)
    return controls, masks


def build(args: argparse.Namespace, chunk: Chunk, control_dir: str, mask_dir: str | None, reference: str | None,
          prompt: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATE)
    wf.set("diffusion_model", unet_name=args.model, weight_dtype=args.weight_dtype)
    if args.text_encoder:
        wf.set("text_encoder", clip_name=args.text_encoder)
    if args.vae:
        wf.set("vae", vae_name=args.vae)
    wf.set("shift", shift=args.shift)
    wf.set("positive_prompt", text=prompt)
    if args.negative is not None:
        wf.set("negative_prompt", text=args.negative)
    wf.set("control_frames", directory=control_dir, image_load_cap=chunk.length)
    if mask_dir:
        wf.set("mask_frames", directory=mask_dir, image_load_cap=chunk.length)
    else:
        del wf.node("vace")["inputs"]["control_masks"]  # no kept frames: generate everything
        wf.remove("mask")
        wf.remove("mask_frames")
    wf.set("vace", width=args.width, height=args.height, length=chunk.length, strength=args.strength)
    if reference:
        ref = wf.add_node("LoadImage", {"image": reference}, title="reference_image")
        wf.node("vace")["inputs"]["reference_image"] = [ref, 0]
    wf.set("sampler", seed=seed, steps=args.steps, cfg=args.cfg, sampler_name=args.sampler, scheduler=args.scheduler)
    wf.set("frames_out", filename_prefix=f"AetherFX/{tag}")
    return wf


def run_chunk(args, client, chunk: Chunk, depth: list[Path], generated: dict[int, Path], size, chunk_dir: Path,
              reference: str | None, seed: int) -> list[Path]:
    """Generate one chunk; returns its ``chunk.length`` frames in order."""
    done = sorted(chunk_dir.glob("*.png")) if chunk_dir.is_dir() else []
    if args.resume and len(done) == chunk.length:
        print(f"[=] {chunk.name}: reusing {len(done)} frames from {chunk_dir}")
        return done
    first_new = chunk.start + chunk.keep
    prompt = prompt_at(args.schedule, first_new)
    tag = job_tag(f"{args.output_dir.name}_{chunk.name}")
    print(f"[*] {chunk.name}: frames {chunk.start + 1}-{chunk.start + chunk.length} "
          f"(keeps {chunk.keep} + {chunk.tail}) prompt: {prompt[:70]}")
    with tempfile.TemporaryDirectory(prefix="aether_vace_") as tmp:
        controls, masks = control_frames(chunk, depth, generated, size, Path(tmp))
        has_mask = chunk.keep or chunk.tail
        control_dir, mask_dir = f"{tag}_control", (f"{tag}_mask" if has_mask else None)
        if args.dry_run:
            dump_payload(build(args, chunk, control_dir, mask_dir, reference, prompt, tag, seed), args.dump_payload)
            return []
        upload_files(client, controls, subfolder=control_dir, label="control frames")
        if mask_dir:
            upload_files(client, masks, subfolder=mask_dir, label="masks")
    wf = build(args, chunk, control_dir, mask_dir, reference, prompt, tag, seed)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    frames = sorted(collect_outputs(client, prompt_id, chunk_dir, suffixes=(".png",)))
    if len(frames) != chunk.length:
        raise CLIError(f"{chunk.name}: expected {chunk.length} frames back, got {len(frames)}")
    return frames


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    depth = list_frames(args.depth_frames)
    if args.frames:
        if args.frames > len(depth):
            raise CLIError(f"--frames {args.frames} but only {len(depth)} depth frames")
        depth = depth[:args.frames]
    n = len(depth)
    size = (args.width, args.height)
    with Image.open(depth[0]) as img:
        src_w, src_h = img.size
    if abs(src_w / src_h - args.width / args.height) > 0.01:
        print(f"[!] depth is {src_w}x{src_h} but rendering {args.width}x{args.height}: the aspect differs")

    chunks = plan_chunks(n, args.chunk, args.overlap)
    join = plan_loop_join(n, args.loop_frames, args.overlap) if args.loop else None
    print(f"[*] {n} frames, {args.width}x{args.height}, {args.model}, strength {args.strength:g}, seed {seed}; "
          f"{len(chunks)} chunk(s)" + (" + loop join" if join else ""))

    client = None if args.dry_run else make_client(args)
    reference = None
    work = args.output_dir / "_chunks"
    if args.reference_image and client:
        reference = upload_as(client, args.reference_image, f"{job_tag('vace_ref')}{args.reference_image.suffix}",
                              work / "_upload")
    elif args.reference_image:
        reference = args.reference_image.name

    generated: dict[int, Path] = {}
    for chunk in chunks + ([join] if join else []):
        frames = run_chunk(args, client, chunk, depth, generated, size, work / chunk.name, reference, seed)
        if args.dry_run:
            return 0  # the payload of the first chunk is enough to check the graph
        for i in range(chunk.keep, chunk.length - chunk.tail):
            if chunk.start + i < n:
                generated[chunk.start + i] = frames[i]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(depth):
        shutil.copyfile(generated[index], args.output_dir / f"world_{frame_number(path, index)}.png")
    print(f"[✓] {n} frames -> {args.output_dir}/world_####.png (chunks kept in {work})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

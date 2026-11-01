#!/usr/bin/env python3
"""Blender depth/normal render passes -> ControlNet-guided AnimateDiff video (MP4) via ComfyUI.

    python scripts/render_blender_video.py \
        --depth-frames ./blender_out/depth/ --normal-frames ./blender_out/normal/ \
        --prompt "cinematic 90s vinyl doll, glowing neon water splash, dynamic studio lighting" \
        --frames 120 --fps 24 --output ./exports/video/previz_shot_01.mp4

Depth passes may be 16-bit PNG, 8-bit PNG or EXR (raw Z with Blender's 1e10 background
is fine). Depth is normalised over the whole sequence and inverted to the ControlNet
convention (near = white) unless --no-invert-depth is given.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_dir, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_files  # noqa: E402
from aether_engine.utils.image_tools import convert_pass_sequence, fit_size, frame_size, list_frames  # noqa: E402

TEMPLATE = "blender_previz_to_video.json"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--depth-frames", type=Path, required=True, help="directory of depth pass frames")
    p.add_argument("--normal-frames", type=Path, help="directory of normal pass frames (optional)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default=None, help="negative prompt (default: template's)")
    p.add_argument("--frames", type=int, default=None, help="use the first N frames (default: all)")
    p.add_argument("--fps", type=float, default=24.0)
    p.add_argument("--output", type=Path, required=True, help="output .mp4 path")
    p.add_argument("--width", type=int, help="render width (default: pass aspect, 512px short side)")
    p.add_argument("--height", type=int, help="render height")
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg", type=float, default=7.0)
    p.add_argument("--depth-strength", type=float, default=0.8)
    p.add_argument("--normal-strength", type=float, default=0.6)
    p.add_argument("--context-length", type=int, default=16, help="AnimateDiff sliding window length")
    p.add_argument("--no-invert-depth", dest="invert_depth", action="store_false",
                   help="depth frames are already near=white")
    models = p.add_argument_group("models (filenames on the server)")
    models.add_argument("--checkpoint", help="SD1.5 checkpoint")
    models.add_argument("--motion-model", help="AnimateDiff motion module")
    models.add_argument("--depth-controlnet")
    models.add_argument("--normal-controlnet")
    add_common_args(p)
    args = p.parse_args(argv)

    require_dir(args.depth_frames, "--depth-frames")
    if args.normal_frames:
        require_dir(args.normal_frames, "--normal-frames")
    if args.output.suffix.lower() != ".mp4":
        raise CLIError("--output must end in .mp4")
    in_range("--fps", args.fps, 1, 120)
    in_range("--depth-strength", args.depth_strength, 0, 2)
    in_range("--normal-strength", args.normal_strength, 0, 2)
    if args.frames is not None:
        in_range("--frames", args.frames, 1, 10000)
    if (args.width is None) != (args.height is None):
        raise CLIError("pass both --width and --height, or neither")
    for name in ("width", "height"):
        value = getattr(args, name)
        if value is not None and value % 8:
            raise CLIError(f"--{name} must be a multiple of 8")
    return args


def count_frames(args: argparse.Namespace) -> int:
    counts = {"depth": len(list_frames(args.depth_frames))}
    if args.normal_frames:
        counts["normal"] = len(list_frames(args.normal_frames))
    n = min(counts.values())
    if len(set(counts.values())) > 1:
        print(f"[!] pass frame counts differ {counts}; using the first {n}")
    if args.frames:
        if args.frames > n:
            raise CLIError(f"--frames {args.frames} but only {n} frames available")
        n = args.frames
    return n


def build(args: argparse.Namespace, n_frames: int, size: tuple[int, int], depth_dir: str,
          normal_dir: str | None, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATE)
    wf.set("positive_prompt", text=args.prompt)
    if args.negative is not None:
        wf.set("negative_prompt", text=args.negative)
    wf.set("depth_frames", directory=depth_dir, image_load_cap=n_frames)
    wf.set("apply_depth", strength=args.depth_strength)
    if normal_dir:
        wf.set("normal_frames", directory=normal_dir, image_load_cap=n_frames)
        wf.set("apply_normal", strength=args.normal_strength)
    else:
        # Single-ControlNet route: sampler takes conditioning straight from the depth apply.
        wf.link("sampler", "positive", "apply_depth", 0)
        wf.link("sampler", "negative", "apply_depth", 1)
        for title in ("apply_normal", "normal_frames", "normal_controlnet"):
            wf.remove(title)
    wf.set("context_options", context_length=args.context_length)
    wf.set("latent", width=size[0], height=size[1], batch_size=n_frames)
    wf.set("sampler", seed=seed, steps=args.steps, cfg=args.cfg)
    wf.set("video_out", frame_rate=args.fps, filename_prefix=f"AetherFX/{tag}")
    for title, value, key in (("checkpoint", args.checkpoint, "ckpt_name"),
                              ("animatediff", args.motion_model, "model_name"),
                              ("depth_controlnet", args.depth_controlnet, "control_net_name"),
                              ("normal_controlnet", args.normal_controlnet, "control_net_name")):
        if value and wf.has(title):
            wf.set(title, **{key: value})
    return wf


def faststart(path: Path) -> None:
    """Move the moov atom to the front so the MP4 streams/scrubs immediately."""
    if not shutil.which("ffmpeg"):
        return
    tmp = path.with_suffix(".faststart.mp4")
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-c", "copy",
                             "-movflags", "+faststart", str(tmp)], capture_output=True)
    if result.returncode == 0:
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)
        print(f"[!] ffmpeg faststart remux failed: {result.stderr.decode(errors='replace').strip()}")


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    tag = job_tag(args.output.stem)
    n_frames = count_frames(args)
    size = (args.width, args.height) if args.width else fit_size(*frame_size(list_frames(args.depth_frames)[0]))
    print(f"[*] {n_frames} frames @ {args.fps:g} fps, {size[0]}x{size[1]}")

    with tempfile.TemporaryDirectory(prefix="aether_previz_") as tmp:
        depth = convert_pass_sequence(args.depth_frames, Path(tmp) / "depth", "depth", size, n_frames,
                                      invert_depth=args.invert_depth)
        normal = (convert_pass_sequence(args.normal_frames, Path(tmp) / "normal", "normal", size, n_frames)
                  if args.normal_frames else None)
        depth_dir, normal_dir = f"{tag}_depth", (f"{tag}_normal" if normal else None)

        if args.dry_run:
            dump_payload(build(args, n_frames, size, depth_dir, normal_dir, tag, seed), args.dump_payload)
            return 0

        client = make_client(args)
        if client.server_device_type() != "cuda" and n_frames > 48:
            print(f"[!] {n_frames} frames on a non-CUDA server will be very slow; consider the RunPod box")
        upload_files(client, depth, subfolder=depth_dir, label="depth frames")
        if normal:
            upload_files(client, normal, subfolder=normal_dir, label="normal frames")

    wf = build(args, n_frames, size, depth_dir, normal_dir, tag, seed)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)

    videos = collect_outputs(client, prompt_id, args.output.parent, suffixes=(".mp4",))
    if not videos:
        raise CLIError(f"prompt {prompt_id} finished but produced no .mp4")
    target = move_to(videos[-1], args.output)
    faststart(target)
    print(f"[✓] {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

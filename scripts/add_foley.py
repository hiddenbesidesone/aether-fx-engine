#!/usr/bin/env python3
r"""Video -> synced Foley / ambience (MMAudio) via ComfyUI, muxed back into the video.

    python scripts/add_foley.py --video ./exports/video/previz_shot_01.mp4 \
        --prompt "plastic toy footsteps on glossy floor, water splash" --output ./exports/video/shot_01_foley.mp4

Writes the MP4 with the new audio track plus the audio alone as <output>.flac. The video keeps its
original frame rate; MMAudio itself watches a 25 fps copy (its sync model's rate).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_file, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402
from render_blender_video import faststart  # noqa: E402

TEMPLATE = "video_foley_api.json"
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
TRAINED_SECONDS = 8.0  # MMAudio's training clip length; quality drops on much longer clips


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--prompt", default="", help="what should be heard (optional; MMAudio also reads the picture)")
    p.add_argument("--negative", default=None, help="what to avoid (default: music, speech)")
    p.add_argument("--duration", type=float, default=None,
                   help="seconds of audio (default: the video's length via ffprobe, else 8)")
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg", type=float, default=4.5)
    p.add_argument("--output", type=Path, default=None, help="output .mp4 (default: exports/video/<name>_foley.mp4)")
    add_common_args(p)
    args = p.parse_args(argv)
    require_file(args.video, "--video")
    if args.video.suffix.lower() not in VIDEO_SUFFIXES:
        raise CLIError(f"--video must be one of {', '.join(VIDEO_SUFFIXES)}")
    args.output = args.output or Path("exports/video") / f"{args.video.stem}_foley.mp4"
    if args.output.suffix.lower() != ".mp4":
        raise CLIError("--output must end in .mp4")
    if args.duration is None:
        args.duration = probe_duration(args.video)
        if args.duration is None:
            print(f"[!] ffprobe not found; generating {TRAINED_SECONDS:g}s (pass --duration to change)")
            args.duration = TRAINED_SECONDS
    in_range("--duration", args.duration, 1, 120)
    in_range("--steps", args.steps, 1, 200)
    in_range("--cfg", args.cfg, 0, 20)
    return args


def probe_duration(video: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                             str(video)], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def build(args: argparse.Namespace, video_name: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATE)
    wf.set("source_video", video=video_name)
    wf.set("video_25fps", video=video_name)
    wf.set("foley", prompt=args.prompt, duration=round(args.duration, 2), steps=args.steps, cfg=args.cfg, seed=seed)
    if args.negative is not None:
        wf.set("foley", negative_prompt=args.negative)
    wf.set("save_audio", filename_prefix=f"AetherFX/foley/{tag}")
    wf.set("video_out", filename_prefix=f"AetherFX/foley/{tag}")
    return wf


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    tag = job_tag(args.video.stem)
    server_name = f"{tag}{args.video.suffix.lower()}"
    print(f"[*] MMAudio: {args.duration:.1f}s of audio, steps={args.steps} cfg={args.cfg:g} seed={seed}")
    if args.duration > TRAINED_SECONDS * 1.5:
        print(f"[!] MMAudio is trained on {TRAINED_SECONDS:g}s clips; for long shots, cut the video and run per shot")

    if args.dry_run:
        dump_payload(build(args, server_name, tag, seed), args.dump_payload)
        return 0

    client = make_client(args)
    with tempfile.TemporaryDirectory(prefix="aether_foley_") as tmp:
        name = upload_as(client, args.video, server_name, Path(tmp))
    wf = build(args, name, tag, seed)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)

    files = collect_outputs(client, prompt_id, args.output.parent, suffixes=(".mp4", ".flac"))
    # VHS writes <prefix>_00001.mp4 (silent) and <prefix>_00001-audio.mp4; history reports the latter.
    videos = sorted((f for f in files if f.suffix == ".mp4"), key=lambda f: "-audio" not in f.stem)
    audio = [f for f in files if f.suffix == ".flac"]
    if not videos:
        raise CLIError(f"prompt {prompt_id} finished but produced no .mp4")
    target = move_to(videos[0], args.output)
    faststart(target)
    for extra in videos[1:]:
        extra.unlink(missing_ok=True)
    print(f"[✓] video {target}")
    if audio:
        print(f"[✓] audio {move_to(audio[0], args.output.with_suffix('.flac'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

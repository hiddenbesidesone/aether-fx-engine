#!/usr/bin/env python3
r"""Start frame + end frame -> video (Wan 2.2 14B first/last frame) via ComfyUI, upscaled to 1080 at 24 fps.

    python scripts/render_flf_video.py --start home.png --end home.png \
        --prompt "the officer turns his head to the camera, nods, then looks ahead again" \
        --output exports/video/rider_nod.mp4

Wan 2.2 renders 1280x720 at 16 fps (5 s = 81 frames). Then, on the same server: SeedVR2 upscales it to
1080 on the short side, and RIFE interpolates it to 24 fps (16 -> 48 -> every 2nd frame). Leave out --end
to end on the start frame (a clip that loops back to its first frame). --fast uses the 4-step LightX2V
LoRAs: ~3 min instead of ~25 min on an L40S, with a little less motion.

The images are centre-cropped to the render aspect (16:9 / 9:16 / 1:1, from the start frame) before upload,
so nothing is stretched.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_file, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402
from render_blender_video import faststart  # noqa: E402

TEMPLATES = {False: "flf_wan22_api.json", True: "flf_wan22_fast_api.json"}
WAN_FPS = 16
MAX_FRAMES = 121  # Wan 2.2 is trained on 81 (5 s); up to ~7.5 s still works, longer drifts
FPS_CHOICES = (16, 24, 32, 48)  # 16 = raw; 24 = RIFE x3 then every 2nd frame; 32 = x2; 48 = x3
SIZES = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (960, 960)}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=Path, required=True, help="first frame (png/jpg)")
    p.add_argument("--end", type=Path, default=None, help="last frame (default: the start frame)")
    p.add_argument("--prompt", required=True, help="what happens between the two frames")
    p.add_argument("--negative", default=None, help="what to avoid (default: Wan's standard negative)")
    p.add_argument("--seconds", type=float, default=5.0, help="clip length (default 5; Wan's sweet spot)")
    p.add_argument("--size", default=None,
                   help="render size WxH, multiples of 16 (default: 1280x720, 720x1280 or 960x960 from the start frame)")
    p.add_argument("--resolution", type=int, default=1080,
                   help="upscale the short side to this with SeedVR2 (default 1080; 0 = no upscale)")
    p.add_argument("--fps", type=int, choices=FPS_CHOICES, default=24, help="output frame rate (default 24)")
    p.add_argument("--fast", action="store_true", help="4-step LightX2V LoRAs (~8x faster, a little less motion)")
    p.add_argument("--steps", type=int, default=None, help="sampler steps (default 20, or 4 with --fast)")
    p.add_argument("--output", type=Path, default=None, help="output .mp4 (default: exports/video/<start>_flf.mp4)")
    add_common_args(p)
    args = p.parse_args(argv)
    require_file(args.start, "--start")
    args.end = args.end or args.start
    require_file(args.end, "--end")
    in_range("--seconds", args.seconds, 1, MAX_FRAMES / WAN_FPS)
    in_range("--resolution", args.resolution, 0, 2160)
    if args.resolution and args.resolution % 2:
        raise CLIError("--resolution must be even")
    args.output = args.output or Path("exports/video") / f"{args.start.stem}_flf.mp4"
    if args.output.suffix.lower() != ".mp4":
        raise CLIError("--output must end in .mp4")
    args.size = parse_size(args.size) if args.size else default_size(args.start)
    args.length = frames_for(args.seconds)
    args.steps = args.steps or (4 if args.fast else 20)
    in_range("--steps", args.steps, 2, 60)
    return args


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise CLIError(f"--size must look like 1280x720, got {text!r}") from None
    if w % 16 or h % 16:
        raise CLIError("--size width and height must be multiples of 16")
    in_range("--size width", w, 256, 1920)
    in_range("--size height", h, 256, 1920)
    return w, h


def default_size(image: Path) -> tuple[int, int]:
    with Image.open(image) as im:
        w, h = im.size
    if w > h * 1.15:
        return SIZES["landscape"]
    if h > w * 1.15:
        return SIZES["portrait"]
    return SIZES["square"]


def frames_for(seconds: float) -> int:
    """Wan needs 4k+1 frames."""
    n = round(seconds * WAN_FPS)
    return min(MAX_FRAMES, (n // 4) * 4 + 1)


def fit(src: Path, size: tuple[int, int], dest: Path) -> Path:
    """Centre-crop to the render aspect, then resize, so the model never sees a stretched frame."""
    w, h = size
    with Image.open(src) as im:
        im = im.convert("RGB")
        scale = max(w / im.width, h / im.height)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        left, top = (im.width - w) // 2, (im.height - h) // 2
        im.crop((left, top, left + w, top + h)).save(dest)
    return dest


def build(args: argparse.Namespace, start_name: str, end_name: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATES[args.fast])
    w, h = args.size
    wf.set("start_image", image=start_name)
    wf.set("end_image", image=end_name)
    wf.set("positive", text=args.prompt)
    if args.negative is not None:
        wf.set("negative", text=args.negative)
    wf.set("flf", width=w, height=h, length=args.length)
    half = args.steps // 2  # Wan 2.2 hands over from the high-noise to the low-noise expert halfway
    wf.set("sampler_high", noise_seed=seed, steps=args.steps, end_at_step=half)
    wf.set("sampler_low", steps=args.steps, start_at_step=half)
    wf.set("upscale", seed=seed)
    wf.set("video_out", filename_prefix=f"AetherFX/flf/{tag}", frame_rate=args.fps)

    tail = [wf.node_id("decode"), 0]
    if args.resolution:
        wf.set("upscale", resolution=args.resolution)
        tail = [wf.node_id("upscale"), 0]
    else:
        wf.rewire([wf.node_id("upscale"), 0], tail)
        for title in ("upscale", "upscale_dit", "upscale_vae"):
            wf.remove(title)
    if args.fps == WAN_FPS:
        wf.rewire([wf.node_id("select_nth"), 0], tail)
        wf.remove("select_nth")
        wf.remove("interpolate")
    else:
        wf.set("interpolate", multiplier=2 if args.fps == 32 else 3)
        if args.fps != 24:
            wf.rewire([wf.node_id("select_nth"), 0], [wf.node_id("interpolate"), 0])
            wf.remove("select_nth")
    return wf


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    tag = job_tag(args.start.stem)
    w, h = args.size
    loop = args.end.resolve() == args.start.resolve()
    print(f"[*] Wan 2.2 {'fast (4 steps)' if args.fast else f'{args.steps} steps'}: {w}x{h}, {args.length} frames "
          f"({args.length / WAN_FPS:.1f}s){', ends on the start frame' if loop else ''}, seed {seed}")
    print(f"[*] then {'SeedVR2 -> ' + str(args.resolution) + 'p, ' if args.resolution else ''}{args.fps} fps")

    with tempfile.TemporaryDirectory(prefix="aether_flf_") as tmp:
        tmp = Path(tmp)
        start = fit(args.start, args.size, tmp / f"{tag}_start.png")
        end = start if loop else fit(args.end, args.size, tmp / f"{tag}_end.png")
        if args.dry_run:
            dump_payload(build(args, start.name, end.name, tag, seed), args.dump_payload)
            return 0
        client = make_client(args)
        start_name = upload_as(client, start, start.name, tmp)
        end_name = start_name if loop else upload_as(client, end, end.name, tmp)

    wf = build(args, start_name, end_name, tag, seed)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)
    files = collect_outputs(client, prompt_id, args.output.parent, suffixes=(".mp4",))
    if not files:
        raise CLIError(f"prompt {prompt_id} finished but produced no .mp4")
    target = move_to(files[0], args.output)
    faststart(target)
    print(f"[✓] video {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

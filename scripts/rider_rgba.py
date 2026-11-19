#!/usr/bin/env python3
"""Green-screen rider frames + matte frames -> straight-alpha RGBA PNGs with the green removed.

The last step of Workflow 1 in docs/gemini/05_police_bike_comfyui.md. ComfyUI does the upscale
(SeedVR2) and the matte (BiRefNet or MatAnyone) and saves two PNG sequences; this joins them:

    python scripts/rider_rgba.py --frames upscaled/clip_03 --matte matte/clip_03 \
        --output rider_rgba/clip_03

Green is removed in two ways, both limited to where the matte is see-through or close to its
edge, so solid yellow-green areas (hi-vis jacket, livery) keep their colour:

1. See-through pixels (spokes, windscreen, edges) are a mix of the rider and the green screen.
   The screen's share is taken back out: rider = (pixel - (1 - alpha) * screen) / alpha, with the
   screen colour measured per frame from the pixels the matte marks as background.
2. Pixels there that still look like the screen (within --tolerance of its colour) have their
   green limited to max(red, blue). The jacket (about 140/180/105) is far enough from the screen
   to be left alone; lower --tolerance if it greys at the edges, raise it if green fringes remain.

Frames pair up by frame number; output is rider_####.png with the same numbers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import CLIError, in_range, require_dir  # noqa: E402
from aether_engine.utils.image_tools import frames_by_number  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frames", type=Path, required=True, help="folder of (upscaled) green-screen RGB frames")
    p.add_argument("--matte", type=Path, required=True, help="folder of matte frames, white = rider")
    p.add_argument("--output", type=Path, required=True, help="folder for rider_####.png (RGBA)")
    p.add_argument("--edge", type=int, default=3, help="px from the matte edge that get despilled (default 3)")
    p.add_argument("--despill", type=float, default=1.0, help="0 = off, 1 = full (default)")
    p.add_argument("--tolerance", type=float, default=0.25,
                   help="how close to the screen colour (0-1, RGB distance) a pixel must be to get its green "
                        "limited (default 0.25)")
    p.add_argument("--screen", help="screen colour as R,G,B (default: measured per frame)")
    args = p.parse_args(argv)
    require_dir(args.frames, "--frames")
    require_dir(args.matte, "--matte")
    in_range("--edge", args.edge, 0, 64)
    in_range("--despill", args.despill, 0, 1)
    in_range("--tolerance", args.tolerance, 0.01, 1)
    if args.screen:
        try:
            args.screen = np.array([float(v) for v in args.screen.split(",")], dtype=np.float32) / 255
            assert args.screen.shape == (3,)
        except (ValueError, AssertionError):
            raise CLIError("--screen must be R,G,B, e.g. 60,170,80")
    return args


def screen_colour(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Median colour of the clear background (alpha ~ 0)."""
    background = rgb[alpha < 0.02]
    if len(background) < 100:
        raise CLIError("the matte leaves almost no background to measure the screen colour; pass --screen R,G,B")
    return np.median(background, axis=0)


def despill_weight(alpha: np.ndarray, edge: int) -> np.ndarray:
    """1 where the matte is see-through or within ``edge`` px of its edge, 0 deep inside the rider."""
    soft = (alpha > 0.002) & (alpha < 0.998)
    if edge:
        outside = Image.fromarray(((alpha < 0.5) * 255).astype(np.uint8))
        near = np.asarray(outside.filter(ImageFilter.MaxFilter(2 * edge + 1))) > 0
        soft |= near & (alpha > 0.002)
    return soft.astype(np.float32)


def unmix(rgb: np.ndarray, alpha: np.ndarray, screen: np.ndarray, weight: np.ndarray, despill: float,
          tolerance: float) -> np.ndarray:
    a = alpha[..., None]
    w = weight * despill
    fg = np.where(a > 0.05, (rgb - (1 - a) * screen) / np.maximum(a, 0.05), rgb)
    out = np.clip(rgb + w[..., None] * (np.clip(fg, 0, 1) - rgb), 0, 1)
    closeness = np.clip(1 - np.linalg.norm(out - screen, axis=-1) / tolerance, 0, 1)
    limit = np.maximum(out[..., 0], out[..., 2])
    out[..., 1] -= w * closeness * np.clip(out[..., 1] - limit, 0, None)
    return out


def process(frame: Path, matte: Path, dst: Path, args: argparse.Namespace) -> None:
    with Image.open(frame) as img:
        rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255
    with Image.open(matte) as img:
        img = img.convert("L")
        if img.size != (rgb.shape[1], rgb.shape[0]):
            img = img.resize((rgb.shape[1], rgb.shape[0]), Image.Resampling.LANCZOS)
        alpha = np.asarray(img, dtype=np.float32) / 255
    screen = args.screen if args.screen is not None else screen_colour(rgb, alpha)
    out = unmix(rgb, alpha, screen, despill_weight(alpha, args.edge), args.despill,
                args.tolerance)
    rgba = np.dstack([out, alpha])
    Image.fromarray(np.round(rgba * 255).astype(np.uint8), "RGBA").save(dst)


def main(argv=None) -> int:
    args = parse_args(argv)
    frames, mattes = frames_by_number(args.frames), frames_by_number(args.matte)
    missing = sorted(set(frames) ^ set(mattes))
    if missing:
        raise CLIError(f"frame numbers don't match between --frames and --matte (e.g. {missing[:5]})")
    args.output.mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(max(frames))))
    for i, number in enumerate(sorted(frames), 1):
        process(frames[number], mattes[number], args.output / f"rider_{number:0{width}d}.png", args)
        print(f"\r  {i}/{len(frames)}", end="", flush=True)
    print(f"\n[✓] {len(frames)} RGBA frames -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

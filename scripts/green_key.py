#!/usr/bin/env python3
"""Green-screen frames -> soft matte frames (white = subject), a quick key without a GPU.

    python scripts/green_key.py --frames green/ride_idle --output matte/ride_idle
    python scripts/rider_rgba.py --frames green/ride_idle --matte matte/ride_idle \
        --output rider_rgba/ride_idle --edge 5 --tolerance 0.45

A colour-difference key on how green a pixel is *relative to its brightness*, so the screen in shadow
(e.g. under the bike) keys out like the lit screen. Two guards keep the subject solid:

- near-black pixels (tyres, boots) stay opaque, where the green ratio is just noise;
- anything with real red in it stays opaque: hi-vis yellow-green (red/green ~0.7) is far from the
  screen (~0.15), so the jacket and livery don't get holes.

See-through areas (windscreen, spokes) get partial alpha; rider_rgba.py then takes the screen colour
back out of them. For finals, an AI matte (BiRefNet / MatAnyone) is cleaner on motion-blurred spokes.
--choke pulls the edge in by N px (with a slight blur) when a thin green rim remains.
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
    p.add_argument("--frames", type=Path, required=True, help="folder of green-screen RGB frames")
    p.add_argument("--output", type=Path, required=True, help="folder for matte_####.png")
    p.add_argument("--low", type=float, default=0.22,
                   help="green ratio below which a pixel is fully subject (default 0.22)")
    p.add_argument("--high", type=float, default=0.38,
                   help="green ratio above which a pixel is fully screen (default 0.38)")
    p.add_argument("--keep-red", type=float, default=0.42,
                   help="red/green ratio above which a pixel is always kept (default 0.42)")
    p.add_argument("--choke", type=int, default=0, help="pull the matte edge in by N px (default 0)")
    args = p.parse_args(argv)
    require_dir(args.frames, "--frames")
    in_range("--low", args.low, 0, 1)
    in_range("--high", args.high, 0, 1)
    if args.high <= args.low:
        raise CLIError("--high must be above --low")
    in_range("--keep-red", args.keep_red, 0.2, 1)
    in_range("--choke", args.choke, 0, 8)
    return args


def matte(rgb: np.ndarray, low: float, high: float, keep_red: float) -> np.ndarray:
    """rgb in 0..255 floats -> alpha in 0..1 (1 = subject)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    ratio = (g - np.maximum(r, b)) / np.maximum(g, 1)
    screen = np.clip((ratio - low) / (high - low), 0, 1)
    screen *= np.clip((g - 12) / 14, 0, 1)
    screen *= np.clip((keep_red - r / np.maximum(g, 1)) / 0.17, 0, 1)
    return 1 - screen


def process(src: Path, dst: Path, args: argparse.Namespace) -> None:
    with Image.open(src) as img:
        rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    alpha = Image.fromarray(np.round(matte(rgb, args.low, args.high, args.keep_red) * 255).astype(np.uint8))
    alpha = alpha.filter(ImageFilter.MedianFilter(3))
    if args.choke:
        alpha = alpha.filter(ImageFilter.MinFilter(2 * args.choke + 1)).filter(ImageFilter.GaussianBlur(0.7))
    alpha.save(dst)


def main(argv=None) -> int:
    args = parse_args(argv)
    frames = frames_by_number(args.frames)
    if not frames:
        raise CLIError(f"no frames in {args.frames}")
    args.output.mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(max(frames))))
    for i, number in enumerate(sorted(frames), 1):
        process(frames[number], args.output / f"matte_{number:0{width}d}.png", args)
        print(f"\r  {i}/{len(frames)}", end="", flush=True)
    print(f"\n[✓] {len(frames)} mattes -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

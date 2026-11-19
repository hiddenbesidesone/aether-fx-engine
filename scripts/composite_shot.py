#!/usr/bin/env python3
"""Workflow 3 of the Police Bike brief: AI world x shadow, then the rider on top, frame by frame.

    python scripts/composite_shot.py --world exports/world/loop_neon --shadow shots/loop/shadow \
        --rider rider_in_frame/loop --output exports/comp/loop_neon --shadow-strength 0.8

Every sequence pairs up by frame number (world_0001, shadow_0001, rider_0001 ...). The world is
resized to the shadow pass's size; the rider RGBA (straight alpha) is expected already placed in
frame at that size, as the Blender stage supplies it. Without --rider you get world x shadow only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import CLIError, in_range, require_dir  # noqa: E402
from aether_engine.utils.image_tools import frames_by_number  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--world", type=Path, required=True, help="AI world frames (world_####.png)")
    p.add_argument("--shadow", type=Path, required=True, help="shadow pass frames, white = no shadow")
    p.add_argument("--rider", type=Path, help="rider RGBA frames, placed in frame")
    p.add_argument("--output", type=Path, required=True, help="folder for comp_####.png")
    p.add_argument("--shadow-strength", type=float, default=1.0, help="0 = no shadow, 1 = full multiply")
    args = p.parse_args(argv)
    for name in ("world", "shadow", "rider"):
        if getattr(args, name):
            require_dir(getattr(args, name), f"--{name}")
    in_range("--shadow-strength", args.shadow_strength, 0, 1)
    return args


def load(path: Path, mode: str, size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(path) as img:
        img = img.convert(mode)
        if size and img.size != size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return np.asarray(img, dtype=np.float32) / 255


def composite(world: np.ndarray, shadow: np.ndarray, rider: np.ndarray | None, strength: float) -> np.ndarray:
    out = world * (1 - strength * (1 - shadow[..., None]))
    if rider is not None:
        a = rider[..., 3:]
        out = rider[..., :3] * a + out * (1 - a)
    return out


def main(argv=None) -> int:
    args = parse_args(argv)
    seqs = {"world": frames_by_number(args.world), "shadow": frames_by_number(args.shadow)}
    if args.rider:
        seqs["rider"] = frames_by_number(args.rider)
    numbers = set(seqs["shadow"])
    for name, seq in seqs.items():
        if set(seq) != numbers:
            diff = sorted(set(seq) ^ numbers)[:5]
            raise CLIError(f"--{name} frame numbers don't match --shadow (e.g. {diff}); no frame may be missing")
    args.output.mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(max(numbers))))
    for i, n in enumerate(sorted(numbers), 1):
        shadow = load(seqs["shadow"][n], "L")
        size = (shadow.shape[1], shadow.shape[0])
        rider = load(seqs["rider"][n], "RGBA", size) if args.rider else None
        out = composite(load(seqs["world"][n], "RGB", size), shadow, rider, args.shadow_strength)
        Image.fromarray(np.round(out * 255).astype(np.uint8)).save(args.output / f"comp_{n:0{width}d}.png")
        print(f"\r  {i}/{len(numbers)}", end="", flush=True)
    print(f"\n[✓] {len(numbers)} frames -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

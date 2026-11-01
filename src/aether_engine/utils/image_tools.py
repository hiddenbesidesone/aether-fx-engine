"""Image preprocessing: square subject framing for 3D, and Blender pass conversion."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

FRAME_SUFFIXES = (".png", ".exr", ".tif", ".tiff", ".jpg", ".jpeg")
# Blender writes ~1e10 for background pixels in a raw Z pass.
DEPTH_BACKGROUND_THRESHOLD = 1e9


# --------------------------------------------------------------- 3D framing

def subject_bbox(img: Image.Image, alpha_threshold: int = 8) -> tuple[int, int, int, int]:
    """Bounding box of the subject: the opaque region if the image has a useful alpha
    channel, otherwise the whole image."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alpha = np.asarray(img.convert("RGBA"))[..., 3]
        ys, xs = np.nonzero(alpha > alpha_threshold)
        if len(xs) and (alpha <= alpha_threshold).any():
            return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    return 0, 0, img.width, img.height


def border_color(rgb: np.ndarray) -> tuple[int, int, int]:
    """Median colour of the outermost pixel ring; used to pad opaque images seamlessly."""
    ring = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return tuple(int(v) for v in np.median(ring, axis=0))


def square_pad_subject(img: Image.Image, padding: float = 0.10, size: int | None = 1024) -> Image.Image:
    """Crop to the subject, centre it on a square canvas with ``padding`` margin per side.

    Transparent inputs stay transparent (RGBA); opaque inputs are padded with their
    border colour so background removal downstream sees a clean, flat surround.
    """
    if not 0 <= padding < 0.5:
        raise ValueError("padding must be in [0, 0.5)")
    x0, y0, x1, y1 = subject_bbox(img)
    has_alpha = (x0, y0, x1, y1) != (0, 0, img.width, img.height) or img.mode == "RGBA"
    subject = img.convert("RGBA" if has_alpha else "RGB").crop((x0, y0, x1, y1))

    side = int(round(max(subject.size) / (1 - 2 * padding)))
    if has_alpha:
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    else:
        canvas = Image.new("RGB", (side, side), border_color(np.asarray(subject)))
    offset = ((side - subject.width) // 2, (side - subject.height) // 2)
    canvas.paste(subject, offset, subject if has_alpha else None)
    if size and side != size:
        canvas = canvas.resize((size, size), Image.Resampling.LANCZOS)
    return canvas


def prepare_3d_input(src: Path, dst: Path, padding: float = 0.10, size: int = 1024) -> Path:
    with Image.open(src) as img:
        img.load()
        out = square_pad_subject(img, padding=padding, size=size)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst.with_suffix(".png"))
    return dst.with_suffix(".png")


# ---------------------------------------------------------- frame sequences

def list_frames(directory: Path) -> list[Path]:
    frames = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() in FRAME_SUFFIXES)
    if not frames:
        raise FileNotFoundError(f"no frames ({', '.join(FRAME_SUFFIXES)}) in {directory}")
    return frames


def read_exr(path: Path) -> np.ndarray:
    """Read an OpenEXR file as float32 (H, W, C) RGB, via OpenCV."""
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("EXR input needs OpenCV: pip install 'aether-fx-engine[exr]'") from exc
    data = cv2.imread(str(path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    if data is None:
        raise RuntimeError(f"could not read {path} (is OPENCV_IO_ENABLE_OPENEXR set before cv2 import?)")
    data = data.astype(np.float32)
    if data.ndim == 3:
        data = data[..., :3][..., ::-1]  # BGR(A) -> RGB
    return data


def read_frame(path: Path) -> np.ndarray:
    """Read any supported frame as float32 with its native value range preserved."""
    if path.suffix.lower() == ".exr":
        return read_exr(path)
    with Image.open(path) as img:
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            return np.asarray(img, dtype=np.float32)
        if img.mode in ("RGB", "RGBA") and _png_bit_depth(path) == 16:
            # Pillow truncates 16-bit RGB PNGs to 8-bit; OpenCV keeps the full range.
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError(f"{path} is a 16-bit RGB PNG; install opencv to read it") from exc
            return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)[..., 2::-1].astype(np.float32)
        return np.asarray(img)


def _png_bit_depth(path: Path) -> int | None:
    if path.suffix.lower() != ".png":
        return None
    with path.open("rb") as fh:
        header = fh.read(26)
    return header[24] if len(header) == 26 and header[12:16] == b"IHDR" else None


def _to_gray(arr: np.ndarray) -> np.ndarray:
    return arr if arr.ndim == 2 else arr[..., 0]


def depth_range(frames: list[Path]) -> tuple[float, float]:
    """Global min/max over the whole sequence (per-frame normalisation flickers)."""
    lo, hi = np.inf, -np.inf
    for path in frames:
        d = _to_gray(read_frame(path)).astype(np.float32)
        valid = d[np.isfinite(d) & (d < DEPTH_BACKGROUND_THRESHOLD)]
        if valid.size:
            lo, hi = min(lo, float(valid.min())), max(hi, float(valid.max()))
    if not np.isfinite(lo) or hi <= lo:
        raise ValueError("depth sequence has no usable range")
    return lo, hi


def normalize_depth(depth: np.ndarray, lo: float, hi: float, invert: bool = True) -> np.ndarray:
    """Map depth to 8-bit. ``invert=True`` gives the ControlNet convention (near = white)
    from Blender's convention (near = small/dark). Background pixels become black."""
    d = _to_gray(depth).astype(np.float32)
    background = ~np.isfinite(d) | (d >= DEPTH_BACKGROUND_THRESHOLD)
    n = np.clip((d - lo) / (hi - lo), 0.0, 1.0)
    if invert:
        n = 1.0 - n
    n[background] = 0.0
    return (n * 255.0 + 0.5).astype(np.uint8)


def normal_to_rgb(normal: np.ndarray) -> np.ndarray:
    """Float normals in [-1, 1] → 8-bit RGB; already-encoded 8-bit maps pass through."""
    if normal.dtype == np.uint8:
        return normal[..., :3] if normal.ndim == 3 else np.stack([normal] * 3, -1)
    n = normal[..., :3].astype(np.float32)
    if n.max() > 1.5:  # 16-bit encoded map
        return (n / 257.0).round().clip(0, 255).astype(np.uint8)
    return ((n * 0.5 + 0.5).clip(0, 1) * 255 + 0.5).astype(np.uint8)


def convert_pass_sequence(src_dir: Path, dst_dir: Path, kind: str, size: tuple[int, int],
                          limit: int | None = None, invert_depth: bool = True) -> list[Path]:
    """Convert a Blender depth/normal pass directory into 8-bit RGB PNGs at ``size``.

    Output files are renamed to a zero-padded sequence so the server loads them in order.
    """
    frames = list_frames(src_dir)[:limit] if limit else list_frames(src_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    if kind == "depth":
        lo, hi = depth_range(frames)
    out = []
    for i, path in enumerate(frames):
        data = read_frame(path)
        if kind == "depth":
            rgb = np.stack([normalize_depth(data, lo, hi, invert_depth)] * 3, -1)
        elif kind == "normal":
            rgb = normal_to_rgb(data)
        else:
            raise ValueError(f"unknown pass kind {kind!r}")
        img = Image.fromarray(rgb, "RGB")
        if img.size != size:
            img = img.resize(size, Image.Resampling.BILINEAR if kind == "depth" else Image.Resampling.NEAREST)
        dst = dst_dir / f"{kind}_{i:05d}.png"
        img.save(dst)
        out.append(dst)
    return out


def frame_size(path: Path) -> tuple[int, int]:
    data = read_frame(path)
    return data.shape[1], data.shape[0]


def fit_size(width: int, height: int, short_side: int = 512, multiple: int = 8) -> tuple[int, int]:
    """Scale (width, height) so the short side is ``short_side``, both rounded to ``multiple``."""
    scale = short_side / min(width, height)

    def snap(v: float) -> int:
        return max(multiple, int(round(v * scale / multiple)) * multiple)

    return snap(width), snap(height)

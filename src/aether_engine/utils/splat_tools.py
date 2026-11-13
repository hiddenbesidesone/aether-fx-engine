"""3D Gaussian splat .ply helpers: read/write and rigid transforms (rotate, uniform scale, move).

Pure numpy, so it also runs inside Blender's bundled Python (scripts/blender/tidy_trellis_asset.py).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# TRELLIS saves splats Y-up with the subject's head toward -Y; its .glb lands Z-up in Blender.
# Rotating -90 degrees about X, (x, y, z) -> (x, z, -y), puts the splat on top of the mesh.
TRELLIS_TO_BLENDER = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)

_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "uint8": "u1",
          "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4", "short": "i2", "ushort": "u2"}


def read_ply(path: Path) -> tuple[np.ndarray, list[bytes]]:
    """Read a binary little-endian vertex-only .ply as a structured array. Also returns the
    header's comment lines, so writing the file back keeps them."""
    with open(path, "rb") as fh:
        header: list[bytes] = []
        while True:
            line = fh.readline()
            if not line:
                raise ValueError(f"{path}: no end_header, not a .ply")
            header.append(line.rstrip(b"\r\n"))
            if header[-1] == b"end_header":
                break
        if header[0] != b"ply" or b"format binary_little_endian 1.0" not in header:
            raise ValueError(f"{path}: expected a binary little-endian .ply")
        elements = [ln for ln in header if ln.startswith(b"element ")]
        if len(elements) != 1 or not elements[0].startswith(b"element vertex "):
            raise ValueError(f"{path}: expected only a vertex element (a splat), got {elements}")
        fields = []
        for ln in header:
            if ln.startswith(b"property "):
                _, kind, name = ln.decode().split()
                fields.append((name, "<" + _TYPES[kind]))
        count = int(elements[0].split()[-1])
        data = np.frombuffer(fh.read(), dtype=np.dtype(fields), count=count).copy()
    return data, [ln for ln in header if ln.startswith(b"comment ")]


def write_ply(path: Path, data: np.ndarray, comments: list[bytes] = ()) -> Path:
    names = {v: k for k, v in _TYPES.items() if k in ("float", "double", "uchar", "int", "uint", "short", "ushort")}
    lines = [b"ply", b"format binary_little_endian 1.0", *comments, f"element vertex {len(data)}".encode()]
    for name in data.dtype.names:
        lines.append(f"property {names[data.dtype[name].str[1:]]} {name}".encode())
    lines.append(b"end_header")
    with open(path, "wb") as fh:
        fh.write(b"\n".join(lines) + b"\n")
        fh.write(data.astype(data.dtype.newbyteorder("<")).tobytes())
    return Path(path)


def _quat_from_matrix(m: np.ndarray) -> np.ndarray:
    """(w, x, y, z) of a proper rotation matrix."""
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2, m[2, 1] - m[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2, m[0, 2] - m[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2, m[1, 0] - m[0, 1])
    return np.array([w, x, y, z])


def positions(data: np.ndarray) -> np.ndarray:
    return np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float64)


def transform(data: np.ndarray, rotation: np.ndarray = np.eye(3), scale: float = 1.0,
              offset: np.ndarray = np.zeros(3)) -> np.ndarray:
    """Return a copy with every Gaussian rotated, uniformly scaled, then moved:
    p' = scale * R p + offset. Updates positions, normals, orientations (rot_0..3 = w, x, y, z)
    and the log-space scale_* fields. Colour (incl. higher SH bands) is left alone, which is
    exact for the base colour and approximate for any view-dependent bands."""
    rotation = np.asarray(rotation, dtype=np.float64)
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6) or np.linalg.det(rotation) < 0:
        raise ValueError("rotation must be a proper rotation matrix (no mirroring)")
    if scale <= 0:
        raise ValueError("scale must be positive")
    out = data.copy()
    xyz = positions(data) @ rotation.T * scale + np.asarray(offset, dtype=np.float64)
    for i, axis in enumerate("xyz"):
        out[axis] = xyz[:, i]
    names = data.dtype.names
    if {"nx", "ny", "nz"} <= set(names):
        n = np.stack([data["nx"], data["ny"], data["nz"]], axis=1) @ rotation.T
        out["nx"], out["ny"], out["nz"] = n[:, 0], n[:, 1], n[:, 2]
    if {"rot_0", "rot_1", "rot_2", "rot_3"} <= set(names):
        rw, rx, ry, rz = _quat_from_matrix(rotation)
        w, x, y, z = (data[f"rot_{i}"].astype(np.float64) for i in range(4))
        # Hamilton product r * q: applies the world rotation after each Gaussian's own.
        out["rot_0"] = rw * w - rx * x - ry * y - rz * z
        out["rot_1"] = rw * x + rx * w + ry * z - rz * y
        out["rot_2"] = rw * y - rx * z + ry * w + rz * x
        out["rot_3"] = rw * z + rx * y - ry * x + rz * w
    for name in names:
        if name.startswith("scale_"):
            out[name] = data[name] + np.log(scale)
    return out

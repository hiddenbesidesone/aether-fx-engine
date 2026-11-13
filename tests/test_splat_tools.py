import numpy as np
import pytest

from aether_engine.utils.splat_tools import TRELLIS_TO_BLENDER, positions, read_ply, transform, write_ply

FIELDS = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
          "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def _splat(n=5, seed=0):
    rng = np.random.default_rng(seed)
    data = np.zeros(n, dtype=[(f, "<f4") for f in FIELDS])
    for f in FIELDS:
        data[f] = rng.normal(size=n)
    return data


def _quat_to_matrix(w, x, y, z):
    n = np.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def test_round_trip_keeps_fields_and_comments(tmp_path):
    data = _splat()
    path = write_ply(tmp_path / "s.ply", data, [b"comment hello"])
    back, comments = read_ply(path)
    assert back.dtype.names == tuple(FIELDS) and comments == [b"comment hello"]
    np.testing.assert_array_equal(back, data)


def test_read_rejects_meshes(tmp_path):
    path = tmp_path / "mesh.ply"
    path.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\n"
                     b"element face 0\nproperty list uchar int vertex_indices\nend_header\n")
    with pytest.raises(ValueError, match="only a vertex element"):
        read_ply(path)


def test_transform_matches_a_rotated_scaled_world():
    data = _splat(seed=1)
    offset = np.array([0.5, -1.0, 2.0])
    out = transform(data, TRELLIS_TO_BLENDER, scale=0.35, offset=offset)
    expected = positions(data) @ TRELLIS_TO_BLENDER.T * 0.35 + offset
    np.testing.assert_allclose(positions(out), expected, atol=1e-5)
    np.testing.assert_allclose(out["scale_0"], data["scale_0"] + np.log(0.35), atol=1e-5)
    np.testing.assert_array_equal(out["f_dc_0"], data["f_dc_0"])
    for i in range(len(data)):  # each Gaussian's orientation is the world rotation applied after its own
        before = _quat_to_matrix(*(float(data[f"rot_{k}"][i]) for k in range(4)))
        after = _quat_to_matrix(*(float(out[f"rot_{k}"][i]) for k in range(4)))
        np.testing.assert_allclose(after, TRELLIS_TO_BLENDER @ before, atol=1e-5)


def test_trellis_rotation_puts_minus_y_up():
    head = np.zeros(1, dtype=[(f, "<f4") for f in FIELDS])
    head["y"], head["rot_0"] = -0.5, 1.0  # TRELLIS splats have the head toward -Y
    assert positions(transform(head, TRELLIS_TO_BLENDER))[0].tolist() == pytest.approx([0, 0, 0.5])


def test_transform_refuses_mirroring():
    with pytest.raises(ValueError, match="proper rotation"):
        transform(_splat(), np.diag([1.0, 1.0, -1.0]))

import numpy as np
import pytest
from PIL import Image

from aether_engine.utils import image_tools as it


def test_square_pad_transparent_subject():
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (100, 50, 300, 150))  # 200x100 subject
    out = it.square_pad_subject(img, padding=0.10, size=None)
    assert out.mode == "RGBA"
    assert out.width == out.height == 250  # 200 / 0.8
    alpha = np.asarray(out)[..., 3]
    ys, xs = np.nonzero(alpha)
    assert xs.min() == 25 and xs.max() == 224  # 10% margin each side horizontally
    assert abs((ys.min() + ys.max()) / 2 - 125) <= 1  # vertically centred


def test_square_pad_opaque_uses_border_colour_and_resizes():
    img = Image.new("RGB", (300, 100), (10, 20, 30))
    out = it.square_pad_subject(img, padding=0.10, size=512)
    assert out.size == (512, 512) and out.mode == "RGB"
    assert out.getpixel((0, 0)) == (10, 20, 30)


def test_depth_16bit_global_normalisation_and_inversion(tmp_path):
    src = tmp_path / "depth"
    src.mkdir()
    for i, (near, far) in enumerate([(1000, 2000), (3000, 4000)]):
        a = np.full((16, 24), far, np.uint16)
        a[:, :12] = near
        Image.fromarray(a).save(src / f"d{i:04d}.png")
    out = it.convert_pass_sequence(src, tmp_path / "out", "depth", (24, 16))
    f0 = np.asarray(Image.open(out[0]))
    f1 = np.asarray(Image.open(out[1]))
    assert f0.shape == (16, 24, 3)
    # Global range 1000..4000, inverted: nearest overall is white, farthest is black.
    assert f0[0, 0, 0] == 255 and f1[0, -1, 0] == 0
    assert f0[0, -1, 0] == pytest.approx(170, abs=1)  # 2000 -> 1 - 1/3


def test_depth_background_is_black():
    d = np.array([[1.0, 2.0, 1e10]], np.float32)
    n = it.normalize_depth(d, 1.0, 2.0)
    assert list(n[0]) == [255, 0, 0]


def test_float_normals_mapped_to_rgb():
    n = np.array([[[-1, 0, 1]]], np.float32)
    assert list(it.normal_to_rgb(n)[0, 0]) == [0, 128, 255]


def test_16bit_rgb_png_read_at_full_depth(tmp_path):
    cv2 = pytest.importorskip("cv2")
    a = np.zeros((4, 4, 3), np.uint16)
    a[..., 2] = 65535  # red channel in BGR order
    p = tmp_path / "n.png"
    cv2.imwrite(str(p), a)
    data = it.read_frame(p)
    assert data.dtype == np.float32 and data[0, 0, 0] == 65535 and data[0, 0, 2] == 0


def test_exr_roundtrip(tmp_path):
    import os
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    cv2 = pytest.importorskip("cv2")
    a = np.random.rand(8, 8, 3).astype(np.float32)
    p = tmp_path / "z.exr"
    if not cv2.imwrite(str(p), a):
        pytest.skip("OpenCV built without OpenEXR")
    assert np.allclose(it.read_exr(p), a[..., ::-1], atol=1e-3)


def test_fit_size():
    assert it.fit_size(1920, 1080) == (912, 512)
    assert it.fit_size(1080, 1920) == (512, 912)

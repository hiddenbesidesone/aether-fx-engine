import numpy as np
import pytest
from PIL import Image

import composite_shot
import rider_rgba

SCREEN = np.array([60, 170, 80], dtype=np.float32)
JACKET = np.array([140, 180, 105], dtype=np.float32)  # genuinely yellow-green: must survive


def _rider_clip(root, n=2):
    """A jacket-coloured block on green, with a 50% see-through column (a spoke) on its left edge."""
    (root / "frames").mkdir(parents=True)
    (root / "matte").mkdir()
    for i in range(1, n + 1):
        rgb = np.tile(SCREEN, (40, 60, 1))
        alpha = np.zeros((40, 60), np.float32)
        rgb[10:30, 20:40] = JACKET
        alpha[10:30, 20:40] = 1
        rgb[10:30, 19] = 0.5 * JACKET + 0.5 * SCREEN
        alpha[10:30, 19] = 0.5
        Image.fromarray(rgb.astype(np.uint8)).save(root / "frames" / f"up_{i:04d}.png")
        Image.fromarray((alpha * 255).astype(np.uint8)).save(root / "matte" / f"matte_{i:04d}.png")
    return root


def test_rider_rgba_unmixes_edges_and_keeps_the_jacket(tmp_path):
    root = _rider_clip(tmp_path)
    out = tmp_path / "rgba"
    assert rider_rgba.main(["--frames", str(root / "frames"), "--matte", str(root / "matte"),
                            "--output", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["rider_0001.png", "rider_0002.png"]
    px = np.asarray(Image.open(out / "rider_0001.png")).astype(int)
    assert px.shape[2] == 4 and px[0, 0, 3] == 0
    assert np.abs(px[20, 30, :3] - JACKET).max() <= 1      # solid interior untouched
    assert np.abs(px[20, 20, :3] - JACKET).max() <= 1      # solid edge next to the screen: not greyed
    assert np.abs(px[20, 19, :3] - JACKET).max() <= 3      # see-through edge: screen taken back out
    assert px[20, 19, 3] in (127, 128)


def test_rider_rgba_limits_leftover_spill(tmp_path):
    root = _rider_clip(tmp_path)
    frame = root / "frames" / "up_0001.png"
    rgb = np.asarray(Image.open(frame)).copy()
    rgb[10:30, 21] = (90, 160, 90)  # solid but contaminated: close to the screen colour
    Image.fromarray(rgb).save(frame)
    out = tmp_path / "rgba"
    rider_rgba.main(["--frames", str(root / "frames"), "--matte", str(root / "matte"), "--output", str(out)])
    r, g, b, _ = np.asarray(Image.open(out / "rider_0001.png")).astype(int)[20, 21]
    assert g < 160 and g >= max(r, b)


def test_rider_rgba_rejects_mismatched_numbers(tmp_path):
    root = _rider_clip(tmp_path)
    (root / "matte" / "matte_0002.png").unlink()
    with pytest.raises(SystemExit, match="don't match"):
        rider_rgba.main(["--frames", str(root / "frames"), "--matte", str(root / "matte"), "--output", str(tmp_path)])


def test_composite_shot(tmp_path):
    for name in ("world", "shadow", "rider"):
        (tmp_path / name).mkdir()
    for i in (1, 2):
        Image.new("RGB", (32, 18), (200, 100, 50)).save(tmp_path / "world" / f"world_{i:04d}.png")  # resized up
        shadow = Image.new("L", (64, 36), 255)
        shadow.paste(128, (0, 30, 64, 36))
        shadow.save(tmp_path / "shadow" / f"shadow_{i:04d}.png")
        rider = Image.new("RGBA", (64, 36), (0, 0, 0, 0))
        rider.paste((10, 20, 30, 255), (30, 10, 34, 20))
        rider.save(tmp_path / "rider" / f"rider_{i:04d}.png")
    out = tmp_path / "comp"
    assert composite_shot.main(["--world", str(tmp_path / "world"), "--shadow", str(tmp_path / "shadow"),
                                "--rider", str(tmp_path / "rider"), "--output", str(out)]) == 0
    px = np.asarray(Image.open(out / "comp_0001.png")).astype(int)
    assert px.shape == (36, 64, 3)
    assert tuple(px[5, 5]) == (200, 100, 50)              # world, no shadow
    assert abs(px[33, 5, 0] - 100) <= 1                   # world x 0.5 shadow
    assert tuple(px[15, 31]) == (10, 20, 30)              # rider on top

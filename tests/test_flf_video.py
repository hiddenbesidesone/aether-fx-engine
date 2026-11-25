import json

import pytest
from PIL import Image


def _by_title(wf: dict) -> dict:
    return {n["_meta"]["title"]: n for n in wf.values()}


def _image(path, size=(1280, 720)):
    Image.new("RGB", size, (0, 160, 0)).save(path)
    return path


def _payload(tmp_path, *extra):
    import render_flf_video

    out = tmp_path / "p.json"
    render_flf_video.main(["--start", str(_image(tmp_path / "a.png")), "--prompt", "nod", "--seed", "5",
                           "--dry-run", "--dump-payload", str(out), *extra])
    return json.loads(out.read_text())


def test_render_flf_video(comfy, tmp_path):
    import render_flf_video

    start, end = _image(tmp_path / "home.png"), _image(tmp_path / "away.png", (1920, 1080))
    target = tmp_path / "out" / "nod.mp4"
    assert render_flf_video.main(["--start", str(start), "--end", str(end), "--prompt", "he nods", "--seed", "7",
                                  "--output", str(target), "--comfy-url", comfy.url]) == 0
    assert target.exists()
    nodes = _by_title(comfy.prompts[-1])
    assert nodes["flf"]["inputs"]["width"] == 1280 and nodes["flf"]["inputs"]["length"] == 81
    assert nodes["start_image"]["inputs"]["image"] != nodes["end_image"]["inputs"]["image"]
    assert nodes["sampler_high"]["inputs"]["noise_seed"] == 7
    assert nodes["sampler_high"]["inputs"]["end_at_step"] == nodes["sampler_low"]["inputs"]["start_at_step"] == 10
    assert nodes["upscale"]["inputs"]["resolution"] == 1080
    assert nodes["interpolate"]["inputs"]["multiplier"] == 3
    assert nodes["video_out"]["inputs"]["frame_rate"] == 24


def test_fit_centre_crops_to_the_render_size(tmp_path):
    import render_flf_video

    out = render_flf_video.fit(_image(tmp_path / "wide.png", (2000, 600)), (1280, 720), tmp_path / "f.png")
    assert Image.open(out).size == (1280, 720)


def test_loop_reuses_the_start_frame(tmp_path):
    nodes = _by_title(_payload(tmp_path))
    assert nodes["start_image"]["inputs"]["image"] == nodes["end_image"]["inputs"]["image"]


def test_fast_raw_16fps_drops_upscale_and_interpolation(tmp_path):
    g = _payload(tmp_path, "--fast", "--fps", "16", "--resolution", "0")
    nodes = _by_title(g)
    assert not {"upscale", "interpolate", "select_nth"} & set(nodes)
    decode = next(k for k, v in g.items() if v["_meta"]["title"] == "decode")
    assert nodes["video_out"]["inputs"]["images"] == [decode, 0]
    assert nodes["sampler_high"]["inputs"]["steps"] == 4 and "lora_high" in nodes


@pytest.mark.parametrize("fps,mult,select", [(24, 3, True), (32, 2, False), (48, 3, False)])
def test_fps_choices(tmp_path, fps, mult, select):
    nodes = _by_title(_payload(tmp_path, "--fps", str(fps)))
    assert nodes["interpolate"]["inputs"]["multiplier"] == mult
    assert ("select_nth" in nodes) is select
    assert nodes["video_out"]["inputs"]["frame_rate"] == fps


@pytest.mark.parametrize("seconds,frames", [(5, 81), (3, 49), (7.5, 121), (2.2, 33)])
def test_length_is_4k_plus_1(tmp_path, seconds, frames):
    assert _by_title(_payload(tmp_path, "--seconds", str(seconds)))["flf"]["inputs"]["length"] == frames


def test_portrait_start_frame_picks_portrait_size(tmp_path):
    import render_flf_video

    assert render_flf_video.default_size(_image(tmp_path / "p.png", (1080, 1920))) == (720, 1280)
    assert render_flf_video.default_size(_image(tmp_path / "s.png", (1000, 1000))) == (960, 960)


def test_bad_size_is_rejected(tmp_path):
    import render_flf_video
    from aether_engine.cli import CLIError

    with pytest.raises(CLIError, match="multiples of 16"):
        render_flf_video.parse_size("1280x721")

import json

from PIL import Image

import render_world_vace as rwv


def _depth(root, n):
    root.mkdir(parents=True)
    for i in range(n):
        Image.new("L", (96, 54), 40 + i % 200).save(root / f"depth_{i + 1:04d}.png")
    return root


def test_plan_chunks_covers_every_frame_with_valid_lengths():
    for n in (5, 81, 89, 200, 267):
        chunks = rwv.plan_chunks(n, 81, 13)
        assert chunks[0].start == 0 and chunks[0].keep == 0
        assert all((c.length - 1) % 4 == 0 and c.length <= 81 for c in chunks)
        assert all(c.keep == 13 for c in chunks[1:])
        assert chunks[-1].start + chunks[-1].length >= n
        for a, b in zip(chunks, chunks[1:]):
            assert b.start == a.start + a.length - 13  # next chunk starts on the last 13 generated frames


def test_plan_loop_join_wraps_to_frame_one():
    join = rwv.plan_loop_join(89, 16, 13)
    assert (join.length - 1) % 4 == 0
    assert join.keep == join.tail == 13
    assert join.start + join.length - join.tail == 89  # tail frames are 1..13 of the shot


def test_prompt_schedule():
    schedule = [(1, "neon"), (40, "forest")]
    assert rwv.prompt_at(schedule, 0) == "neon"
    assert rwv.prompt_at(schedule, 38) == "neon"
    assert rwv.prompt_at(schedule, 39) == "forest"


def test_render_world_chunks_and_loop(comfy, tmp_path):
    depth = _depth(tmp_path / "depth", 30)
    out = tmp_path / "world"
    rc = rwv.main(["--depth-frames", str(depth), "--output-dir", str(out), "--prompt", "neon city",
                   "--prompt-at", "20", "forest", "--chunk", "17", "--overlap", "5", "--loop", "--loop-frames", "6",
                   "--width", "96", "--height", "48", "--seed", "7", "--comfy-url", comfy.url])
    assert rc == 0
    assert sorted(p.name for p in out.glob("world_*.png")) == [f"world_{i:04d}.png" for i in range(1, 31)]
    vace = [next(n for n in wf.values() if n["class_type"] == "WanVaceToVideo") for wf in comfy.prompts]
    assert [v["inputs"]["length"] for v in vace] == [17, 17, 9, 17]  # chunks 0-2 (the last one short), loop join
    assert "control_masks" not in vace[0]["inputs"] and "control_masks" in vace[1]["inputs"]
    texts = [next(n["inputs"]["text"] for n in wf.values() if n["_meta"]["title"] == "positive_prompt")
             for wf in comfy.prompts]
    assert texts == ["neon city", "neon city", "forest", "forest"]  # switches at the next chunk border
    seeds = {next(n for n in wf.values() if n["class_type"] == "KSampler")["inputs"]["seed"] for wf in comfy.prompts}
    assert seeds == {7}


def test_render_world_resume_skips_finished_chunks(comfy, tmp_path):
    depth = _depth(tmp_path / "depth", 9)
    out = tmp_path / "world"
    args = ["--depth-frames", str(depth), "--output-dir", str(out), "--prompt", "x", "--width", "96",
            "--height", "48", "--comfy-url", comfy.url]
    assert rwv.main(args) == 0 and len(comfy.prompts) == 1
    assert rwv.main(args + ["--resume"]) == 0 and len(comfy.prompts) == 1


def test_render_world_dry_run_with_reference(tmp_path):
    depth = _depth(tmp_path / "depth", 9)
    ref = tmp_path / "style.png"
    Image.new("RGB", (32, 32)).save(ref)
    payload = tmp_path / "payload.json"
    rc = rwv.main(["--depth-frames", str(depth), "--output-dir", str(tmp_path / "w"), "--prompt", "x",
                   "--model", "14b", "--weight-dtype", "fp8_e4m3fn", "--reference-image", str(ref),
                   "--dry-run", "--dump-payload", str(payload)])
    assert rc == 0
    wf = json.loads(payload.read_text())
    by_title = {n["_meta"]["title"]: n for n in wf.values()}
    assert by_title["diffusion_model"]["inputs"]["unet_name"] == "wan2.1_vace_14B_fp16.safetensors"
    assert by_title["vace"]["inputs"]["length"] == 9
    assert "reference_image" in by_title["vace"]["inputs"] and "mask_frames" not in by_title


def test_render_world_rejects_bad_sizes(tmp_path):
    import pytest

    depth = _depth(tmp_path / "depth", 5)
    with pytest.raises(SystemExit, match="multiple of 16"):
        rwv.parse_args(["--depth-frames", str(depth), "--output-dir", "o", "--prompt", "x", "--height", "540"])
    with pytest.raises(SystemExit, match="4k\\+1"):
        rwv.parse_args(["--depth-frames", str(depth), "--output-dir", "o", "--prompt", "x", "--chunk", "80"])

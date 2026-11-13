import json

import numpy as np
import pytest
from PIL import Image

from aether_engine.client import ComfyClient, ComfyExecutionError, ComfyValidationError, _ref_from_path_string


def test_ws_url_follows_http_scheme():
    assert ComfyClient("https://abc-8188.proxy.runpod.net", client_id="x").ws_url == \
        "wss://abc-8188.proxy.runpod.net/ws?clientId=x"
    assert ComfyClient("127.0.0.1:8188", client_id="x").ws_url == "ws://127.0.0.1:8188/ws?clientId=x"


def test_path_strings_become_output_refs():
    assert _ref_from_path_string("proj/proj.glb") == {"filename": "proj.glb", "subfolder": "proj", "type": "output"}
    assert _ref_from_path_string("/workspace/ComfyUI/output/3D/a_00001_.glb")["subfolder"] == "3D"
    assert _ref_from_path_string("some log text") is None


def test_progress_and_outputs(comfy, tmp_path):
    client = ComfyClient(comfy.url)
    events = []
    wf = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "AetherFX/t"}},
          "2": {"class_type": "RepeatLatentBatch", "inputs": {"amount": 2}}}
    prompt_id, _ = client.run(wf, callback=events.append)
    client.close()
    assert [e.value for e in events] == [1, 2, 3]
    files = client.get_output_files(prompt_id, tmp_path)
    assert sorted(f.name for f in files) == ["t_00000_.png", "t_00001_.png"]


def test_execution_error_raises_with_numpy_hint(comfy):
    comfy.fail_with = {"node_id": "4", "node_type": "IF_TrellisImageTo3D", "exception_type": "ImportError",
                       "exception_message": "numpy.core.multiarray failed to import", "traceback": []}
    with ComfyClient(comfy.url) as client, pytest.raises(ComfyExecutionError) as exc:
        client.run({"1": {"class_type": "X", "inputs": {}}})
    assert exc.value.node_id == "4" and "numpy>=1.26.0,<2.0.0" in str(exc.value)


def test_validation_error_decodes_node_errors(comfy):
    comfy.reject_with = {"error": {"message": "Prompt outputs failed validation", "details": ""},
                         "node_errors": {"3": {"class_type": "KSampler", "errors": [
                             {"message": "Value not in list", "details": "ckpt_name: 'x' not in []"}]}}}
    with pytest.raises(ComfyValidationError) as exc:
        ComfyClient(comfy.url).queue_prompt({"3": {"class_type": "KSampler", "inputs": {},
                                                   "_meta": {"title": "sampler"}}})
    assert "node 3 (KSampler, 'sampler')" in str(exc.value) and "Value not in list" in str(exc.value)


# ------------------------------------------------------------------- CLIs

def _concept(path):
    img = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
    img.paste((200, 50, 50, 255), (50, 50, 250, 350))
    img.save(path)
    return path


@pytest.mark.parametrize("engine", ["trellis", "hunyuan"])
def test_generate_3d_asset(comfy, tmp_path, engine):
    import generate_3d_asset

    out = tmp_path / "exports"
    rc = generate_3d_asset.main(["--image", str(_concept(tmp_path / "doll_head.png")), "--engine", engine,
                                 "--steps", "25", "--seed", "5", "--output-dir", str(out),
                                 "--comfy-url", comfy.url])
    assert rc == 0
    assert [p.name for p in out.iterdir()] == [f"doll_head_{engine}_5.glb"]
    wf = comfy.prompts[-1]
    by_title = {n["_meta"]["title"]: n for n in wf.values()}
    if engine == "trellis":
        assert by_title["trellis"]["inputs"]["ss_sampling_steps"] == 25
        assert by_title["trellis"]["inputs"]["slat_sampling_steps"] == 20
    uploaded = Image.open(tmp_path / "doll_head.png")  # original untouched
    assert uploaded.size == (300, 400)


@pytest.mark.parametrize("splat_only", [False, True])
def test_generate_3d_asset_splat(comfy, tmp_path, splat_only):
    import generate_3d_asset

    out = tmp_path / "exports"
    argv = ["--image", str(_concept(tmp_path / "doll.v2.png")), "--export-splat", "--seed", "7",
            "--output-dir", str(out), "--comfy-url", comfy.url]
    argv += ["--splat-only"] if splat_only else ["--texture-mode", "opt"]
    assert generate_3d_asset.main(argv) == 0
    expected = {"doll.v2_trellis_7.ply"} | (set() if splat_only else {"doll.v2_trellis_7.glb"})
    assert {p.name for p in out.iterdir()} == expected
    assert (out / "doll.v2_trellis_7.ply").read_bytes().startswith(b"ply\n")
    trellis = next(n["inputs"] for n in comfy.prompts[-1].values() if n["_meta"]["title"] == "trellis")
    assert trellis["save_gaussian"] is True and trellis["save_glb"] is True
    assert trellis["texture_mode"] == ("blank" if splat_only else "opt")


def test_splat_missing_on_server_is_a_clear_error(comfy, tmp_path):
    import generate_3d_asset

    real = comfy.outputs_for

    def drop_ply(wf):  # node ran but the .ply never landed in output/
        outputs = real(wf)
        for key in [k for k in comfy.files if k[1].endswith(".ply")]:
            del comfy.files[key]
        return outputs
    comfy.outputs_for = drop_ply
    with pytest.raises(SystemExit, match=r"\.ply could not be downloaded"):
        generate_3d_asset.main(["--image", str(_concept(tmp_path / "a.png")), "--export-splat", "--seed", "3",
                                "--output-dir", str(tmp_path / "o"), "--comfy-url", comfy.url])
    # the mesh was already renamed, not left behind under the timestamped job name
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["a_trellis_3.glb"]


def test_default_run_does_not_request_splat(tmp_path):
    import generate_3d_asset

    payload = tmp_path / "p.json"
    generate_3d_asset.main(["--image", str(_concept(tmp_path / "a.png")), "--dry-run", "--dump-payload", str(payload)])
    trellis = next(n["inputs"] for n in json.loads(payload.read_text()).values() if n["_meta"]["title"] == "trellis")
    assert (trellis["save_gaussian"], trellis["save_glb"], trellis["texture_mode"]) == (False, True, "fast")
    # TRELLIS concatenates image + mask: an RGBA image would make 5 channels and crash PIL
    rmbg = next(n["inputs"] for n in json.loads(payload.read_text()).values() if n["class_type"] == "BiRefNetRMBG")
    assert rmbg["background"] == "Color"


def test_default_seed_fits_signed_int32():
    from aether_engine.cli import resolve_seed

    assert all(0 <= resolve_seed(None) <= 2**31 - 1 for _ in range(1000))


def test_mock_rejects_save_glb_false(comfy):
    with ComfyClient(comfy.url) as client, pytest.raises(ComfyExecutionError, match="shape"):
        client.run({"4": {"class_type": "IF_TrellisImageTo3D",
                          "inputs": {"save_glb": False, "save_gaussian": True, "project_name": "p"}}})


@pytest.mark.parametrize("argv, message", [
    (["--engine", "hunyuan", "--export-splat"], "--export-splat needs --engine trellis"),
    (["--engine", "hunyuan", "--texture-mode", "opt"], "--texture-mode needs --engine trellis"),
    (["--splat-only"], "--splat-only needs --export-splat"),
    (["--export-splat", "--splat-only", "--texture-mode", "opt"], "--splat-only skips"),
])
def test_splat_flag_validation(tmp_path, argv, message):
    import generate_3d_asset

    with pytest.raises(SystemExit, match=message):
        generate_3d_asset.main(["--image", str(_concept(tmp_path / "a.png")), "--dry-run", *argv])


def test_trellis_refuses_non_cuda_server(comfy, tmp_path):
    import generate_3d_asset

    comfy.device = "mps"
    with pytest.raises(SystemExit, match="CUDA-only"):
        generate_3d_asset.main(["--image", str(_concept(tmp_path / "a.png")), "--comfy-url", comfy.url,
                                "--output-dir", str(tmp_path)])
    assert not comfy.prompts


def _passes(root, n=6):
    for kind in ("depth", "normal"):
        (root / kind).mkdir(parents=True)
        for i in range(n):
            if kind == "depth":
                Image.fromarray(np.full((90, 160), 1000 + 100 * i, np.uint16)).save(root / kind / f"{i:04d}.png")
            else:
                Image.new("RGB", (160, 90), (128, 128, 255)).save(root / kind / f"{i:04d}.png")
    return root


def test_render_blender_video(comfy, tmp_path):
    import render_blender_video

    root = _passes(tmp_path / "blender_out")
    out = tmp_path / "exports" / "shot.mp4"
    rc = render_blender_video.main(["--depth-frames", str(root / "depth"), "--normal-frames", str(root / "normal"),
                                    "--prompt", "vinyl doll", "--frames", "4", "--fps", "24",
                                    "--output", str(out), "--comfy-url", comfy.url])
    assert rc == 0 and out.read_bytes() == b"mp4"
    by_title = {n["_meta"]["title"]: n for n in comfy.prompts[-1].values()}
    assert by_title["latent"]["inputs"]["batch_size"] == 4
    assert by_title["latent"]["inputs"]["width"] == 912
    assert by_title["depth_frames"]["inputs"]["image_load_cap"] == 4
    assert sum(1 for sub, _ in comfy.uploads if sub.endswith("_depth")) == 4


def test_render_blender_video_depth_only_dry_run(tmp_path):
    import render_blender_video

    root = _passes(tmp_path / "blender_out")
    payload = tmp_path / "payload.json"
    rc = render_blender_video.main(["--depth-frames", str(root / "depth"), "--prompt", "x",
                                    "--output", str(tmp_path / "o.mp4"), "--dry-run", "--dump-payload", str(payload)])
    assert rc == 0
    classes = [n["class_type"] for n in json.loads(payload.read_text()).values()]
    assert classes.count("ControlNetApplyAdvanced") == 1


def _clay(root, n=6):
    root.mkdir(parents=True)
    for i in range(n):
        Image.new("RGB", (160, 90), (120 + i, 120, 120)).save(root / f"{i:04d}.png")
    return root


def test_render_blender_video_clay(comfy, tmp_path):
    import render_blender_video

    out = tmp_path / "shot.mp4"
    rc = render_blender_video.main(["--clay", str(_clay(tmp_path / "clay")), "--prompt", "vinyl doll",
                                    "--frames", "5", "--output", str(out), "--comfy-url", comfy.url])
    assert rc == 0 and out.read_bytes() == b"mp4"
    wf = comfy.prompts[-1]
    by_title = {n["_meta"]["title"]: (nid, n) for nid, n in wf.items()}
    assert "normal_frames" not in by_title
    clay_id = by_title["depth_frames"][0]
    assert by_title["depth_estimate"][1]["inputs"]["image"] == [clay_id, 0]
    assert by_title["canny_edges"][1]["inputs"]["image"] == [clay_id, 0]
    assert by_title["apply_depth"][1]["inputs"]["image"] == [by_title["depth_estimate"][0], 0]
    assert by_title["apply_normal"][1]["inputs"]["image"] == [by_title["canny_edges"][0], 0]
    assert "canny" in by_title["normal_controlnet"][1]["inputs"]["control_net_name"]
    assert sum(1 for sub, _ in comfy.uploads if sub.endswith("_clay")) == 5


def test_render_blender_video_clay_depth_only_dry_run(tmp_path):
    import render_blender_video

    payload = tmp_path / "payload.json"
    rc = render_blender_video.main(["--clay", str(_clay(tmp_path / "clay")), "--prompt", "x", "--canny-strength",
                                    "0", "--output", str(tmp_path / "o.mp4"), "--dry-run",
                                    "--dump-payload", str(payload)])
    assert rc == 0
    classes = [n["class_type"] for n in json.loads(payload.read_text()).values()]
    assert classes.count("ControlNetApplyAdvanced") == 1 and "Canny" not in classes
    assert "DepthAnythingV2Preprocessor" in classes


def test_run_brand_stylizer(comfy, tmp_path):
    import run_brand_stylizer

    concepts = tmp_path / "concepts"
    concepts.mkdir()
    for name in ("a.png", "b.jpg"):
        Image.new("RGB", (64, 64), (1, 2, 3)).save(concepts / name)
    out = tmp_path / "stylized"
    rc = run_brand_stylizer.main(["--input-dir", str(concepts), "--lora", "latex_vinyl_v2.safetensors:0.8",
                                  "--lora", "gloss.safetensors:0.5:0.3", "--ip-adapter-weight", "0.65",
                                  "--denoise", "0.55", "--prompt", "gloss", "--batch-count", "4",
                                  "--seed", "1", "--output-dir", str(out), "--comfy-url", comfy.url])
    assert rc == 0
    assert len(list(out.glob("*.png"))) == 8
    wf = comfy.prompts[-1]
    loras = [n["inputs"] for n in wf.values() if n["class_type"] == "LoraLoader"]
    assert [(l["lora_name"], l["strength_model"], l["strength_clip"]) for l in loras] == \
        [("latex_vinyl_v2.safetensors", 0.8, 0.8), ("gloss.safetensors", 0.5, 0.3)]


def test_stylizer_rejects_bad_args(tmp_path):
    import run_brand_stylizer

    img = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(img)
    with pytest.raises(SystemExit):
        run_brand_stylizer.main(["--image", str(img), "--prompt", "x", "--ip-adapter-weight", "1.5"])
    with pytest.raises(SystemExit):
        run_brand_stylizer.main(["--image", str(img), "--prompt", "x", "--lora", "a:b:c:d"])


def test_preflight_names_missing_model(comfy, tmp_path):
    import run_brand_stylizer

    img = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(img)
    with pytest.raises(SystemExit, match="ckpt_name='missing.safetensors' not available"):
        run_brand_stylizer.main(["--image", str(img), "--prompt", "x", "--checkpoint", "missing.safetensors",
                                 "--comfy-url", comfy.url, "--output-dir", str(tmp_path / "o")])

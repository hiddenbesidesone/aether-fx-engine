import json

import pytest

from aether_engine.payload_builder import TEMPLATES_DIR, PayloadError, WorkflowTemplate, is_link


@pytest.mark.parametrize("path", sorted(TEMPLATES_DIR.glob("*.json")), ids=lambda p: p.name)
def test_templates_are_valid_api_graphs(path):
    graph = json.loads(path.read_text())
    assert graph, "empty template"
    wf = WorkflowTemplate(graph, path.stem)
    wf.validate()  # no nulls, all links resolve
    titles = [n["_meta"]["title"] for n in graph.values()]
    assert len(titles) == len(set(titles)), "node titles must be unique"


def test_set_and_link_by_title():
    wf = WorkflowTemplate.load("brand_stylizer_api.json")
    wf.set("sampler", denoise=0.6, seed=7)
    assert wf.node("sampler")["inputs"]["denoise"] == 0.6
    with pytest.raises(PayloadError):
        wf.set("sampler", seed=None)
    with pytest.raises(PayloadError):
        wf.node("nope")


def test_lora_chain_rewires_model_and_clip_consumers():
    wf = WorkflowTemplate.load("brand_stylizer_api.json")
    ckpt = wf.node_id("checkpoint")
    added = wf.insert_lora_chain([("a.safetensors", 0.8, 0.8), ("b.safetensors", 0.5, 0.4)])
    graph = wf.to_api()
    assert graph[added[0]]["inputs"]["model"] == [ckpt, 0]
    assert graph[added[1]]["inputs"]["model"] == [added[0], 0]
    assert wf.node("ipadapter_loader")["inputs"]["model"] == [added[1], 0]
    assert wf.node("positive_prompt")["inputs"]["clip"] == [added[1], 1]
    assert wf.node("negative_prompt")["inputs"]["clip"] == [added[1], 1]
    # VAE (output 2) still comes straight from the checkpoint.
    assert wf.node("decode")["inputs"]["vae"] == [ckpt, 2]


def test_remove_refuses_while_linked():
    wf = WorkflowTemplate.load("blender_previz_to_video.json")
    with pytest.raises(PayloadError):
        wf.remove("apply_normal")
    wf.link("sampler", "positive", "apply_depth", 0)
    wf.link("sampler", "negative", "apply_depth", 1)
    for title in ("apply_normal", "normal_frames", "normal_controlnet"):
        wf.remove(title)
    wf.validate()


def test_check_against_server_reports_missing_and_bad_values():
    wf = WorkflowTemplate.load("brand_stylizer_api.json")
    info = {
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["other.safetensors"]]}}},
        "KSampler": {"input": {"required": {"seed": ["INT", {}], "model": ["MODEL"]}}},
        "LoadImage": {"input": {"required": {"image": [["x.png"]]}}},
    }
    problems = wf.check_against_server(info)
    assert any("not available on server" in p and "other.safetensors" in p for p in problems)
    assert any("IPAdapterAdvanced" in p and "not installed" in p for p in problems)
    # LoadImage accepts uploaded subfolder paths not in its combo list.
    assert not any("source_image" in p for p in problems)


def test_ui_workflow_rejected(tmp_path):
    p = tmp_path / "ui.json"
    p.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(PayloadError, match="Export \\(API\\)"):
        WorkflowTemplate.load(p)


def test_link_detection():
    assert is_link(["3", 0])
    assert not is_link(["a", "b"])
    assert not is_link("3")

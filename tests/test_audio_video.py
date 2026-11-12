import json
from pathlib import Path

import pytest


def _by_title(wf: dict) -> dict:
    return {n["_meta"]["title"]: n for n in wf.values()}


def _audio(path: Path) -> Path:
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


# --------------------------------------------------------------------------- generate_audio


@pytest.mark.parametrize("engine", ["stable-audio", "musicgen"])
def test_generate_audio(comfy, tmp_path, engine):
    import generate_audio

    out = tmp_path / "audio"
    assert generate_audio.main(["--engine", engine, "--prompt", "boom bap beat", "--duration", "20", "--seed", "3",
                                "--output-dir", str(out), "--comfy-url", comfy.url]) == 0
    name = f"{engine.replace('-', '_')}_3.flac"
    assert [p.name for p in out.iterdir()] == [name]
    nodes = _by_title(comfy.prompts[-1])
    if engine == "stable-audio":
        assert nodes["latent"]["inputs"]["seconds"] == 20
        assert nodes["timing"]["inputs"]["seconds_total"] == 20
        assert nodes["positive_prompt"]["inputs"]["text"] == "boom bap beat"
    else:
        assert nodes["musicgen"]["inputs"]["duration"] == 20
        assert nodes["musicgen"]["inputs"]["model_size"] == "medium"


def test_bpm_and_bars_set_length_and_prompt(tmp_path):
    import generate_audio

    payload = tmp_path / "p.json"
    generate_audio.main(["--engine", "musicgen", "--prompt", "trap beat", "--bpm", "120", "--bars", "8",
                         "--seed", "1234567890123", "--dry-run", "--dump-payload", str(payload)])
    mg = _by_title(json.loads(payload.read_text()))["musicgen"]["inputs"]
    assert mg["duration"] == pytest.approx(16.0)  # 8 bars * 4 beats * 0.5 s
    assert mg["prompt"] == "trap beat, 120 BPM"
    assert 0 <= mg["seed"] <= generate_audio.MUSICGEN_SEED_MAX


def test_bpm_already_in_prompt_is_not_repeated():
    import generate_audio

    assert generate_audio.prompt_with_bpm("lofi 85bpm groove", 85) == "lofi 85bpm groove"


@pytest.mark.parametrize("argv, message", [
    (["--engine", "musicgen", "--duration", "40"], "at most 30s"),
    (["--engine", "musicgen", "--bpm", "60", "--bars", "16"], r"64.0s \(16 bars at 60 BPM\)"),
    (["--bars", "4"], "--bars needs --bpm"),
    (["--engine", "musicgen", "--negative", "x"], "only used by --engine stable-audio"),
])
def test_generate_audio_rejects_bad_args(argv, message):
    import generate_audio

    with pytest.raises(SystemExit, match=message):
        generate_audio.main(["--prompt", "x", "--dry-run", *argv])


def test_generate_audio_with_stems(comfy, tmp_path):
    import generate_audio

    out = tmp_path / "audio"
    assert generate_audio.main(["--engine", "musicgen", "--prompt", "x", "--stems", "--seed", "9",
                                "--name", "my_other_beat", "--output-dir", str(out), "--comfy-url", comfy.url]) == 0
    assert {p.name for p in out.iterdir()} == {"my_other_beat.flac"} | {
        f"my_other_beat_{s}.flac" for s in ("bass", "drums", "other", "vocals")}
    wf = comfy.prompts[-1]
    musicgen_id = next(nid for nid, n in wf.items() if n["_meta"]["title"] == "musicgen")
    assert _by_title(wf)["separate"]["inputs"]["audio"] == [musicgen_id, 0]


def test_musicgen_silent_failure_is_reported(comfy, tmp_path):
    import generate_audio

    comfy.musicgen_info = "Error generating audio: CUDA out of memory"
    with pytest.raises(SystemExit, match="MusicGen failed.*CUDA out of memory"):
        generate_audio.main(["--engine", "musicgen", "--prompt", "x", "--output-dir", str(tmp_path),
                             "--comfy-url", comfy.url])


# --------------------------------------------------------------------------- separate_stems


def test_separate_stems(comfy, tmp_path):
    import separate_stems

    out = tmp_path / "stems"
    assert separate_stems.main(["--audio", str(_audio(tmp_path / "beat.v1.wav")), "--output-dir", str(out),
                                "--comfy-url", comfy.url]) == 0
    assert {p.name for p in out.iterdir()} == {f"beat.v1_{s}.flac" for s in ("bass", "drums", "other", "vocals")}
    assert comfy.uploads[-1][1].endswith(".wav")
    assert _by_title(comfy.prompts[-1])["source_audio"]["inputs"]["audio"] == comfy.uploads[-1][1]


def test_separate_stems_rejects_non_audio(tmp_path):
    import separate_stems

    (tmp_path / "x.png").write_bytes(b"png")
    with pytest.raises(SystemExit, match="--audio must be one of"):
        separate_stems.main(["--audio", str(tmp_path / "x.png"), "--dry-run"])


# --------------------------------------------------------------------------- add_foley


def test_add_foley(comfy, tmp_path):
    import add_foley

    video = tmp_path / "shot_01.mp4"
    video.write_bytes(b"mp4")
    target = tmp_path / "out" / "shot_01_foley.mp4"
    assert add_foley.main(["--video", str(video), "--prompt", "toy footsteps", "--duration", "6", "--seed", "2",
                           "--output", str(target), "--comfy-url", comfy.url]) == 0
    assert {p.name for p in target.parent.iterdir()} == {"shot_01_foley.mp4", "shot_01_foley.flac"}
    nodes = _by_title(comfy.prompts[-1])
    uploaded = comfy.uploads[-1][1]
    assert nodes["source_video"]["inputs"]["video"] == nodes["video_25fps"]["inputs"]["video"] == uploaded
    assert nodes["video_25fps"]["inputs"]["force_rate"] == 25
    assert nodes["foley"]["inputs"]["duration"] == 6
    assert nodes["foley"]["inputs"]["prompt"] == "toy footsteps"
    # the muxed video keeps the source frame rate (linked from VHS_VideoInfo.source_fps)
    info_id = next(nid for nid, n in comfy.prompts[-1].items() if n["_meta"]["title"] == "source_info")
    assert nodes["video_out"]["inputs"]["frame_rate"] == [info_id, 0]


def test_add_foley_defaults_to_8s_without_ffprobe(tmp_path, monkeypatch):
    import add_foley

    monkeypatch.setattr(add_foley.shutil, "which", lambda _: None)
    video = tmp_path / "v.mov"
    video.write_bytes(b"mov")
    payload = tmp_path / "p.json"
    add_foley.main(["--video", str(video), "--dry-run", "--dump-payload", str(payload)])
    assert _by_title(json.loads(payload.read_text()))["foley"]["inputs"]["duration"] == 8.0


# --------------------------------------------------------------------------- TRELLIS loader backends


def test_trellis_uses_backends_the_server_has(comfy, tmp_path):
    import generate_3d_asset
    from test_client_and_cli import _concept

    loader = comfy.object_info["IF_TrellisCheckpointLoader"]["input"]["required"]
    loader["attn_backend"] = [["xformers", "naive", "sdpa"]]  # no flash-attn on this server
    assert generate_3d_asset.main(["--image", str(_concept(tmp_path / "a.png")), "--output-dir", str(tmp_path / "o"),
                                   "--comfy-url", comfy.url]) == 0
    assert _by_title(comfy.prompts[-1])["trellis_loader"]["inputs"]["attn_backend"] == "xformers"

#!/usr/bin/env python3
r"""Text -> music / soundscape (Stable Audio Open or MusicGen) via ComfyUI, optionally split into stems.

    # ambient / textures / one-shots: Stable Audio Open (up to 47 s)
    python scripts/generate_audio.py --engine stable-audio \
        --prompt "dark ambient drone, rain on metal roof, distant thunder" --duration 40

    # beats: MusicGen (up to 30 s); --bpm + --bars sets the length to whole bars and adds the BPM to the prompt
    python scripts/generate_audio.py --engine musicgen --prompt "boom bap hip-hop beat, dusty vinyl drums" \
        --bpm 90 --bars 8 --stems --output-dir ./exports/audio/

Writes <name>.flac (and <name>_bass/_drums/_other/_vocals.flac with --stems).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to  # noqa: E402
from separate_stems import add_stem_nodes, save_stems, stem_of  # noqa: E402

TEMPLATES = {"stable-audio": "stable_audio_api.json", "musicgen": "musicgen_api.json"}
MAX_SECONDS = {"stable-audio": 47.0, "musicgen": 30.0}
MUSICGEN_SEED_MAX = 999_999_999  # the node's INT limit


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=sorted(TEMPLATES), default="stable-audio")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default=None, help="Stable Audio negative prompt (default: template's)")
    p.add_argument("--duration", type=float, default=None,
                   help="seconds (default 30; max 47 Stable Audio, 30 MusicGen)")
    p.add_argument("--bpm", type=float, default=None, help="tempo; appended to the prompt as 'NN BPM'")
    p.add_argument("--bars", type=int, default=None, help="with --bpm: length in 4/4 bars (overrides --duration)")
    p.add_argument("--steps", type=int, default=50, help="Stable Audio sampler steps (default 50)")
    p.add_argument("--cfg", type=float, default=None,
                   help="guidance (default: Stable Audio 5.0, MusicGen 3.0)")
    p.add_argument("--model-size", choices=("small", "medium", "large"), default="medium",
                   help="MusicGen model (downloads on first use: ~2.4 / 8 / 14 GB)")
    p.add_argument("--stems", action="store_true", help="also split the result into bass/drums/other/vocals")
    p.add_argument("--name", default=None, help="output file name without extension (default: <engine>_<seed>)")
    p.add_argument("--output-dir", type=Path, default=Path("exports/audio"))
    add_common_args(p)
    args = p.parse_args(argv)

    if args.engine == "musicgen" and args.negative is not None:
        raise CLIError("--negative is only used by --engine stable-audio")
    if args.bars is not None:
        if args.bpm is None:
            raise CLIError("--bars needs --bpm")
        in_range("--bars", args.bars, 1, 64)
        args.duration = args.bars * 4 * 60.0 / args.bpm
    if args.bpm is not None:
        in_range("--bpm", args.bpm, 40, 220)
    args.duration = args.duration if args.duration is not None else min(30.0, MAX_SECONDS[args.engine])
    if args.duration > MAX_SECONDS[args.engine] + 1e-6:
        hint = f" ({args.bars} bars at {args.bpm:g} BPM)" if args.bars else ""
        raise CLIError(f"{args.engine} generates at most {MAX_SECONDS[args.engine]:g}s; asked for "
                       f"{args.duration:.1f}s{hint}")
    in_range("--duration", args.duration, 1, MAX_SECONDS[args.engine])
    in_range("--steps", args.steps, 1, 500)
    return args


def prompt_with_bpm(prompt: str, bpm: float | None) -> str:
    if bpm is None or re.search(r"\d+\s*bpm", prompt, re.IGNORECASE):
        return prompt
    return f"{prompt.rstrip(' ,.')}, {bpm:g} BPM"


def build(args: argparse.Namespace, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATES[args.engine])
    prompt = prompt_with_bpm(args.prompt, args.bpm)
    if args.engine == "stable-audio":
        wf.set("positive_prompt", text=prompt)
        if args.negative is not None:
            wf.set("negative_prompt", text=args.negative)
        wf.set("timing", seconds_total=args.duration)
        wf.set("latent", seconds=args.duration)
        wf.set("sampler", seed=seed, steps=args.steps, cfg=args.cfg if args.cfg is not None else 5.0)
    else:
        wf.set("musicgen", prompt=prompt, duration=args.duration, seed=seed % (MUSICGEN_SEED_MAX + 1),
               model_size=args.model_size, guidance_scale=args.cfg if args.cfg is not None else 3.0)
    wf.set("save_audio", filename_prefix=f"AetherFX/audio/{tag}")
    if args.stems:
        add_stem_nodes(wf, "musicgen" if args.engine == "musicgen" else "decode", f"AetherFX/audio/{tag}")
    return wf


def musicgen_error(client, prompt_id: str) -> str | None:
    """The MusicGen node returns silence plus an 'Error ...' info string instead of raising."""
    entry = client.get_history(prompt_id) or {}
    for out in (entry.get("outputs") or {}).values():
        for text in out.get("text", []) or []:
            if isinstance(text, str) and text.lstrip().lower().startswith("error"):
                return text.strip()
    return None


def main(argv=None) -> int:
    args = parse_args(argv)
    seed = resolve_seed(args.seed)
    name = args.name or f"{args.engine.replace('-', '_')}_{seed}"
    tag = job_tag(name)
    wf = build(args, tag, seed)
    print(f"[*] {args.engine}: {args.duration:.1f}s, seed={seed}"
          + (f", {args.bpm:g} BPM" if args.bpm else "") + (" + stems" if args.stems else ""))
    if args.dry_run:
        dump_payload(wf, args.dump_payload)
        return 0

    client = make_client(args)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)
    if args.engine == "musicgen":
        error = musicgen_error(client, prompt_id)
        if error:
            raise CLIError(f"MusicGen failed (the node returned silence): {error}")

    files = collect_outputs(client, prompt_id, args.output_dir, suffixes=(".flac",))
    mains = [f for f in files if stem_of(f, tag) is None]
    if not mains:
        raise CLIError(f"prompt {prompt_id} finished but produced no audio file")
    base = args.output_dir / name
    print(f"[✓] track  {move_to(mains[0], base.with_suffix('.flac'))}")
    if args.stems:
        for stem, path in save_stems([f for f in files if stem_of(f, tag)], tag, base).items():
            print(f"[✓] {stem:6} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

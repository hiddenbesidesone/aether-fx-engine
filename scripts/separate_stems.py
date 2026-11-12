#!/usr/bin/env python3
r"""Split a track into bass / drums / other / vocals stems (Hybrid Demucs) via ComfyUI.

    python scripts/separate_stems.py --audio ./exports/audio/beat_01.flac --output-dir ./exports/stems/

Writes <name>_bass.flac, <name>_drums.flac, <name>_other.flac, <name>_vocals.flac.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_file)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402

TEMPLATE = "stem_split_api.json"
STEMS = ("bass", "drums", "other", "vocals")  # AudioSeparation output order
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".opus")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audio", type=Path, required=True, help="track to split (wav/flac/mp3/...)")
    p.add_argument("--chunk-length", type=float, default=10.0,
                   help="Demucs window in seconds; longer uses more VRAM (default 10)")
    p.add_argument("--output-dir", type=Path, default=Path("exports/stems"))
    add_common_args(p)
    args = p.parse_args(argv)
    require_file(args.audio, "--audio")
    if args.audio.suffix.lower() not in AUDIO_SUFFIXES:
        raise CLIError(f"--audio must be one of {', '.join(AUDIO_SUFFIXES)}")
    in_range("--chunk-length", args.chunk_length, 1, 60)
    return args


def add_stem_nodes(wf: WorkflowTemplate, source: str, prefix: str, chunk_length: float = 10.0) -> None:
    """Append Demucs separation of ``source`` (a node title with an AUDIO output 0) plus one SaveAudio per stem."""
    wf.add_node("AudioSeparation", {"audio": [wf.node_id(source), 0], "chunk_fade_shape": "linear",
                                    "chunk_length": chunk_length, "chunk_overlap": 0.1}, title="separate")
    for i, stem in enumerate(STEMS):
        wf.add_node("SaveAudio", {"audio": [wf.node_id("separate"), i], "filename_prefix": f"{prefix}_{stem}"},
                    title=f"save_{stem}")


def stem_of(path: Path, tag: str) -> str | None:
    """Which stem a SaveAudio output of job ``tag`` is (``<tag>_<stem>_00001_.flac``), or None."""
    m = re.match(rf"{re.escape(tag)}_({'|'.join(STEMS)})_\d+_?\.", path.name)
    return m.group(1) if m else None


def save_stems(files: list[Path], tag: str, base: Path) -> dict[str, Path]:
    """Rename job ``tag``'s downloaded stem files to <base>_<stem><ext>."""
    saved = {}
    for path in files:
        stem = stem_of(path, tag)
        if stem:
            saved[stem] = move_to(path, base.with_name(f"{base.name}_{stem}{path.suffix}"))
    missing = [s for s in STEMS if s not in saved]
    if missing:
        raise CLIError(f"separation finished but these stems are missing: {', '.join(missing)}")
    return saved


def main(argv=None) -> int:
    args = parse_args(argv)
    tag = job_tag(args.audio.stem)
    server_name = f"{tag}{args.audio.suffix.lower()}"

    def build(name: str) -> WorkflowTemplate:
        wf = WorkflowTemplate.load(TEMPLATE)
        wf.set("source_audio", audio=name)
        wf.set("separate", chunk_length=args.chunk_length)
        for stem in STEMS:
            wf.set(f"save_{stem}", filename_prefix=f"AetherFX/stems/{tag}_{stem}")
        return wf

    if args.dry_run:
        dump_payload(build(server_name), args.dump_payload)
        return 0

    client = make_client(args)
    with tempfile.TemporaryDirectory(prefix="aether_stems_") as tmp:
        name = upload_as(client, args.audio, server_name, Path(tmp))
    wf = build(name)
    preflight(client, wf, args)
    prompt_id = execute(client, wf, args)

    files = collect_outputs(client, prompt_id, args.output_dir, suffixes=(".flac",))
    for stem, path in save_stems(files, tag, args.output_dir / args.audio.stem).items():
        print(f"[✓] {stem:6} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

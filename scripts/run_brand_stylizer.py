#!/usr/bin/env python3
"""Batch concept restyling / material transfer (SDXL + LoRA stack + IP-Adapter + depth ControlNet).

    python scripts/run_brand_stylizer.py --input-dir ./inputs/concepts/ \
        --lora "latex_vinyl_v2.safetensors:0.8" --ip-adapter-weight 0.65 --denoise 0.55 \
        --prompt "hyper-gloss black latex outfit, molded toy seam details, 8k commercial photography" \
        --batch-count 4 --output-dir ./exports/stylized/

Denoise 0.45-0.75 keeps the source silhouette (variations); 1.0 is full synthesis guided
only by IP-Adapter and the depth ControlNet.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aether_engine.cli import (CLIError, add_common_args, dump_payload, execute, in_range, make_client,  # noqa: E402
                               preflight, require_dir, resolve_seed)
from aether_engine.payload_builder import WorkflowTemplate  # noqa: E402
from aether_engine.utils.file_transfer import collect_outputs, job_tag, move_to, upload_as  # noqa: E402

TEMPLATE = "brand_stylizer_api.json"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def parse_lora(spec: str) -> tuple[str, float, float]:
    """"name.safetensors[:model_strength[:clip_strength]]" -> (name, model, clip)."""
    name, *strengths = spec.split(":")
    try:
        values = [float(s) for s in strengths]
    except ValueError:
        values = None
    if not name or values is None or len(values) > 2:
        raise argparse.ArgumentTypeError(f"bad --lora {spec!r}; expected name.safetensors:0.8[:0.8]")
    model = values[0] if values else 1.0
    clip = values[1] if len(values) > 1 else model
    return name, model, clip


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input-dir", type=Path, help="directory of concept images")
    src.add_argument("--image", type=Path, action="append", help="a concept image (repeatable)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default=None, help="negative prompt (default: template's)")
    p.add_argument("--lora", type=parse_lora, action="append", default=[],
                   help="LoRA as name.safetensors:strength[:clip_strength]; repeat to stack")
    p.add_argument("--ip-adapter-weight", type=float, default=0.65, help="0.0-1.0 (default 0.65)")
    p.add_argument("--ip-adapter-preset", default=None, help="IPAdapterUnifiedLoader preset")
    p.add_argument("--denoise", type=float, default=0.55, help="0.45-0.75 variations, 1.0 full synthesis")
    p.add_argument("--controlnet-strength", type=float, default=0.6, help="depth ControlNet strength")
    p.add_argument("--batch-count", type=int, default=4, help="variations per input image")
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--cfg", type=float, default=6.0)
    p.add_argument("--megapixels", type=float, default=1.0, help="working resolution (SDXL ~1.0)")
    models = p.add_argument_group("models (filenames on the server)")
    models.add_argument("--checkpoint", help="SDXL checkpoint")
    models.add_argument("--controlnet", help="SDXL depth ControlNet")
    p.add_argument("--output-dir", type=Path, default=Path("exports/stylized"))
    add_common_args(p)
    args = p.parse_args(argv)

    if args.input_dir:
        require_dir(args.input_dir, "--input-dir")
        args.images = sorted(f for f in args.input_dir.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        if not args.images:
            raise CLIError(f"no images ({', '.join(IMAGE_SUFFIXES)}) in {args.input_dir}")
    else:
        args.images = args.image
        missing = [str(f) for f in args.images if not f.is_file()]
        if missing:
            raise CLIError(f"--image not found: {', '.join(missing)}")
    in_range("--ip-adapter-weight", args.ip_adapter_weight, 0.0, 1.0)
    in_range("--denoise", args.denoise, 0.0, 1.0)
    in_range("--controlnet-strength", args.controlnet_strength, 0.0, 2.0)
    in_range("--batch-count", args.batch_count, 1, 64)
    in_range("--megapixels", args.megapixels, 0.25, 4.0)
    for name, s_model, s_clip in args.lora:
        in_range(f"--lora {name} strength", s_model, -4.0, 4.0)
        in_range(f"--lora {name} clip strength", s_clip, -4.0, 4.0)
    if not (0.45 <= args.denoise <= 0.75 or args.denoise == 1.0):
        print(f"[!] denoise {args.denoise} is outside the tuned ranges (0.45-0.75 or 1.0)")
    return args


def build(args: argparse.Namespace, image_name: str, tag: str, seed: int) -> WorkflowTemplate:
    wf = WorkflowTemplate.load(TEMPLATE)
    wf.insert_lora_chain(args.lora)
    wf.set("source_image", image=image_name)
    wf.set("scale_source", megapixels=args.megapixels)
    wf.set("ipadapter", weight=args.ip_adapter_weight)
    wf.set("positive_prompt", text=args.prompt)
    if args.negative is not None:
        wf.set("negative_prompt", text=args.negative)
    wf.set("apply_controlnet", strength=args.controlnet_strength)
    wf.set("batch", amount=args.batch_count)
    wf.set("sampler", seed=seed, steps=args.steps, cfg=args.cfg, denoise=args.denoise)
    wf.set("save_images", filename_prefix=f"AetherFX/{tag}")
    if args.checkpoint:
        wf.set("checkpoint", ckpt_name=args.checkpoint)
    if args.controlnet:
        wf.set("controlnet", control_net_name=args.controlnet)
    if args.ip_adapter_preset:
        wf.set("ipadapter_loader", preset=args.ip_adapter_preset)
    return wf


def main(argv=None) -> int:
    args = parse_args(argv)
    loras = ", ".join(f"{n}@{m:g}" for n, m, _ in args.lora) or "none"
    print(f"[*] {len(args.images)} image(s) x {args.batch_count}; denoise={args.denoise} "
          f"ip-adapter={args.ip_adapter_weight} loras={loras}")

    if args.dry_run:
        dump_payload(build(args, args.images[0].name, job_tag(args.images[0].stem), resolve_seed(args.seed)),
                     args.dump_payload)
        return 0

    client = make_client(args)
    checked = False
    failures = 0
    with tempfile.TemporaryDirectory(prefix="aether_stylize_") as tmp:
        for i, image in enumerate(args.images, 1):
            seed = resolve_seed(args.seed)
            tag = job_tag(image.stem)
            print(f"\n[{i}/{len(args.images)}] {image.name} (seed {seed})")
            image_name = upload_as(client, image, f"{tag}{image.suffix.lower()}", Path(tmp))
            wf = build(args, image_name, tag, seed)
            if not checked:  # graph shape is identical per image; check the server once
                preflight(client, wf, args)
                checked = True
            try:
                prompt_id = execute(client, wf, args)
            except CLIError as exc:
                failures += 1
                print(f"[!] {image.name} failed: {exc.code}")
                continue
            outputs = collect_outputs(client, prompt_id, args.output_dir, suffixes=(".png",))
            for j, out in enumerate(outputs):
                move_to(out, args.output_dir / f"{image.stem}_s{seed}_{j:02d}.png")
            print(f"[✓] {len(outputs)} image(s) -> {args.output_dir}")

    if failures:
        raise CLIError(f"{failures} of {len(args.images)} image(s) failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

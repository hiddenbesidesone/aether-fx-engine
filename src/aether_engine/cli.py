"""Shared plumbing for the scripts/ CLIs: common flags, preflight, run + report."""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

from .client import ComfyClient, ComfyError, print_progress
from .payload_builder import PayloadError, WorkflowTemplate

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class CLIError(SystemExit):
    def __init__(self, message: str):
        super().__init__(f"error: {message}")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("server")
    group.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"),
                       help="ComfyUI base URL: local, SSH tunnel, or https://<pod-id>-8188.proxy.runpod.net "
                            "(default: $COMFY_URL or http://127.0.0.1:8188)")
    group.add_argument("--timeout", type=float, default=None, help="give up after N seconds of execution")
    group.add_argument("--seed", type=int, default=None, help="sampler seed (default: random)")
    group.add_argument("--skip-preflight", action="store_true",
                       help="don't check node classes/model names against the server's /object_info")
    group.add_argument("--dry-run", action="store_true",
                       help="validate inputs and write the API payload to --dump-payload without contacting the server")
    group.add_argument("--dump-payload", type=Path, default=None, help="write the final API JSON to this path")


def resolve_seed(seed: int | None) -> int:
    return seed if seed is not None else random.randint(0, 2**32 - 1)


def make_client(args: argparse.Namespace) -> ComfyClient:
    client = ComfyClient(args.comfy_url)
    try:
        stats = client.system_stats()
    except Exception as exc:
        raise CLIError(f"cannot reach ComfyUI at {client.base_url}: {exc}")
    device = (stats.get("devices") or [{}])[0]
    print(f"[*] ComfyUI {stats.get('system', {}).get('comfyui_version', '')} at {client.base_url} "
          f"({device.get('type', '?')}: {device.get('name', '?')})")
    return client


def require_cuda_server(client: ComfyClient, job: str) -> None:
    """Abort when the target server can't run CUDA-only extensions (e.g. Apple Silicon)."""
    device = client.server_device_type()
    if device != "cuda":
        raise CLIError(
            f"{job} needs CUDA-only extensions but {client.base_url} runs on '{device}'. "
            f"Run it on the RunPod box instead: --comfy-url https://<pod-id>-8188.proxy.runpod.net "
            f"(or an SSH tunnel to http://127.0.0.1:8188)")


def preflight(client: ComfyClient, template: WorkflowTemplate, args: argparse.Namespace) -> None:
    template.validate()
    if args.skip_preflight:
        return
    problems = template.check_against_server(client.object_info())
    if problems:
        raise CLIError("workflow doesn't match the server:\n  " + "\n  ".join(problems)
                       + "\n(install the missing nodes/models, pass the right names, or --skip-preflight)")


def dump_payload(template: WorkflowTemplate, path: Path | None) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(template.to_api(), indent=2) + "\n")
        print(f"[*] payload written to {path}")


def execute(client: ComfyClient, template: WorkflowTemplate, args: argparse.Namespace) -> str:
    """Queue the workflow, stream progress, and return the prompt_id."""
    dump_payload(template, args.dump_payload)
    try:
        prompt_id, _ = client.run(template.to_api(), callback=print_progress, timeout=args.timeout)
    except (ComfyError, PayloadError) as exc:
        raise CLIError(str(exc))
    finally:
        client.close()
    print(f"[✓] prompt {prompt_id} complete")
    return prompt_id


def require_dir(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise CLIError(f"{label} {path} is not a directory")
    return path


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise CLIError(f"{label} {path} does not exist")
    return path


def in_range(name: str, value: float, lo: float, hi: float) -> float:
    if not lo <= value <= hi:
        raise CLIError(f"{name} must be between {lo} and {hi} (got {value})")
    return value


"""Moving inputs to and outputs from a (possibly remote) ComfyUI server."""

from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from ..client import ComfyClient


def job_tag(prefix: str) -> str:
    """Short unique, filesystem-safe name for one job's uploads/outputs."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", prefix).strip("_") or "job"
    return f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def upload_files(client: ComfyClient, paths: Iterable[Path], subfolder: str = "",
                 workers: int = 8, label: str = "upload") -> list[str]:
    """Upload files concurrently into ``input/<subfolder>``; returns server-side names in order."""
    paths = list(paths)
    done = 0
    lock = threading.Lock()

    def one(path: Path) -> str:
        nonlocal done
        name = client.upload_image(path, subfolder=subfolder)
        with lock:
            done += 1
            print(f"\r  {label}: {done}/{len(paths)}", end="\n" if done == len(paths) else "", flush=True)
        return name

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, paths))


def upload_as(client: ComfyClient, path: Path, name: str, scratch: Path) -> str:
    """Upload ``path`` under a new filename (unique names avoid clobbering other jobs' inputs)."""
    scratch.mkdir(parents=True, exist_ok=True)
    staged = scratch / name
    if staged.resolve() != path.resolve():
        shutil.copyfile(path, staged)
    return client.upload_image(staged)


def collect_outputs(client: ComfyClient, prompt_id: str, dest_dir: Path,
                    suffixes: Iterable[str] | None = None) -> list[Path]:
    paths = client.get_output_files(prompt_id, dest_dir=dest_dir, suffixes=suffixes)
    for path in paths:
        print(f"  saved {path}")
    return paths


def move_to(path: Path, target: Path) -> Path:
    """Move a downloaded file to an exact target path (e.g. --output shot.mp4)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), target)
    return target

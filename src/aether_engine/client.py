"""ComfyUI HTTP + WebSocket client.

Works against a local server (http://127.0.0.1:8188), an SSH tunnel, or a RunPod
proxy (https://<pod-id>-8188.proxy.runpod.net); the WebSocket scheme follows the
HTTP scheme (http → ws, https → wss).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse, urlunparse

import requests
import websocket

DEFAULT_URL = "http://127.0.0.1:8188"

# Output keys ComfyUI nodes use for file results in /history ("gifs" is VHS_VideoCombine).
FILE_OUTPUT_KEYS = ("images", "gifs", "videos", "audio", "3d", "meshes")
FILE_SUFFIXES = (".glb", ".gltf", ".obj", ".ply", ".stl", ".mp4", ".webm", ".mov", ".gif", ".png", ".jpg", ".webp",
                 ".flac", ".wav", ".mp3", ".opus")


class ComfyError(RuntimeError):
    """Base error for ComfyUI failures."""


class ComfyValidationError(ComfyError):
    """The server rejected the prompt before execution (/prompt returned node_errors)."""

    def __init__(self, message: str, node_errors: dict | None = None):
        super().__init__(message)
        self.node_errors = node_errors or {}


class ComfyExecutionError(ComfyError):
    """A node raised during execution (WebSocket execution_error)."""

    def __init__(self, data: dict):
        self.data = data
        self.node_id = data.get("node_id")
        self.node_type = data.get("node_type")
        self.exception_type = data.get("exception_type", "")
        self.exception_message = (data.get("exception_message") or "").strip()
        self.traceback = data.get("traceback") or []
        super().__init__(self._describe())

    def _describe(self) -> str:
        msg = f"node {self.node_id} ({self.node_type}) raised {self.exception_type}: {self.exception_message}"
        hint = diagnose(self.exception_message + "".join(self.traceback))
        return f"{msg}\n  hint: {hint}" if hint else msg


class ComfyInterrupted(ComfyError):
    """Execution was interrupted (e.g. cancelled from the UI)."""


def diagnose(text: str) -> str | None:
    """Map well-known failure signatures to an actionable hint."""
    checks = [
        (("_ARRAY_API", "numpy.core.multiarray failed", "compiled using NumPy 1.x"),
         "NumPy 2.x is installed on the server; reinstall with: pip install 'numpy>=1.26.0,<2.0.0'"),
        (("CUDA out of memory", "OutOfMemoryError", "MPS backend out of memory"),
         "out of GPU memory; lower resolution/frame count or batch size"),
        (("Torch not compiled with CUDA", "No CUDA GPUs are available", "CUDA driver"),
         "this node needs CUDA; point --comfy-url at the RunPod instance"),
        (("No such file or directory", "FileNotFoundError", "not found"),
         "a model or input file is missing on the server; check models/ and the input upload"),
    ]
    for needles, hint in checks:
        if any(n in text for n in needles):
            return hint
    return None


@dataclass
class Progress:
    prompt_id: str
    node: str | None
    value: int
    max: int

    @property
    def fraction(self) -> float:
        return self.value / self.max if self.max else 0.0


ProgressCallback = Callable[[Progress], None]


def _format_node_errors(node_errors: dict, workflow: dict | None = None) -> str:
    lines = []
    for node_id, info in node_errors.items():
        cls = info.get("class_type") or (workflow or {}).get(node_id, {}).get("class_type", "?")
        title = (workflow or {}).get(node_id, {}).get("_meta", {}).get("title")
        label = f"node {node_id} ({cls}{', ' + repr(title) if title else ''})"
        for err in info.get("errors", []):
            detail = err.get("details") or err.get("message", "")
            lines.append(f"  {label}: {err.get('message', '')} {detail}".rstrip())
    return "\n".join(lines)


class ComfyClient:
    def __init__(self, base_url: str | None = None, client_id: str | None = None, timeout: float = 60.0,
                 headers: dict[str, str] | None = None):
        base_url = base_url or os.environ.get("COMFY_URL") or DEFAULT_URL
        if "://" not in base_url:
            base_url = f"http://{base_url}"
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or str(uuid.uuid4())
        self.timeout = timeout
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)
        self._ws: websocket.WebSocket | None = None

    # ------------------------------------------------------------------ HTTP

    @property
    def ws_url(self) -> str:
        parts = urlparse(self.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunparse((scheme, parts.netloc, f"{parts.path}/ws", "", f"clientId={self.client_id}", ""))

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self.session.get(self._url(path), timeout=kwargs.pop("timeout", self.timeout), **kwargs)
        resp.raise_for_status()
        return resp

    def system_stats(self) -> dict:
        return self._get("/system_stats").json()

    def server_device_type(self) -> str:
        """Device type of the ComfyUI server's first torch device: "cuda", "mps" or "cpu"."""
        devices = self.system_stats().get("devices") or [{}]
        return devices[0].get("type", "cpu")

    def object_info(self) -> dict:
        return self._get("/object_info", timeout=max(self.timeout, 120)).json()

    def upload_image(self, file_path: Path | str, subfolder: str = "", overwrite: bool = True,
                     upload_type: str = "input") -> str:
        """Upload a file to the server's input directory; return the name to reference in LoadImage
        (``subfolder/filename`` when a subfolder is used)."""
        file_path = Path(file_path)
        with file_path.open("rb") as fh:
            resp = self.session.post(
                self._url("/upload/image"),
                files={"image": (file_path.name, fh)},
                data={"subfolder": subfolder, "overwrite": str(overwrite).lower(), "type": upload_type},
                timeout=max(self.timeout, 300),
            )
        resp.raise_for_status()
        info = resp.json()
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def queue_prompt(self, workflow: dict) -> str:
        """POST a workflow to /prompt and return its prompt_id.

        Raises ComfyValidationError with decoded node_errors when the server rejects it.
        """
        resp = self.session.post(
            self._url("/prompt"),
            json={"prompt": workflow, "client_id": self.client_id},
            timeout=self.timeout,
        )
        try:
            body = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise ComfyError(f"/prompt returned non-JSON response: {resp.text[:500]}")
        if resp.status_code != 200 or body.get("node_errors"):
            error = body.get("error") or {}
            message = error.get("message", "prompt rejected") if isinstance(error, dict) else str(error)
            details = error.get("details", "") if isinstance(error, dict) else ""
            node_text = _format_node_errors(body.get("node_errors") or {}, workflow)
            raise ComfyValidationError(
                f"{message}{': ' + details if details else ''}" + (f"\n{node_text}" if node_text else ""),
                body.get("node_errors"),
            )
        return body["prompt_id"]

    def get_history(self, prompt_id: str) -> dict | None:
        return self._get(f"/history/{prompt_id}").json().get(prompt_id)

    def interrupt(self) -> None:
        self.session.post(self._url("/interrupt"), timeout=self.timeout)

    def download(self, filename: str, subfolder: str = "", folder_type: str = "output",
                 dest_dir: Path | str = ".") -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(filename).name
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        with self.session.get(self._url("/view"), params=params, stream=True, timeout=max(self.timeout, 300)) as resp:
            resp.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
            tmp.replace(dest)
        return dest

    # ------------------------------------------------------------- WebSocket

    def connect(self) -> None:
        """Open the WebSocket. Call before queue_prompt so no events are missed."""
        if self._ws is None:
            self._ws = websocket.create_connection(self.ws_url, timeout=self.timeout,
                                                  header=[f"{k}: {v}" for k, v in self.session.headers.items()
                                                          if k.lower() in ("authorization", "cookie")])

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def __enter__(self) -> "ComfyClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def track_execution(self, prompt_id: str, callback: ProgressCallback | None = None,
                        poll_interval: float = 5.0, timeout: float | None = None) -> dict:
        """Block until ``prompt_id`` finishes, reporting progress events to ``callback``.

        Returns the /history entry. Raises ComfyExecutionError / ComfyInterrupted on failure.
        If the job finished before the socket connected, the history poll catches it.
        """
        self.connect()
        assert self._ws is not None
        self._ws.settimeout(poll_interval)
        deadline = time.monotonic() + timeout if timeout else None
        current_node: str | None = None

        while True:
            if deadline and time.monotonic() > deadline:
                raise ComfyError(f"timed out waiting for prompt {prompt_id}")
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                entry = self.get_history(prompt_id)
                if entry and entry.get("status", {}).get("completed") is not None:
                    return self._finish_from_history(prompt_id, entry)
                continue
            except websocket.WebSocketConnectionClosedException:
                # Proxies (RunPod) drop idle sockets; reconnect and keep going.
                self._ws = None
                self.connect()
                self._ws.settimeout(poll_interval)
                continue

            if not isinstance(raw, str):
                continue  # binary preview frames
            msg = json.loads(raw)
            msg_type, data = msg.get("type"), msg.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue

            if msg_type == "executing":
                current_node = data.get("node")
                if current_node is None and data.get("prompt_id") == prompt_id:
                    return self._finish_from_history(prompt_id, self.get_history(prompt_id))
            elif msg_type == "progress":
                if callback:
                    callback(Progress(prompt_id, data.get("node") or current_node,
                                      int(data.get("value", 0)), int(data.get("max", 0))))
            elif msg_type == "execution_error":
                raise ComfyExecutionError(data)
            elif msg_type == "execution_interrupted":
                raise ComfyInterrupted(f"prompt {prompt_id} interrupted at node {data.get('node_id')}")
            elif msg_type == "execution_success":
                return self._finish_from_history(prompt_id, self.get_history(prompt_id))

    def _finish_from_history(self, prompt_id: str, entry: dict | None) -> dict:
        # History can lag the final WS event by a moment.
        for _ in range(10):
            if entry:
                break
            time.sleep(0.5)
            entry = self.get_history(prompt_id)
        if not entry:
            raise ComfyError(f"prompt {prompt_id} finished but has no history entry")
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            for name, data in status.get("messages", []):
                if name == "execution_error":
                    raise ComfyExecutionError(data)
                if name == "execution_interrupted":
                    raise ComfyInterrupted(f"prompt {prompt_id} interrupted")
            raise ComfyError(f"prompt {prompt_id} failed: {status}")
        return entry

    # --------------------------------------------------------------- outputs

    @staticmethod
    def iter_output_refs(entry: dict) -> Iterable[dict]:
        """Yield {filename, subfolder, type} for every file a prompt produced.

        Covers standard UI outputs and string paths shown via PreviewAny / ShowText,
        which is how 3D nodes that only return a path string surface their .glb.
        """
        seen = set()
        for node_out in (entry.get("outputs") or {}).values():
            for key in FILE_OUTPUT_KEYS:
                for item in node_out.get(key, []) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        ref = {"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                               "type": item.get("type", "output")}
                        if item.get("type") == "temp" and key == "images":
                            continue  # previews
                        k = (ref["filename"], ref["subfolder"], ref["type"])
                        if k not in seen:
                            seen.add(k)
                            yield ref
            for text in node_out.get("text", []) or []:
                ref = _ref_from_path_string(text)
                if ref:
                    k = (ref["filename"], ref["subfolder"], ref["type"])
                    if k not in seen:
                        seen.add(k)
                        yield ref

    def get_output_files(self, prompt_id: str, dest_dir: Path | str = "output",
                         suffixes: Iterable[str] | None = None) -> list[Path]:
        """Download every output file of ``prompt_id`` into ``dest_dir``."""
        entry = self.get_history(prompt_id)
        if not entry:
            raise ComfyError(f"no history for prompt {prompt_id}")
        wanted = tuple(s.lower() for s in suffixes) if suffixes else None
        paths = []
        for ref in self.iter_output_refs(entry):
            if wanted and not ref["filename"].lower().endswith(wanted):
                continue
            paths.append(self.download(ref["filename"], ref["subfolder"], ref["type"], dest_dir))
        return paths

    def run(self, workflow: dict, callback: ProgressCallback | None = None,
            timeout: float | None = None) -> tuple[str, dict]:
        """Connect, queue, and wait. Returns (prompt_id, history entry)."""
        self.connect()
        prompt_id = self.queue_prompt(workflow)
        return prompt_id, self.track_execution(prompt_id, callback=callback, timeout=timeout)


def _ref_from_path_string(text: Any) -> dict | None:
    if not isinstance(text, str):
        return None
    text = text.strip().strip('"')
    if "\n" in text or not text.lower().endswith(FILE_SUFFIXES):
        return None
    path = text.replace("\\", "/")
    # Absolute server paths: keep the part under ComfyUI's output/ directory.
    if "/output/" in path:
        path = path.rsplit("/output/", 1)[1]
    elif path.startswith("/"):
        return None
    subfolder, _, filename = path.rpartition("/")
    return {"filename": filename, "subfolder": subfolder, "type": "output"}


def print_progress(progress: Progress) -> None:
    """Default single-line progress reporter for the CLIs."""
    width = 30
    filled = int(width * progress.fraction)
    bar = "#" * filled + "-" * (width - filled)
    end = "\n" if progress.value >= progress.max else ""
    print(f"\r  [{bar}] {progress.value}/{progress.max}  node {progress.node}", end=end, flush=True)

"""Environment, device (CUDA/MPS) and dependency validation.

Run directly to print a report and exit non-zero on hard failures:

    python -m aether_engine.env_check            # client-side checks
    python -m aether_engine.env_check --gpu-box  # also require torch/onnxruntime (RunPod)
"""

from __future__ import annotations

import argparse
import importlib
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

REQUIRED_NUMPY_SERIES = "1.26."

# Packages that are compiled against the NumPy 1.x C-API on the GPU box.
NUMPY_ABI_SENSITIVE = ("torch", "onnxruntime", "insightface", "cv2")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fatal: bool = True
    missing: bool = False


@dataclass
class EnvReport:
    results: list[CheckResult] = field(default_factory=list)
    device: str = "cpu"

    @property
    def ok(self) -> bool:
        return all(r.ok or not r.fatal for r in self.results)

    def add(self, *args, **kwargs) -> CheckResult:
        result = CheckResult(*args, **kwargs)
        self.results.append(result)
        return result

    def format(self) -> str:
        lines = [f"Device: {self.device}"]
        for r in self.results:
            mark = "OK  " if r.ok else ("FAIL" if r.fatal else "WARN")
            lines.append(f"[{mark}] {r.name}: {r.detail}")
        return "\n".join(lines)


def check_numpy() -> CheckResult:
    try:
        import numpy
    except ImportError:
        return CheckResult("numpy", False, "not installed (need numpy>=1.26.0,<2.0.0)")
    version = numpy.__version__
    if version.startswith(REQUIRED_NUMPY_SERIES):
        return CheckResult("numpy", True, version)
    return CheckResult(
        "numpy",
        False,
        f"{version} installed but {REQUIRED_NUMPY_SERIES}x is required. torch/onnxruntime/insightface "
        f"are built against the NumPy 1.x C-API. Fix: pip install 'numpy>=1.26.0,<2.0.0'",
    )


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def detect_hardware_provider() -> str:
    """Return "cuda", "mps" or "cpu" for the current machine.

    Uses torch when it is importable; otherwise falls back to platform hints so the
    client-only install on the Mac (no torch) still reports correctly.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"
    except ImportError:
        pass
    if is_apple_silicon():
        return "mps"
    if shutil.which("nvidia-smi"):
        try:
            subprocess.run(["nvidia-smi", "-L"], check=True, capture_output=True, timeout=10)
            return "cuda"
        except (subprocess.SubprocessError, OSError):
            pass
    return "cpu"


def get_torch_device():
    """Resolve a torch.device for this machine: cuda → mps → cpu.

    Code that passes CUDA-specific arguments (e.g. ``device="cuda"``) should call this
    instead so it degrades to MPS on Apple Silicon.
    """
    import torch

    return torch.device(detect_hardware_provider())


def check_import(module: str, fatal: bool) -> CheckResult:
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name == module:
            return CheckResult(module, False, "not installed", fatal=fatal, missing=True)
        return CheckResult(module, False, str(exc), fatal=fatal)
    except ImportError as exc:
        detail = str(exc)
        if "_ARRAY_API" in detail or "numpy.core.multiarray" in detail:
            detail = f"NumPy ABI mismatch ({detail}); reinstall numpy<2"
        return CheckResult(module, False, detail, fatal=fatal)
    except Exception as exc:  # compiled extensions can raise anything on a bad ABI
        return CheckResult(module, False, f"{type(exc).__name__}: {exc}", fatal=fatal)
    return CheckResult(module, True, getattr(mod, "__version__", "imported"), fatal=fatal)


def run_checks(gpu_box: bool = False) -> EnvReport:
    report = EnvReport()
    report.results.append(check_numpy())
    report.device = detect_hardware_provider()

    for module in NUMPY_ABI_SENSITIVE:
        # On the Mac client these are optional; on the GPU box torch and onnxruntime must load.
        fatal = gpu_box and module in ("torch", "onnxruntime")
        result = check_import(module, fatal=fatal)
        # A missing optional package on the Mac client is fine; a broken one is not.
        if gpu_box or not result.missing:
            report.results.append(result)

    if gpu_box and report.device != "cuda":
        report.add("cuda", False, f"expected a CUDA device on the GPU box, found {report.device}")

    if gpu_box:
        try:
            import onnxruntime

            providers = onnxruntime.get_available_providers()
            report.add(
                "onnxruntime providers",
                "CUDAExecutionProvider" in providers,
                ", ".join(providers),
                fatal=False,
            )
        except Exception:
            pass
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpu-box", action="store_true", help="require torch/onnxruntime and a CUDA device")
    args = parser.parse_args(argv)

    report = run_checks(gpu_box=args.gpu_box)
    print(report.format())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

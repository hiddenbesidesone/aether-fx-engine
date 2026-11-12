#!/usr/bin/env python3
"""Smoke-test the TRELLIS GPU stack on this pod and pick backends that actually run.

    /workspace/ComfyUI/venv/bin/python scripts/runpod/check_trellis.py [--write-env FILE]

Each compiled dependency is imported *and* run on a tiny CUDA input, because a wheel that
imports fine can still lack kernels for this GPU ("no kernel image is available").
TRELLIS reads its attention backend and spconv algorithm once, when ComfyUI starts, so the
working choices are written to --write-env as `export` lines for scripts/runpod/start_comfy.sh.
Exit code 0 means TRELLIS can run here.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from pathlib import Path

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> bool:
    try:
        detail = fn() or ""
        RESULTS.append((name, True, detail))
        return True
    except Exception as exc:  # report every failure, keep going
        last = traceback.format_exception_only(type(exc), exc)[-1].strip()
        RESULTS.append((name, False, last[:200]))
        return False


def torch_cuda():
    import torch
    assert torch.cuda.is_available(), "torch.cuda.is_available() is False"
    cap = torch.cuda.get_device_capability(0)
    return f"torch {torch.__version__}, {torch.cuda.get_device_name(0)} (sm_{cap[0]}{cap[1]})"


def flash_attn():
    import torch
    from flash_attn import flash_attn_func
    q = torch.randn(1, 64, 4, 64, device="cuda", dtype=torch.float16)
    out = flash_attn_func(q, q, q)
    torch.cuda.synchronize()
    assert out.shape == q.shape
    import flash_attn as fa
    return fa.__version__


def xformers():
    import torch
    import xformers
    import xformers.ops as xops
    q = torch.randn(1, 64, 4, 64, device="cuda", dtype=torch.float16)
    out = xops.memory_efficient_attention(q, q, q)
    torch.cuda.synchronize()
    assert out.shape == q.shape
    return xformers.__version__


def spconv_algo(algo_name: str):
    def run():
        import torch
        import spconv.pytorch as spconv
        algo = getattr(spconv.ConvAlgo, {"native": "Native", "implicit_gemm": "MaskImplicitGemm"}[algo_name])
        coords = torch.tensor([[0, 1, 1, 1], [0, 1, 2, 1], [0, 2, 2, 2]], dtype=torch.int32, device="cuda")
        feats = torch.randn(3, 8, device="cuda", dtype=torch.float16)
        x = spconv.SparseConvTensor(feats, coords, [4, 4, 4], 1)
        conv = spconv.SubMConv3d(8, 8, 3, algo=algo).cuda().half()
        out = conv(x)
        torch.cuda.synchronize()
        assert out.features.shape == (3, 8)
        import spconv as sp
        return sp.__version__
    return run


def nvdiffrast():
    import torch
    import nvdiffrast.torch as dr
    ctx = dr.RasterizeCudaContext()
    pos = torch.tensor([[[-0.8, -0.8, 0, 1], [0.8, -0.8, 0, 1], [0, 0.8, 0, 1]]], device="cuda")
    tri = torch.tensor([[0, 1, 2]], dtype=torch.int32, device="cuda")
    rast, _ = dr.rasterize(ctx, pos, tri, resolution=[32, 32])
    torch.cuda.synchronize()
    assert rast[..., 3].max() > 0, "rasterized nothing"
    return getattr(sys.modules["nvdiffrast"], "__version__", "")


def gaussian_rasterizer():
    import torch
    from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer
    eye = torch.eye(4, device="cuda")
    settings = GaussianRasterizationSettings(
        image_height=32, image_width=32, tanfovx=0.5, tanfovy=0.5, kernel_size=0.1, subpixel_offset=torch.zeros(
            (32, 32, 2), device="cuda"), bg=torch.zeros(3, device="cuda"), scale_modifier=1.0, viewmatrix=eye,
        projmatrix=eye, sh_degree=0, campos=torch.zeros(3, device="cuda"), prefiltered=False, debug=False)
    n = 4
    means = torch.tensor([[0, 0, 2.0]] * n, device="cuda") + torch.randn(n, 3, device="cuda") * 0.05
    color, _ = GaussianRasterizer(settings)(
        means3D=means, means2D=torch.zeros_like(means), shs=None, colors_precomp=torch.ones(n, 3, device="cuda"),
        opacities=torch.ones(n, 1, device="cuda"), scales=torch.full((n, 3), 0.1, device="cuda"),
        rotations=torch.tensor([[1.0, 0, 0, 0]] * n, device="cuda"), cov3D_precomp=None)
    torch.cuda.synchronize()
    assert color.shape == (3, 32, 32)


def imports(*names: str):
    def run():
        for name in names:
            importlib.import_module(name)
    return run


def kaolin_or_patch(comfy_dir: Path):
    def run():
        try:
            import kaolin
            return f"kaolin {kaolin.__version__}"
        except ImportError:
            flexi = comfy_dir / "custom_nodes/ComfyUI-IF_Trellis/trellis/representations/mesh/flexicube.py"
            if "patched by aether" in flexi.read_text():
                return "kaolin not installed; flexicube.py patched to work without it"
            raise
    return run


def onnxruntime_gpu():
    from importlib.metadata import PackageNotFoundError, version
    try:
        cpu = version("onnxruntime")
        raise RuntimeError(f"CPU onnxruntime {cpu} is installed and shadows onnxruntime-gpu "
                           f"(run repair_onnxruntime from scripts/runpod/env.sh)")
    except PackageNotFoundError:
        pass
    import onnxruntime as ort
    providers = ort.get_available_providers()
    assert "CUDAExecutionProvider" in providers, f"providers: {providers}"
    return ort.__version__


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comfy-dir", type=Path, default=Path("/workspace/ComfyUI"))
    p.add_argument("--write-env", type=Path, help="write SPARSE_ATTN_BACKEND / SPCONV_ALGO exports here")
    args = p.parse_args()

    if not check("torch + CUDA", torch_cuda):
        report()
        return 1
    fa = check("flash-attn (run)", flash_attn)
    xf = check("xformers (run)", xformers)
    implicit = check("spconv implicit_gemm (run)", spconv_algo("implicit_gemm"))
    native = check("spconv native (run)", spconv_algo("native"))
    check("nvdiffrast (rasterize)", nvdiffrast)
    check("diff-gaussian-rasterization (render)", gaussian_rasterizer)
    check("kaolin / flexicube", kaolin_or_patch(args.comfy_dir))
    check("mesh/postprocess libs", imports("utils3d", "xatlas", "pyvista", "pymeshfix", "igraph", "trimesh",
                                           "plyfile", "easydict", "rembg"))
    check("onnxruntime-gpu (LivePortrait)", onnxruntime_gpu)

    attn = "flash_attn" if fa else "xformers" if xf else None
    algo = "implicit_gemm" if implicit else "native" if native else None
    report()

    blockers = [name for name, ok, _ in RESULTS if not ok and not name.startswith(
        ("flash-attn", "xformers", "spconv", "onnxruntime"))]
    if attn is None:
        blockers.append("no working attention backend (TRELLIS sparse attention needs flash-attn or xformers)")
    if algo is None:
        blockers.append("spconv runs with neither algorithm")

    if attn and algo:
        print(f"\nUse: SPARSE_ATTN_BACKEND={attn}  SPCONV_ALGO={algo}")
        if args.write_env:
            args.write_env.parent.mkdir(parents=True, exist_ok=True)
            args.write_env.write_text(
                "# written by scripts/runpod/check_trellis.py -- read by start_comfy.sh before ComfyUI starts\n"
                f"export SPARSE_ATTN_BACKEND={attn}\nexport ATTN_BACKEND={attn}\nexport SPCONV_ALGO={algo}\n")
            print(f"     saved to {args.write_env}")
    if blockers:
        print("\nTRELLIS will NOT run on this pod yet:")
        for b in blockers:
            print(f"  - {b}")
        return 1
    print("\nTRELLIS stack OK. Restart ComfyUI with scripts/runpod/start_comfy.sh so it picks these up.")
    return 0


def report() -> None:
    width = max(len(name) for name, _, _ in RESULTS)
    print()
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")


if __name__ == "__main__":
    sys.exit(main())

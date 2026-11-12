#!/usr/bin/env bash
# Install ComfyUI-IF_Trellis (image -> 3D mesh + Gaussian splat) on a RunPod ComfyUI box
# without touching the torch / onnxruntime-gpu stack that LivePortrait depends on.
#
#   bash scripts/runpod/install_trellis.sh
#
# Do NOT `pip install -r` the node's own requirements.txt: it is written for torch 2.5 / CUDA 12.4,
# installs CPU onnxruntime (LivePortrait's 70-minute CPU fallback) and an unpinned xformers that
# can replace torch. This script installs the same libraries, matched to the torch already here.
#
# Needs nvcc (CUDA toolkit) to compile nvdiffrast and diff-gaussian-rasterization; RunPod
# "devel" PyTorch images ship it. Ends by running check_trellis.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"

BUILD_DIR="/workspace/build"
mkdir -p "$BUILD_DIR"

read -r TORCH_VER CUDA_TAG PY_TAG CXX_ABI GPU_SM <<<"$(torch_info)"
TORCH_MM="${TORCH_VER%.*}"
echo "[*] torch $TORCH_VER  cuda $CUDA_TAG  python $PY_TAG  cxx11abi $CXX_ABI  gpu sm_$GPU_SM"
if [ "$GPU_SM" = "none" ]; then
    echo "error: torch can't see a GPU. TRELLIS needs CUDA." >&2; exit 1
fi
case "$CUDA_TAG" in
    12[6-9]|12[0-9][0-9]) SPCONV="spconv-cu126" ;;
    124|125)              SPCONV="spconv-cu124" ;;
    121|122|123)          SPCONV="spconv-cu121" ;;
    *) echo "error: torch is built for CUDA '$CUDA_TAG'; this script handles CUDA 12.x" >&2; exit 1 ;;
esac

if ! command -v nvcc >/dev/null; then
    echo "error: nvcc not found. nvdiffrast and diff-gaussian-rasterization must be compiled." >&2
    echo "       Use a RunPod PyTorch *devel* template, or install the CUDA toolkit matching CUDA $CUDA_TAG." >&2
    exit 1
fi
echo "[*] $(nvcc --version | tail -1)"
export TORCH_CUDA_ARCH_LIST="$GPU_SM"   # compile only for this GPU (much faster)
export MAX_JOBS="${MAX_JOBS:-8}"

echo "=== 1/7 node source ==="
DEST="$COMFY_DIR/custom_nodes/ComfyUI-IF_Trellis"
if [ -d "$DEST/.git" ]; then
    git -C "$DEST" pull --ff-only || true
    git -C "$DEST" submodule update --init --recursive
else
    git clone --recurse-submodules https://github.com/if-ai/ComfyUI-IF_Trellis.git "$DEST"
fi

echo "=== 2/7 pure-Python dependencies ==="
safe_pip pillow imageio imageio-ffmpeg tqdm easydict opencv-python-headless scipy trimesh xatlas \
    pyvista pymeshfix igraph plyfile ninja huggingface_hub transformers "rembg==2.0.60" \
    "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

echo "=== 3/7 sparse conv: $SPCONV ==="
safe_pip "$SPCONV"

echo "=== 4/7 attention backends ==="
FA_WHEEL="flash_attn-2.8.3.post2+cu12torch${TORCH_MM}cxx11abi${CXX_ABI}-${PY_TAG}-${PY_TAG}-linux_x86_64.whl"
FA_URL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post2/${FA_WHEEL}"
if [ -n "$(pkg_version flash-attn)" ]; then
    echo "[*] flash-attn $(pkg_version flash-attn) already installed"
elif safe_pip --no-deps "$FA_URL"; then
    echo "[✓] flash-attn prebuilt wheel"
else
    echo "[!] no prebuilt flash-attn wheel for torch $TORCH_MM / $PY_TAG; continuing with xformers only"
fi
if [ -z "$(pkg_version xformers)" ]; then
    # pytorch.org's index has the xformers build that matches this torch; the pins stop it swapping torch.
    safe_pip xformers --index-url "https://download.pytorch.org/whl/cu$CUDA_TAG" \
        || echo "[!] xformers install failed; continuing"
fi

echo "=== 5/7 kaolin (FlexiCubes mesh extraction) ==="
KAOLIN_INDEX="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-${TORCH_VER}_cu${CUDA_TAG}.html"
if [ -n "$(pkg_version kaolin)" ] || safe_pip kaolin -f "$KAOLIN_INDEX"; then
    echo "[✓] kaolin $(pkg_version kaolin)"
else
    # TRELLIS only imports kaolin.utils.testing.check_tensor (a shape assertion). Inline a stand-in.
    FLEXI="$DEST/trellis/representations/mesh/flexicube.py"
    if grep -q '^from kaolin.utils.testing import check_tensor' "$FLEXI"; then
        echo "[!] no kaolin wheel at $KAOLIN_INDEX; patching flexicube.py to not need it"
        "$PY" - "$FLEXI" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text().replace(
    "from kaolin.utils.testing import check_tensor\n",
    "try:\n    from kaolin.utils.testing import check_tensor\n"
    "except ImportError:  # patched by aether install_trellis.sh\n"
    "    def check_tensor(tensor, shape=None, dtype=None, device=None, throw=True):\n"
    "        if shape is not None and (tensor.dim() != len(shape) or any(\n"
    "                s is not None and s != t for s, t in zip(shape, tensor.shape))):\n"
    "            if throw:\n"
    "                raise ValueError(f'tensor shape {tuple(tensor.shape)} != {shape}')\n"
    "            return False\n"
    "        return True\n", 1))
EOF
    fi
fi

echo "=== 6/7 nvdiffrast (compiles, a few minutes) ==="
if [ -z "$(pkg_version nvdiffrast)" ]; then
    safe_pip --no-build-isolation "git+https://github.com/NVlabs/nvdiffrast.git"
fi

echo "=== 7/7 diff-gaussian-rasterization (compiles, a few minutes) ==="
if [ -z "$(pkg_version diff_gaussian_rasterization)" ]; then
    MIP="$BUILD_DIR/mip-splatting"
    [ -d "$MIP" ] || git clone --recurse-submodules https://github.com/autonomousvision/mip-splatting.git "$MIP"
    DGR="$MIP/submodules/diff-gaussian-rasterization"
    git -C "$MIP" submodule update --init --recursive
    # Newer GCC no longer pulls in <cstdint> transitively; the rasterizer uses uint32_t.
    HDR="$DGR/cuda_rasterizer/rasterizer_impl.h"
    grep -q '<cstdint>' "$HDR" || sed -i '1i #include <cstdint>' "$HDR"
    safe_pip --no-build-isolation "$DGR"
fi

repair_onnxruntime
echo
echo "=== checking the install on this GPU ==="
"$PY" "$HERE/check_trellis.py" --comfy-dir "$COMFY_DIR" --write-env "$STATE_DIR/trellis_env.sh"

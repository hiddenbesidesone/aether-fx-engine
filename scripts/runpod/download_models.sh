#!/usr/bin/env bash
# Download model weights into ComfyUI/models on the persistent volume. Skips files already there.
#
#   bash scripts/runpod/download_models.sh stable-audio   # needs HF_TOKEN + license accepted (see below)
#   bash scripts/runpod/download_models.sh mmaudio        # Foley from video (~5 GB, public)
#   bash scripts/runpod/download_models.sh yvann          # Yvann audio-reactive Text-to-Video example (~5 GB)
#
# Models that download themselves on first use (into /workspace, see env.sh):
#   TRELLIS-image-large -> models/checkpoints/   DINOv2 -> $TORCH_HOME   BiRefNet -> models/RMBG/
#   MusicGen            -> models/musicgen/      Demucs -> $TORCH_HOME   BigVGAN  -> models/mmaudio/nvidia/
#
# Stable Audio Open is gated: open https://huggingface.co/stabilityai/stable-audio-open-1.0 while
# logged in, accept the license, create a read token at https://huggingface.co/settings/tokens, then
#   export HF_TOKEN=hf_xxx
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"
M="$COMFY_DIR/models"

fetch() {  # fetch <repo> <file in repo> <destination path>
    local repo="$1" file="$2" dest="$3"
    if [ -s "$dest" ]; then echo "[=] $(basename "$dest") already present"; return 0; fi
    mkdir -p "$(dirname "$dest")"
    echo "[*] $repo/$file -> $dest"
    "$PY" - "$repo" "$file" "$dest" <<'EOF'
import os, shutil, sys
from huggingface_hub import hf_hub_download
repo, file, dest = sys.argv[1:]
staging = os.path.join(os.path.dirname(dest), ".download")  # same volume: the final move is a rename
path = hf_hub_download(repo, file, local_dir=staging, token=os.environ.get("HF_TOKEN") or None)
os.replace(path, dest)
shutil.rmtree(staging, ignore_errors=True)
EOF
}

case "${1:-}" in
stable-audio)
    if [ -z "${HF_TOKEN:-}" ]; then
        echo "error: Stable Audio Open is gated. Accept the license on its Hugging Face page, then export HF_TOKEN=hf_..." >&2
        exit 1
    fi
    fetch stabilityai/stable-audio-open-1.0 model.safetensors "$M/checkpoints/stable-audio-open-1.0.safetensors"
    fetch google-t5/t5-base model.safetensors "$M/text_encoders/t5-base.safetensors"
    ;;
mmaudio)
    for f in mmaudio_large_44k_v2_fp16.safetensors mmaudio_vae_44k_fp16.safetensors \
             mmaudio_synchformer_fp16.safetensors apple_DFN5B-CLIP-ViT-H-14-384_fp16.safetensors; do
        fetch Kijai/MMAudio_safetensors "$f" "$M/mmaudio/$f"
    done
    ;;
yvann)
    # What the Yvann AudioReactive_TextToVideo example workflow loads, under the names it expects (~5 GB).
    # Its 2x-sudo-UltraCompact.pth upscaler isn't on Hugging Face: bypass that node, or add any 2x upscaler.
    fetch Lykon/DreamShaper DreamShaper_8_pruned.safetensors "$M/checkpoints/dreamshaper_8.safetensors"
    fetch stabilityai/sd-vae-ft-mse-original vae-ft-mse-840000-ema-pruned.safetensors \
        "$M/vae/vae-ft-mse-840000-ema-pruned.safetensors"
    fetch wangfuyun/AnimateLCM AnimateLCM_sd15_t2v.ckpt "$M/animatediff_models/AnimateLCM_sd15_t2v.ckpt"
    fetch wangfuyun/AnimateLCM AnimateLCM_sd15_t2v_lora.safetensors "$M/loras/AnimateLCM_sd15_t2v_lora.safetensors"
    fetch guoyww/animatediff v3_sd15_adapter.ckpt "$M/loras/v3_sd15_adapter.ckpt"
    fetch ByteDance/Hyper-SD Hyper-SD15-12steps-CFG-lora.safetensors "$M/loras/Hyper-SD15-12steps-CFG-lora.safetensors"
    ;;
*)
    echo "usage: download_models.sh stable-audio|mmaudio|yvann" >&2; exit 2 ;;
esac
echo "[✓] done"

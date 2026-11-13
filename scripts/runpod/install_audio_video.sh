#!/usr/bin/env bash
# Install the audio + audio/video node packs on a RunPod ComfyUI box, through
# safe_node_install.sh so none of them can replace torch or onnxruntime-gpu.
#
#   bash scripts/runpod/install_audio_video.sh audio      # MusicGen, Demucs stems (Stable Audio is built in)
#   bash scripts/runpod/install_audio_video.sh video      # VideoHelperSuite, MMAudio (Foley), Yvann audio-reactive
#   bash scripts/runpod/install_audio_video.sh yvann-deps # extra packs the Yvann example workflows use
#   bash scripts/runpod/install_audio_video.sh previz     # Blender previz -> AnimateDiff video (render_blender_video.py)
#   bash scripts/runpod/install_audio_video.sh all
#
# Then: bash scripts/runpod/download_models.sh ...   and   bash scripts/runpod/start_comfy.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"

GROUP="${1:-all}"
node() { bash "$HERE/safe_node_install.sh" "$1" "$2"; }

if ! command -v ffmpeg >/dev/null; then
    echo "[*] installing ffmpeg"
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi
echo "[✓] $(ffmpeg -version | head -1)"
ensure_torchaudio

case "$GROUP" in audio|all)
    node audio-separation-nodes-comfyui https://github.com/christian-byrne/audio-separation-nodes-comfyui.git
    node ComfyUI-MusicGen-HF            https://github.com/ebrinz/ComfyUI-MusicGen-HF.git
    mkdir -p "$COMFY_DIR/models/checkpoints" "$COMFY_DIR/models/text_encoders" "$COMFY_DIR/models/musicgen"
;; esac

case "$GROUP" in video|all)
    node ComfyUI-VideoHelperSuite https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
    node ComfyUI-MMAudio          https://github.com/kijai/ComfyUI-MMAudio.git
    node ComfyUI_Yvann-Nodes      https://github.com/yvann-ba/ComfyUI_Yvann-Nodes.git
    mkdir -p "$COMFY_DIR/models/mmaudio"
;; esac

case "$GROUP" in yvann-deps|all)
    node ComfyUI-KJNodes              https://github.com/kijai/ComfyUI-KJNodes.git
    node ComfyUI-AnimateDiff-Evolved  https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git
    node ComfyUI-Advanced-ControlNet  https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet.git
    node ComfyUI_IPAdapter_plus       https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
    node ComfyUI_FizzNodes            https://github.com/FizzleDorf/ComfyUI_FizzNodes.git
    mkdir -p "$COMFY_DIR/models/animatediff_models" "$COMFY_DIR/models/upscale_models" \
             "$COMFY_DIR/models/controlnet" "$COMFY_DIR/models/vae" "$COMFY_DIR/models/loras"
;; esac

case "$GROUP" in previz|all)
    # ControlNet loading/apply and Canny are built into ComfyUI; controlnet_aux adds Depth Anything V2
    # for --clay renders (its checkpoint downloads itself into custom_nodes/comfyui_controlnet_aux/ckpts).
    node ComfyUI-VideoHelperSuite     https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
    node ComfyUI-AnimateDiff-Evolved  https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git
    node comfyui_controlnet_aux       https://github.com/Fannovel16/comfyui_controlnet_aux.git
    mkdir -p "$COMFY_DIR/models/animatediff_models" "$COMFY_DIR/models/controlnet" "$COMFY_DIR/models/checkpoints"
;; esac

case "$GROUP" in audio|video|yvann-deps|previz|all) ;; *)
    echo "usage: install_audio_video.sh audio|video|yvann-deps|previz|all" >&2; exit 2 ;;
esac

repair_onnxruntime
echo
echo "[✓] done. Next: download models (scripts/runpod/download_models.sh) and restart ComfyUI (scripts/runpod/start_comfy.sh)."

# Video ↔ audio: Foley from video (MMAudio) + audio-reactive animation (Yvann) on RunPod — guide for Gemini

> **How to use this file:** paste the whole thing into Gemini and say *"Walk me through this one step at a
> time. I'll paste the terminal output after each step."* Gemini: please follow the steps in order, give me
> one step at a time, and wait for my output before moving on.

---

## Context for Gemini (read first)

I'm running ComfyUI on a **RunPod GPU pod** and working in the **JupyterLab terminal**. My repo,
`aether-fx-engine`, adds two video+audio tools:

| Tool | What it does | How to run it |
|---|---|---|
| **Foley / ambience from video**: `ComfyUI-MMAudio` (kijai) | Watches a clip and generates synced sound effects and ambience, then muxes them into the MP4 | CLI: `scripts/add_foley.py` |
| **Audio-reactive animation**: `ComfyUI_Yvann-Nodes` | Analyses a track (beats, stems) and drives AnimateDiff, IP-Adapter and ControlNet with it | The pack's own example workflows, in the **ComfyUI web UI** |
| **VideoHelperSuite** (VHS) | Video load/save and audio muxing; both tools use it | (support pack) |

**Status:** the Foley CLI is built and tested against a fake server only, so **this is its first real run**.
The audio-reactive part ships no CLI. Its example graphs need several model files, so we start from the
author's tested workflows in the UI.

What's already on the pod and working: ComfyUI plus a **LivePortrait** workflow. LivePortrait depends on
`onnxruntime-gpu==1.26.0` (CUDA 12) and torch 2.8 / CUDA 12.8. **Don't break that.** VideoHelperSuite may
already be installed for LivePortrait. Re-running the installer just pulls the latest version, which is fine.

### Rules for this install (important)

1. Install node packs **only** with `scripts/runpod/install_audio_video.sh` (it calls
   `safe_node_install.sh`). It drops torch, torchaudio and onnxruntime lines from each pack's requirements
   and pins the versions that are installed now, so MMAudio's dependencies can't swap in a different torch.
2. Don't `pip install` torch, torchaudio, xformers or onnxruntime by hand.
3. ComfyUI's Python is `/workspace/ComfyUI/venv/bin/python`. `/root` is wiped when the pod restarts; the
   scripts keep caches on `/workspace`.

---

## Step 1 — Check the pod and update the repo

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv
/workspace/ComfyUI/venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
cd /workspace
[ -d aether-fx-engine ] || git clone https://github.com/hiddenbesidesone/aether-fx-engine.git
cd /workspace/aether-fx-engine && git fetch origin && git checkout feature/multi-workflow-engine && git pull
```

## Step 2 — Install the node packs

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/install_audio_video.sh video 2>&1 | tee /workspace/install_video.log
```

This installs `ffmpeg` if it's missing and matches `torchaudio` to torch. Then it installs
**ComfyUI-VideoHelperSuite**, **ComfyUI-MMAudio** and **ComfyUI_Yvann-Nodes**, and creates
`models/mmaudio`.

For the audio-reactive example workflows, also install the packs they're built on: KJNodes,
AnimateDiff-Evolved, Advanced-ControlNet, IPAdapter_plus and FizzNodes.

```bash
bash scripts/runpod/install_audio_video.sh yvann-deps 2>&1 | tee -a /workspace/install_video.log
```

**Expected ending (each time):** `[✓] onnxruntime-gpu==1.26.0` and `[✓] done.` Paste any `[!]` lines to Gemini.

## Step 3 — Download models

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/download_models.sh mmaudio   # ~5 GB -> models/mmaudio/ (public, no token)
bash scripts/runpod/download_models.sh yvann     # ~5 GB -> checkpoints/, vae/, loras/, animatediff_models/
```

- MMAudio also auto-downloads NVIDIA's BigVGAN vocoder into `models/mmaudio/nvidia/` on first use.
- The `yvann` set covers the **Text-to-Video** example. Its `2x-sudo-UltraCompact.pth` upscaler isn't on
  Hugging Face, so either bypass that node (select it, then Ctrl+B) or pick any 2x upscaler you have in
  `models/upscale_models/`.
- The **Images-to-Video** and **Video-to-Video** examples need more models (QR-code-monster / depth /
  lineart ControlNets, SparseCtrl RGB, IP-Adapter + CLIP vision). Gemini: once Text-to-Video works, help me
  use **ComfyUI-Manager → Model Manager**, or the "missing models" prompt the workflow shows when it loads,
  to fetch those.

## Step 4 — Restart ComfyUI

```bash
bash /workspace/aether-fx-engine/scripts/runpod/start_comfy.sh
```

**Expected:** `[✓] ComfyUI is up on :8188`. If it prints `some custom nodes failed to import`, run
`grep -B2 -A20 -i "MMAudio\|Yvann\|VideoHelper" /workspace/comfyui.log | head -80` and paste the output.

---

## Part A — Foley from video (CLI)

### Step A1 — Client CLI (one time; skip if already done for another guide)

```bash
python3 -m venv /workspace/aether-venv          # use python3.12 if python3 is 3.13+
/workspace/aether-venv/bin/pip install -q -e /workspace/aether-fx-engine
mkdir -p /workspace/aether-fx-engine/inputs /workspace/exports
```

### Step A2 — Run it

Upload a clip (`.mp4`/`.mov`/`.webm`/`.mkv`) to `/workspace/aether-fx-engine/inputs/` with the JupyterLab
file browser. Then run:

```bash
cd /workspace/aether-fx-engine
/workspace/aether-venv/bin/python scripts/add_foley.py --video inputs/shot_01.mp4 \
    --prompt "plastic toy footsteps on a glossy floor, water splash" \
    --output /workspace/exports/video/shot_01_foley.mp4
```

**Expected:** `[✓] video /workspace/exports/video/shot_01_foley.mp4` and
`[✓] audio /workspace/exports/video/shot_01_foley.flac`.

Things to know:

- **Keep clips short.** MMAudio is trained on 8-second clips. Up to about 12 s is fine; for longer edits,
  run it once per shot. `--duration` defaults to the clip's length (read with `ffprobe`).
- `--prompt` is optional; MMAudio also "watches" the picture. Use `--negative` to avoid things (the default
  avoids music and speech).
- The output MP4 keeps the clip's original frame rate. Internally, MMAudio watches a 25 fps, 384 px copy,
  because its sync model expects 25 fps.
- `--seed N` makes a run repeatable; `--steps 25`, `--cfg 4.5`.

| Symptom | Likely cause / fix |
|---|---|
| `mmaudio_model='mmaudio_large_44k_v2_fp16.safetensors' not available` | Step 3 isn't done. Run `ls /workspace/ComfyUI/models/mmaudio`. |
| `node class 'MMAudioSampler' is not installed` | Import failure. Check `/workspace/comfyui.log` (Step 4). |
| `node class 'VHS_LoadVideo' is not installed` | VideoHelperSuite failed to import (often `opencv`/`cv2`). Check the log. |
| Error mentioning `bigvgan` / a download | First-run vocoder download failed. Check the pod's internet access and rerun. |
| The audio drifts out of sync | Usually a variable-frame-rate source (phone footage). Re-encode first: `ffmpeg -i in.mp4 -r 25 -c:v libx264 -crf 18 -c:a copy fixed.mp4`. |

---

## Part B — Audio-reactive animation (ComfyUI web UI)

1. Open the ComfyUI UI: RunPod → your pod → **Connect** → HTTP port **8188**.
2. Load an example: **Workflow → Browse Templates**. Find the **ComfyUI_Yvann-Nodes** section (custom-node
   templates are listed by pack name) and open **AudioReactive_TextToVideo_Yvann**. The same files are on
   the pod at `/workspace/ComfyUI/custom_nodes/ComfyUI_Yvann-Nodes/example_workflows/` if you'd rather
   drag one in.
3. If any boxes are red, a node pack or model is missing. Read the names on the red nodes and give them to
   Gemini. Missing node packs can usually be installed with **Manager → Install Missing Custom Nodes**.
   **Afterwards, run `source /workspace/aether-fx-engine/scripts/runpod/env.sh && repair_onnxruntime` in
   the terminal and restart with `start_comfy.sh`**, because Manager installs don't go through our safe
   installer.
4. Load your audio in the audio loader node, set the prompts, and **Queue**. The examples use "Hybrid
   Demucs" to split the track and drive the visuals from the drums or another stem. The result is saved
   by `VHS_VideoCombine` to `/workspace/ComfyUI/output/`.

These workflows use **subgraphs** (grouped nodes). If the UI complains it can't open them, ComfyUI or its
frontend is too old. Gemini: help me update ComfyUI with `cd /workspace/ComfyUI && git pull` and reinstall
its requirements **through the pins**:

```bash
source /workspace/aether-fx-engine/scripts/runpod/env.sh && safe_pip -r /workspace/ComfyUI/requirements.txt
```

then restart with `start_comfy.sh`.

Combining with the music guide: generate a beat with `generate_audio.py --stems`
(`docs/gemini/02_audio_music_and_stems.md`), use the full track as the workflow's audio, and point the
reactive weights at the drums. To add Foley on top of a rendered video, run `add_foley.py` on it.

## Running the Foley CLI from the Mac instead (optional)

```bash
python scripts/add_foley.py --video ./exports/video/shot_01.mp4 --prompt "..." \
    --comfy-url https://<POD_ID>-8188.proxy.runpod.net --output ./exports/video/shot_01_foley.mp4
```

## Notes on how it works (for Gemini)

- Template: `workflows/templates/video_foley_api.json`. It loads the clip twice: once at its own fps for the
  final MP4 (frame rate linked from `VHS_VideoInfo.source_fps`), and once at 25 fps / 384 px for
  `MMAudioSampler`. That node takes the first `duration × 25` frames as its sync stream, whatever the source
  fps is.
- `VHS_VideoCombine` writes `<prefix>_00001.mp4` (silent) and `<prefix>_00001-audio.mp4`, padding the audio
  to the video's length. The CLI keeps the `-audio` file.
- The Yvann example workflows are GPL-3 and live in the node pack; they aren't copied into this repo.

# Blender previz → stylized video (AnimateDiff + ControlNet) on RunPod — guide for Gemini

> **How to use this file:** paste the whole thing into Gemini and say *"Walk me through this one step at a
> time. I'll paste the terminal output after each step."* Gemini: please follow the steps in order, give me
> one step at a time, and wait for my output before moving on.

---

## Context for Gemini (read first)

I'm running ComfyUI on a **RunPod GPU pod** (NVIDIA L40S, 48 GB, torch `2.8.0+cu128`, Python 3.12) and
working in the **JupyterLab terminal**. My repo, `aether-fx-engine` (branch `feature/multi-workflow-engine`),
has a CLI that turns a Blender previz animation into a stylized video:

| Input from Blender | What the server does | CLI |
|---|---|---|
| **Clay / viewport render**: grey solid-shaded animation, as an `.mp4`/`.mov` or a folder of PNG frames | Estimates depth per frame (Depth Anything V2) and finds edges (Canny), then renders with both ControlNets | `scripts/render_blender_video.py --clay …` |
| **Render passes**: a depth (Z) pass, plus an optional normal pass, as frame folders (PNG or EXR) | Uses the exact geometry from the passes as the ControlNet guides | `scripts/render_blender_video.py --depth-frames … [--normal-frames …]` |

Both routes render with **SD1.5 (DreamShaper 8) + AnimateDiff v3** motion, using a 16-frame sliding context
window so long shots stay consistent, and save an H.264 MP4.

Workflow template: `workflows/templates/blender_previz_to_video.json`. The CLI uploads the frames, edits the
template by node title, checks every node and model name against the server before queueing, and downloads
the MP4.

**Status:** built and tested against a fake server only. **This is the first real run.**

What's already on the pod and working: ComfyUI plus **LivePortrait** (needs `onnxruntime-gpu==1.26.0`,
`numpy==1.26.4`), **TRELLIS** (image → 3D, tested), and possibly the audio packs from guide 02.
**Don't break any of that.**

### Rules for this install (important)

1. Install node packs **only** with `scripts/runpod/install_audio_video.sh previz` (it calls
   `safe_node_install.sh`). That drops torch / torchvision / torchaudio / xformers / onnxruntime lines from
   each pack's `requirements.txt` and pins the installed versions plus `numpy<2`.
2. **Never** `pip install` torch, torchvision, torchaudio, xformers, onnxruntime or numpy by hand, and don't
   install these packs from ComfyUI-Manager (Manager installs skip the pins).
3. ComfyUI's Python is `/workspace/ComfyUI/venv/bin/python`. The client CLI uses its own venv,
   `/workspace/aether-venv` (made in an earlier guide).
4. `/root` is wiped when the pod restarts; `/workspace` persists.

---

## Step 1 — Check the pod and update the repo

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv
/workspace/ComfyUI/venv/bin/python -c "import torch, numpy; print(torch.__version__, torch.cuda.is_available(), numpy.__version__)"
df -h /workspace | tail -1
cd /workspace/aether-fx-engine && git fetch origin && git checkout feature/multi-workflow-engine && git pull
git log --oneline -1
```

**Expected:** the L40S, `2.8.0+cu128 True 1.26.4`, at least ~15 GB free, and the latest commit mentions
Blender previz.

## Step 2 — Install the node packs

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/install_audio_video.sh previz 2>&1 | tee /workspace/install_previz.log
```

This installs (or updates) three packs:

- **ComfyUI-VideoHelperSuite**: loads the frame folders and writes the MP4. It may already be installed.
- **ComfyUI-AnimateDiff-Evolved**: the motion model and the sliding context window.
- **comfyui_controlnet_aux**: the Depth Anything V2 preprocessor used by `--clay`.

The ControlNet loader, ControlNet apply and Canny nodes are built into ComfyUI.

**Expected:** each pack ends with `[✓] <name> installed`, and the script ends with
`[✓] onnxruntime-gpu==1.26.0` and `[✓] done`. `comfyui_controlnet_aux` has a long requirements list. If a few
optional extras are listed as failed (for example `mediapipe`), that's fine because Depth Anything doesn't use
them. Gemini: if anything else fails, ask me for `grep -n "failed\|error" /workspace/install_previz.log`.

## Step 3 — Confirm the GPU stack wasn't disturbed

```bash
/workspace/ComfyUI/venv/bin/python - <<'EOF'
import torch, torchvision, numpy, onnxruntime as ort
print("torch", torch.__version__, "| torchvision", torchvision.__version__, "| numpy", numpy.__version__)
print("onnxruntime", ort.__version__, ort.get_available_providers())
EOF
```

**Expected:** torch still `2.8.0+cu128`, numpy `1.26.4`, onnxruntime `1.26.0`, and the providers include
`CUDAExecutionProvider`. If anything changed, **stop**. Gemini: compare it with these values and help me fix it
before going on. For onnxruntime, the fix is `source scripts/runpod/env.sh && repair_onnxruntime`.

## Step 4 — Download the models (~6 GB)

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/download_models.sh previz
```

| File | Folder | What it's for |
|---|---|---|
| `dreamshaper_8.safetensors` | `models/checkpoints` | SD1.5 image model (the style comes from your prompt) |
| `v3_sd15_mm.ckpt` | `models/animatediff_models` | AnimateDiff v3 motion module |
| `control_v11f1p_sd15_depth_fp16.safetensors` | `models/controlnet` | depth guide (both routes) |
| `control_v11p_sd15_canny_fp16.safetensors` | `models/controlnet` | edge guide (`--clay`) |
| `control_v11p_sd15_normalbae_fp16.safetensors` | `models/controlnet` | normal-pass guide (`--normal-frames`) |

All of them are public; no `HF_TOKEN` is needed. Files that are already present are skipped (for example
DreamShaper, if the Yvann models from guide 03 are installed). The Depth Anything V2 checkpoint (~1.3 GB)
downloads itself the first time a `--clay` job runs.

**Expected:** a line per file, then `[✓] done`. Check with
`ls -la /workspace/ComfyUI/models/{animatediff_models,controlnet}`.

## Step 5 — Restart ComfyUI

```bash
bash /workspace/aether-fx-engine/scripts/runpod/start_comfy.sh
```

**Expected:** `[✓] ComfyUI is up on :8188`. If it prints `some custom nodes failed to import`, run
`grep -B2 -A20 -i "AnimateDiff\|VideoHelper\|controlnet_aux" /workspace/comfyui.log | head -80` and paste
the output.

## Step 6 — Client CLI (skip if `/workspace/aether-venv` already exists)

```bash
python3 -m venv /workspace/aether-venv          # use python3.12 if python3 is 3.13+
/workspace/aether-venv/bin/pip install -q -e /workspace/aether-fx-engine
/workspace/aether-venv/bin/python /workspace/aether-fx-engine/scripts/render_blender_video.py --help | head -20
```

If the venv already exists, just rerun the `pip install -e` line so it picks up the new code.

## Step 7 — Export from Blender (on the Mac)

Keep the shot to around **48–120 frames at 24 fps** for the first tests. The CLI scales frames so the short
side is 512 px (16:9 becomes 912×512), so there's no need to render bigger than 1280×720.

**Route A, clay render (quickest):**
1. Viewport shading: **Solid**, lighting **Studio** or a grey **MatCap**, colour **Single** (light grey). Turn
   on **Cavity** and **Shadow** if you want stronger edges. Turn off **Overlays** (grid, outlines,
   gizmos) so they don't show up as edges.
2. *View → Viewport Render Animation*, with output set to **FFmpeg / MPEG-4 (H.264)** or a **PNG** sequence.

**Route B, render passes (most accurate geometry):**
1. *View Layer Properties → Passes*: tick **Z** (and **Normal** if you want the normal guide).
2. In the Compositor, add a **File Output** node set to **OpenEXR**, with an input for Depth and one for
   Normal, writing into `blender_out/depth/` and `blender_out/normal/`. Then render the animation (Eevee is
   fine).

The CLI handles raw Z, including Blender's 1e10 background, and flips it to the near-is-white convention.

Upload the result with JupyterLab's file browser into `/workspace/aether-fx-engine/inputs/` (a video file,
or a zip of the frame folders that you unzip in the terminal).

## Step 8 — First run (short test), then the full shot

```bash
cd /workspace/aether-fx-engine
A=/workspace/aether-venv/bin/python
mkdir -p /workspace/exports/video

# Route A: clay render. 32 frames first to check that everything works.
$A scripts/render_blender_video.py --clay inputs/shot_01_clay.mp4 \
    --prompt "cinematic 90s vinyl doll, glossy plastic, neon water splash, dynamic studio lighting" \
    --frames 32 --seed 42 --output /workspace/exports/video/shot_01_test.mp4

# Route B: depth (+ normal) passes
$A scripts/render_blender_video.py --depth-frames inputs/blender_out/depth/ \
    --normal-frames inputs/blender_out/normal/ \
    --prompt "cinematic 90s vinyl doll, glossy plastic, neon water splash, dynamic studio lighting" \
    --frames 32 --seed 42 --output /workspace/exports/video/shot_01_passes_test.mp4
```

**Expected:** a summary line like `[*] 32 frames @ 24 fps, 912x512 (clay -> depth estimate + canny)`, the
uploads, sampler progress, then `[✓] /workspace/exports/video/shot_01_test.mp4`. Download it from the file
browser and check it. Then drop `--frames` (or set it to the full length) for the whole shot.

Tuning (all of these are in `--help`):

| Want | Change |
|---|---|
| Follows the clay shapes more closely | `--depth-strength 1.0` (default 0.8), `--canny-strength 0.7` (default 0.5) |
| More freedom in style and detail | lower those, e.g. `--depth-strength 0.6 --canny-strength 0.3`, or `--canny-strength 0` for depth only |
| Less flicker / smoother motion | keep `--cfg` at 6–7, try `--steps 30`; the context window is `--context-length 16` (the motion model's native length) |
| Different look per run, or a repeatable one | change or fix `--seed` |
| Larger output | `--width 1024 --height 576` (multiples of 8; uses more VRAM and time) |
| Different SD1.5 model / ControlNet files | `--checkpoint`, `--motion-model`, `--depth-controlnet`, `--canny-controlnet`, `--normal-controlnet` |

**Troubleshooting.** Before queueing, the CLI checks the server. If it prints
`workflow doesn't match the server:`, the list after it names exactly what's missing.

| Symptom | Likely cause / fix |
|---|---|
| `node class 'ADE_AnimateDiffLoaderGen1' … not installed` (or `VHS_LoadImages`, `DepthAnythingV2Preprocessor`) | Step 2 didn't finish, or ComfyUI wasn't restarted. Check `/workspace/comfyui.log` (Step 5). |
| `control_net_name=… not available` / `model_name=… not available` / `ckpt_name=… not available` | Step 4 isn't finished. Compare `ls /workspace/ComfyUI/models/controlnet` with the names in the table. |
| `--clay with a video file needs ffmpeg` | Run `apt-get install -y ffmpeg`, or pass a folder of PNG frames. |
| Stuck at the start of a `--clay` job | Depth Anything V2 is downloading on its first run. Watch with `tail -f /workspace/comfyui.log`. |
| `CUDA out of memory` | Use fewer `--frames` per job, a smaller `--width/--height`, or `--context-length 12`. |
| Output looks like grey clay | The guides are too strong for the prompt. Lower `--depth-strength` / `--canny-strength`, and add the look to the prompt (materials, lighting, colour). |
| Viewport grid or outlines appear in the video | Turn off Overlays in Blender and re-export (Step 7). |
| Errors mentioning `numpy`, `_ARRAY_API`, or LivePortrait stops using the GPU | Something replaced numpy or onnxruntime. Rerun Step 3 and fix it before anything else. |

## Running from the Mac instead (optional)

The same CLI works from the Mac against the pod's public URL. It uploads the frames over HTTPS:

```bash
python scripts/render_blender_video.py --clay ./previz/shot_01_clay.mp4 --prompt "..." \
    --comfy-url https://<POD_ID>-8188.proxy.runpod.net --output ./exports/video/shot_01.mp4
```

## Notes on how it works (for Gemini)

- The template's nodes are addressed by `_meta.title`: `checkpoint`, `context_options`, `animatediff`,
  `positive_prompt`, `negative_prompt`, `depth_frames`, `normal_frames`, `depth_controlnet`,
  `normal_controlnet`, `apply_depth`, `apply_normal`, `latent`, `sampler`, `decode`, `video_out`.
- With `--clay`, the frames go into the `depth_frames` loader. The CLI adds `depth_estimate`
  (`DepthAnythingV2Preprocessor`) and `canny_edges` (core `Canny`), points `apply_depth` at the depth estimate,
  and reuses the second ControlNet branch (`apply_normal`, `normal_controlnet`) for Canny.
- Frames are uploaded into a per-job subfolder of `ComfyUI/input/` (`<job>_clay`, `<job>_depth`,
  `<job>_normal`) and loaded with `VHS_LoadImages`. The template has no absolute paths.
- `--dry-run --dump-payload payload.json` writes the exact API payload without contacting the server. That's
  useful for checking the graph.
- The latent batch is the whole shot. AnimateDiff denoises it in overlapping 16-frame windows
  (`ADE_StandardStaticContextOptions`), which is what keeps long shots consistent.

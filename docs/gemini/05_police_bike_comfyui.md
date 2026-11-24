# Police Bike: AI world from Blender depth, rider matte, composite (RunPod) — guide for Gemini

> **How to use this file:** paste the whole thing into Gemini and say *"Walk me through this one step at a
> time. I'll paste the terminal output after each step."* Gemini: please follow the steps in order, give me
> one step at a time, and wait for my output before moving on.

---

## Context for Gemini (read first)

I'm making a music video: a policeman on a motorbike, side-on, locked at the centre of the frame, while
an AI-painted world scrolls past and the camera zooms. The full brief is in the repo at
`docs/projects/police-bike/brief.md`. There are three workflows:

| # | What | How it runs here | Status |
|---|---|---|---|
| **2** | **The world:** Blender depth frames → AI world frames, frame for frame, with **Wan 2.1 VACE** | `scripts/render_world_vace.py` (CLI; does chunking, loop joining, prompt schedule) | **Go/no-go passed** on a real A40 (2026-11-24): use 14B (~21 min per 89 frames on an A40). Results: `docs/projects/police-bike/aether_side_status.md` |
| 1 | **Rider:** green-screen clip → upscale (SeedVR2) → matte (BiRefNet / MatAnyone) → RGBA without green spill | Upscale and matte: built by hand in the ComfyUI UI (Step 10). Despill + RGBA: `scripts/rider_rgba.py` | UI part not built yet; despill script tested locally |
| 3 | **Composite:** world × shadow, rider on top | `scripts/composite_shot.py` (plain Python, runs anywhere) | Tested locally |

**Do Workflow 2 first.** It decides whether the whole approach works.

I'm running ComfyUI on a **RunPod GPU pod** (the L40S, 48 GB, torch `2.8.0+cu128`, Python 3.12) and working
in the **JupyterLab terminal**. Repo: `/workspace/aether-fx-engine`, branch `feature/multi-workflow-engine`.
Already on the pod and working: LivePortrait (needs `onnxruntime-gpu==1.26.0`, `numpy==1.26.4`), TRELLIS
with BiRefNet (ComfyUI-RMBG), and maybe the audio packs from guide 02. **Don't break any of that.**

### Rules for this install (important)

1. Install node packs **only** with `scripts/runpod/install_audio_video.sh police-bike` (it calls
   `safe_node_install.sh`). That keeps torch / torchvision / torchaudio / xformers / onnxruntime pinned
   and `numpy<2`.
2. **Never** `pip install` torch, torchvision, torchaudio, xformers, onnxruntime or numpy by hand, and don't
   install these packs from ComfyUI-Manager (Manager installs skip the pins).
3. ComfyUI's Python is `/workspace/ComfyUI/venv/bin/python`. The client CLI uses `/workspace/aether-venv`.
4. `/root` is wiped when the pod restarts; `/workspace` persists.
5. Don't run this at the same time as another guide's install (02 or 04). Both restart ComfyUI.

---

## Step 1 — Check the pod, the disk and the repo

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv
/workspace/ComfyUI/venv/bin/python -c "import torch, numpy; print(torch.__version__, torch.cuda.is_available(), numpy.__version__)"
df -h /workspace | tail -1
cd /workspace/aether-fx-engine && git status --short | head
git fetch origin && git checkout feature/multi-workflow-engine && git pull
git log --oneline -1
```

**Expected:** a 48 GB card, `2.8.0+cu128 True 1.26.4`, and a clean `git status`. If `git status` lists
changed files, **stop**. Gemini: help me commit and push them, or stash them, before pulling.

Disk needed: **~14 GB** for the 1.3B test model, **~35 GB more** for the 14B model, and **~10-20 GB** for SeedVR2
(it downloads on first use). If free space is under ~60 GB, grow the network volume in the RunPod console first.

## Step 2 — Install the node packs (and update ComfyUI if it's too old)

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/install_audio_video.sh police-bike 2>&1 | tee /workspace/install_police_bike.log
```

What it does:

- Checks that ComfyUI has the built-in **`WanVaceToVideo`** node. If it doesn't, it runs `git pull` on
  ComfyUI and installs its requirements under the pins. That's the only time ComfyUI itself gets updated.
- Installs or updates **VideoHelperSuite** (frame folders in and out), **KJNodes** (helpers),
  **SeedVR2_VideoUpscaler** and **ComfyUI-RMBG** (BiRefNet and SAM2 masks; it's probably already there from TRELLIS).

**Expected:** `[✓] ComfyUI has WanVaceToVideo`, `[✓] <name> installed` for each pack, then
`[✓] onnxruntime-gpu==1.26.0` and `[✓] done`. Gemini: if anything else fails, ask me for
`grep -n "failed\|error" /workspace/install_police_bike.log`.

## Step 3 — Confirm the GPU stack wasn't disturbed

```bash
/workspace/ComfyUI/venv/bin/python - <<'EOF'
import torch, torchvision, numpy, onnxruntime as ort
print("torch", torch.__version__, "| torchvision", torchvision.__version__, "| numpy", numpy.__version__)
print("onnxruntime", ort.__version__, ort.get_available_providers())
EOF
```

**Expected:** torch still `2.8.0+cu128`, numpy `1.26.4`, onnxruntime `1.26.0`, and the providers include
`CUDAExecutionProvider`. If anything changed, **stop**. For onnxruntime, the fix is
`source scripts/runpod/env.sh && repair_onnxruntime`. For anything else, Gemini: help me put it back first.

## Step 4 — Download the Wan VACE models

Start with the small model only. The 14B comes after the first test works.

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/download_models.sh wan-vace          # 1.3B + text encoder + VAE (~14 GB)
ls -la /workspace/ComfyUI/models/{diffusion_models,text_encoders,vae}
```

| File | Folder |
|---|---|
| `wan2.1_vace_1.3B_fp16.safetensors` (fast tests) | `models/diffusion_models` |
| `wan2.1_vace_14B_fp16.safetensors` (quality; `download_models.sh wan-vace-14b`) | `models/diffusion_models` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders` |
| `wan_2.1_vae.safetensors` | `models/vae` |

All of them are public, so no `HF_TOKEN` is needed. **Expected:** a line per file, then `[✓] done`.

## Step 5 — Restart ComfyUI

```bash
bash /workspace/aether-fx-engine/scripts/runpod/start_comfy.sh
```

**Expected:** `[✓] ComfyUI is up on :8188`. If it prints `some custom nodes failed to import`, run
`grep -B2 -A20 -i "SeedVR2\|RMBG\|VideoHelper\|KJNodes" /workspace/comfyui.log | head -80` and paste it.

## Step 6 — Client CLI

```bash
[ -d /workspace/aether-venv ] || python3 -m venv /workspace/aether-venv   # use python3.12 if python3 is 3.13+
/workspace/aether-venv/bin/pip install -q -e /workspace/aether-fx-engine
/workspace/aether-venv/bin/python /workspace/aether-fx-engine/scripts/render_world_vace.py --help | head -20
```

## Step 7 — Upload the Blender shots

On the Mac, zip each shot folder so the zip contains `depth/`, `shadow/`, `matte/`, `env/` and `beauty/`
(each full of `name_####.png`), for example `loop.zip` and `zoom.zip`. Upload them with JupyterLab's file
browser into `/workspace/aether-fx-engine/inputs/police-bike/`, then:

```bash
cd /workspace/aether-fx-engine/inputs/police-bike
for z in *.zip; do unzip -oq "$z" -d "${z%.zip}"; done
for s in */; do echo "$s: $(ls $s/depth | wc -l) depth frames"; done
```

**Expected:** `loop/: 89 depth frames` and `zoom/: 267 depth frames`. If the zip put an extra folder level in
(`loop/loop/depth`), move it up one level.

## Step 8 — The go/no-go test (Workflow 2)

```bash
cd /workspace/aether-fx-engine
A=/workspace/aether-venv/bin/python
S=inputs/police-bike
W=/workspace/exports/police-bike/world

# 8a. Smoke test: 17 frames with the small model, about a minute. Checks that everything is wired up.
$A scripts/render_world_vace.py --depth-frames $S/loop/depth --frames 17 \
    --prompt "rainy neon city street at night, cinematic" --seed 42 --output-dir $W/smoke

# 8b. The loop shot, all 89 frames in one chunk, made seamless.
$A scripts/render_world_vace.py --depth-frames $S/loop/depth --chunk 89 --loop \
    --prompt "rainy neon city street at night, cinematic" --seed 42 --output-dir $W/loop_neon_1.3b

# Turn the frames into an MP4 to watch (24 fps; -stream_loop plays it 3 times so you can see the seam).
ffmpeg -v error -y -framerate 24 -i $W/loop_neon_1.3b/world_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 16 \
    /workspace/exports/police-bike/loop_neon_1.3b.mp4
ffmpeg -v error -y -stream_loop 2 -i /workspace/exports/police-bike/loop_neon_1.3b.mp4 -c copy \
    /workspace/exports/police-bike/loop_neon_1.3b_x3.mp4
```

**Expected:** `[*] 89 frames, 768x432, wan2.1_vace_1.3B_fp16.safetensors, strength 1, seed 42; 1 chunk(s) + loop join`,
the uploads and sampler progress for each pass, then `[✓] 89 frames -> …/world_####.png`. The output keeps the
depth's frame numbers (`depth_0001` → `world_0001`). Download the MP4s from the file browser.

**What to check (the brief's questions):**

1. Does the road stay where the Blender road is? Put it side by side with the `beauty` frames.
2. Does the world scroll smoothly at our speed, with no stutter?
3. Flicker: does the texture boil from frame to frame?
4. In the `_x3` version: is there a jump where the loop wraps?

Then the same with the **14B model**, and then the **zoom** shot. Zoom has 267 frames, so it runs in 4 chunks
of up to 81 frames, each starting from the last 13 frames of the one before:

```bash
bash scripts/runpod/download_models.sh wan-vace-14b      # once, ~35 GB
$A scripts/render_world_vace.py --depth-frames $S/loop/depth --chunk 89 --loop --model 14b \
    --prompt "rainy neon city street at night, cinematic" --seed 42 --output-dir $W/loop_neon_14b
$A scripts/render_world_vace.py --depth-frames $S/zoom/depth --model 14b \
    --prompt "rainy neon city street at night, cinematic" --seed 42 --output-dir $W/zoom_neon_14b
```

On the zoom shot, also check: does it hold up as the camera pulls back 30×, and is there a visible jump at a
chunk border (new chunks take over at frames 82, 150 and 218)?

**Report back** (to Claude, and for the Blender side): model size, `--strength`, the resolution, seconds per
chunk (shown in the progress), and the answers to the checks above. A strength sweep on the loop is the
quickest way to learn the most:

```bash
for st in 0.6 0.8 1.0 1.2; do
  $A scripts/render_world_vace.py --depth-frames $S/loop/depth --chunk 89 --strength $st --model 14b \
      --prompt "rainy neon city street at night, cinematic" --seed 42 --output-dir $W/loop_strength_$st
done
```

## Step 9 — Tuning and longer shots

All of these flags are in `--help`:

| Want | Change |
|---|---|
| Follows the greybox more strictly / more freely | `--strength 1.2` / `--strength 0.7` (default 1.0) |
| Final quality | `--model 14b --width 1280 --height 720` (slower, more VRAM). Previews: the default 768x432, or 1024x576 |
| 14B on a 24 GB card | add `--weight-dtype fp8_e4m3fn` |
| Same look on a re-run | keep `--seed` fixed per section |
| Different world per music section | `--prompt "neon city…" --prompt-at 120 "watercolour forest…"`. The switch happens at the first chunk border after frame 120, carried over smoothly from the previous chunk's frames |
| Style from a picture | `--reference-image style.png` |
| Smoother chunk borders | a longer `--overlap` (default 13; 17 or 21 also work) |
| Interrupted run (or tweaking only the end) | rerun the same command with `--resume`; finished chunks in `<output-dir>/_chunks` are reused |
| Fewer artefacts | `--steps 30`; `--cfg` between 5 and 7 |

Sizes must be multiples of 16, which is why 960x540 isn't offered: use 768x432, 1024x576 or 1280x720 (all exactly
16:9, so they scale to 960x540 / 1920x1080 with no cropping). The composite step scales the world to the shadow
pass's size.

Not built yet, and parked until Workflow 2 passes: using `env_####.png` as a second control, and a gradual
crossfade between prompts (today prompts switch at a chunk border).

## Step 10 — Workflow 1: rider upscale + matte (built in the ComfyUI UI)

Gemini: this part has no script yet. Help me build it in the ComfyUI web UI (open the pod's port 8188 from
the RunPod console). Once it works, save it, and Claude will turn it into a batch CLI.

Upload the rider clips into `/workspace/ComfyUI/input/rider/` first.

**10a. Upscale (one workflow per clip):**

1. **Load Video (Upload)** (VideoHelperSuite): the clip, `force_rate` **0** (keeps 24 fps and every frame),
   `frame_load_cap` 0.
2. **SeedVR2 (Down)Load DiT Model**: `seedvr2_ema_7b_fp16.safetensors` on the 48 GB card (`3b` for quick tests).
   **SeedVR2 (Down)Load VAE Model**: the default `ema_vae_fp16.safetensors`. They download themselves
   into `models/SEEDVR2` the first time.
3. **SeedVR2 Video Upscaler**: `resolution` **1080** (the short side, so 1280x720 → 1920x1080; 2160 for 4K),
   `batch_size` as high as fits (it must be 4n+1: try **33**; bigger batches mean steadier texture),
   `color_correction` **lab** or **wavelet**, and a fixed seed. Use the **same settings for every clip**.
4. **Save Image**, `filename_prefix` `police_bike/upscaled/<clip name>/up`.

**10b. Matte, try both and keep whichever flickers least on spokes, windscreen, visor and beacon pole:**

- **BiRefNet:** load the *upscaled* frames (**Load Images (Path)** from VideoHelperSuite, pointing at the
  output folder from 10a) → the **BiRefNet** node from ComfyUI-RMBG (model `BiRefNet-general` or
  `BiRefNet_HR`) → its **MASK** output → **Convert Mask to Image** → **Save Image**, prefix
  `police_bike/matte/<clip name>/matte`.
- **MatAnyone (optional):** `bash scripts/runpod/install_audio_video.sh matanyone`, then restart ComfyUI. It
  needs a mask for the first frame only (from the BiRefNet output on frame 1, or SAM2 from ComfyUI-RMBG),
  then tracks the matte through the clip. Save its matte the same way.

The green floor shadow under the wheels must **not** be in the matte. If it shows as a grey smudge, raise the
mask threshold/sensitivity on the BiRefNet node, or use MatAnyone. Tell Claude if neither fixes it, and a floor cut-off
can be added to the despill script.

**10c. Despill + RGBA (terminal):**

```bash
cd /workspace/aether-fx-engine
C=clip_01
/workspace/aether-venv/bin/python scripts/rider_rgba.py \
    --frames /workspace/ComfyUI/output/police_bike/upscaled/$C \
    --matte  /workspace/ComfyUI/output/police_bike/matte/$C \
    --output /workspace/exports/police-bike/rider_rgba/$C
```

It removes the green from see-through and edge pixels only, measuring the screen colour each frame, so the
hi-vis jacket and livery keep their yellow-green. If the jacket edges go grey, add `--tolerance 0.15`. If green
fringes remain, use `--tolerance 0.35` or `--edge 5`. Output: `rider_#####.png`, RGBA, same numbers as the input.

**10d. Save the workflow** (UI menu → Workflow → Save, and Export (API)) into
`/workspace/aether-fx-engine/workflows/police_bike/` as `rider_upscale_matte.json` and
`rider_upscale_matte_api.json`, then commit and push them so Claude can script the batch version.

## Step 11 — Workflow 3: composite

The rider sequence for a shot comes from the Blender stage already placed in frame (same size as the passes).

```bash
cd /workspace/aether-fx-engine
/workspace/aether-venv/bin/python scripts/composite_shot.py \
    --world /workspace/exports/police-bike/world/loop_neon_14b \
    --shadow inputs/police-bike/loop/shadow \
    --rider  inputs/police-bike/loop/rider \
    --shadow-strength 0.8 \
    --output /workspace/exports/police-bike/comp/loop_neon
ffmpeg -v error -y -framerate 24 -i /workspace/exports/police-bike/comp/loop_neon/comp_%04d.png \
    -c:v libx264 -pix_fmt yuv420p -crf 16 /workspace/exports/police-bike/loop_neon_comp.mp4
```

Leave out `--rider` to check world × shadow on its own. The script stops if any sequence is missing a frame. It
runs on the Mac too (plain Python, no GPU). This can also be done in Resolve, After Effects or Blender instead.

## Troubleshooting

Before queueing, the CLI checks the server. If it prints `workflow doesn't match the server:`, the list after
it names what's missing.

| Symptom | Likely cause / fix |
|---|---|
| `node class 'WanVaceToVideo' … not installed` | ComfyUI is older than the VACE nodes and Step 2's update didn't run or failed. Check the top of `/workspace/install_police_bike.log` |
| `node class 'VHS_LoadImages' … not installed` | Step 2 didn't finish, or ComfyUI wasn't restarted (Step 5) |
| `unet_name=… not available` / `clip_name=…` / `vae_name=…` | Step 4 isn't finished; compare `ls /workspace/ComfyUI/models/diffusion_models` with the table |
| `--width must be a multiple of 16` | Use 768x432, 1024x576 or 1280x720 |
| `CUDA out of memory` | `--weight-dtype fp8_e4m3fn`, a smaller size, or `--chunk 49 --overlap 9` |
| `expected 81 frames back, got …` | Paste the full output to Claude: the server dropped or added frames |
| The world is a grey copy of the depth | Strength is too high for the prompt: try `--strength 0.7`, and add materials, light and colour to the prompt |
| A policeman or bike appears in the world | The negative prompt already lists them; add more words with `--negative "…"` (this replaces the default list, so keep its words) |
| Visible jump at a chunk border | A longer `--overlap` (17 or 21); keep the same `--seed` and prompt across the border |
| Errors mentioning `numpy`, `_ARRAY_API`, or LivePortrait stops using the GPU | Something replaced numpy or onnxruntime. Rerun Step 3 and fix it first |

## Notes on how it works (for Gemini)

- Template `workflows/templates/wan_vace_depth_to_video.json`, all built-in nodes except `VHS_LoadImages`:
  `UNETLoader` → `ModelSamplingSD3` (shift 8) → `KSampler` (uni_pc / simple, 20 steps, cfg 6), with
  `CLIPLoader` (type `wan`), `VAELoader`, `WanVaceToVideo` (control video + mask), `TrimVideoLatent`,
  `VAEDecode` and `SaveImage`. Nodes are addressed by title (`diffusion_model`, `vace`, `control_frames`,
  `mask_frames`, `sampler`, `frames_out`…).
- **Chunks:** lengths are 4k+1 (Wan's rule). A chunk after the first gets a control video whose first
  `--overlap` frames are the previous chunk's *generated* frames (mask black = keep) and whose rest is depth
  (mask white = generate), so it continues from what's already there. The last chunk is shorter if needed. Frames
  past the end repeat the last depth frame and are dropped.
- **Loop:** one extra pass whose control is [last 13 generated frames before the seam] + [depth for the last
  ~16 frames] + [the first 13 generated frames], with only the middle generated. Those frames replace the end of
  the shot, so frame 89 leads into frame 1.
- Frames are fed 1:1 at 24 fps (no resampling to Wan's 16 fps), as the brief asks.
- `--dry-run --dump-payload p.json` writes the first chunk's API payload without contacting the server.

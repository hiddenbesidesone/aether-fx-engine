# Image → 3D mesh + Gaussian splat (TRELLIS) on RunPod — guide for Gemini

> **How to use this file:** paste the whole thing into Gemini and say *"Walk me through this one step at a
> time. I'll paste the terminal output after each step."* Gemini: please follow the steps in order, give me
> one step at a time, and wait for my output before moving on.

---

## Context for Gemini (read first)

I'm running ComfyUI on a **RunPod GPU pod** and working in the **JupyterLab terminal**. My project repo,
`aether-fx-engine`, has scripts that install and run an image-to-3D workflow:

- **Input:** one concept image (a doll's head, a toy water pistol). A transparent PNG works best.
- **Output:** a `.glb` mesh (Blender: *File → Import → glTF*) and/or a 3D Gaussian splat `.ply` (Blender:
  SkySplat add-on).
- **Engine:** TRELLIS, via the ComfyUI node pack `ComfyUI-IF_Trellis`. It only works on CUDA.

**Status:** this workflow is built and passes tests against a fake server, but it has **never run on a real
GPU**. This is its first real run, so expect to troubleshoot.

What's already on the pod and working: ComfyUI plus a **LivePortrait** workflow. LivePortrait depends on
`onnxruntime-gpu==1.26.0` (CUDA 12) and torch 2.8 / CUDA 12.8. **Protecting that setup is the top priority.**

### Rules for this install (important)

1. **Never run `pip install -r requirements.txt` inside `ComfyUI-IF_Trellis`.** That file targets torch 2.5 /
   CUDA 12.4. It installs the CPU `onnxruntime` package, which silently pushes LivePortrait's face detection
   onto the CPU (a 10-second step becomes over an hour). It also installs an unpinned `xformers`, which can
   replace torch. The repo's `scripts/runpod/install_trellis.sh` installs the same libraries, matched to the
   torch that's already installed.
2. **Never `pip install torch`, `torchvision`, `torchaudio`, `xformers` or `onnxruntime*` by hand.** The repo
   scripts pin these automatically (they write `/workspace/.aether/constraints.txt` and set `PIP_CONSTRAINT`).
3. Use ComfyUI's own Python for anything ComfyUI loads: `/workspace/ComfyUI/venv/bin/python`. Step 1 checks
   this path.
4. `/root` is wiped when the pod restarts; `/workspace` persists. The scripts keep caches on `/workspace`.

### Known risk: the GPU generation

TRELLIS needs compiled CUDA libraries: **flash-attn or xformers** (attention), **spconv** (sparse
convolutions), **nvdiffrast** and **diff-gaussian-rasterization** (rendering). The planned GPU is an
**RTX PRO 6000 (Blackwell, sm_120)**. Prebuilt wheels don't always include Blackwell kernels yet. Upstream
flash-attn hasn't confirmed sm_120 support, so xformers is the fallback.
`scripts/runpod/check_trellis.py` runs each library on a tiny GPU input and reports PASS or FAIL.
**If it reports that TRELLIS can't run, the practical fix is to run the 3D jobs on an Ada or Ampere GPU pod
(L40S, RTX 6000 Ada, A6000, RTX 4090).** All the wheels support those. Attach the same network volume if
it's in the same datacenter.

---

## Step 1 — Check the pod

```bash
nvidia-smi --query-gpu=name,compute_cap,memory.total --format=csv
ls /workspace/ComfyUI/main.py /workspace/ComfyUI/venv/bin/python
/workspace/ComfyUI/venv/bin/python -c "import torch,sys; print(sys.version.split()[0], torch.__version__, torch.version.cuda, torch.cuda.is_available())"
nvcc --version | tail -1
df -h /workspace | tail -1
```

**Expected:** a GPU with **≥ 16 GB** of VRAM; both paths exist; Python 3.10–3.12; torch `2.8.x+cu128`;
`True`; an `nvcc` line reporting release 12.x; at least ~40 GB free on `/workspace`.

- *If the venv lives somewhere else* (for example `/workspace/venv`), the scripts still find it. Otherwise
  set `export VENV=/path/to/venv` before each script.
- *If `nvcc` is missing*, the pod template isn't a "devel" image. Two compiled libraries need it. Gemini:
  help me install the CUDA 12.8 toolkit (`cuda-toolkit-12-8` from NVIDIA's apt repo), or switch to a RunPod
  PyTorch **devel** template.

## Step 2 — Get the repo onto the pod (or update it)

```bash
cd /workspace
[ -d aether-fx-engine ] || git clone https://github.com/hiddenbesidesone/aether-fx-engine.git
cd /workspace/aether-fx-engine
git fetch origin && git checkout feature/multi-workflow-engine && git pull
ls scripts/runpod/
```

**Expected:** `check_trellis.py  download_models.sh  env.sh  install_audio_video.sh  install_trellis.sh
safe_node_install.sh  start_comfy.sh`

## Step 3 — Install the background-remover node (ComfyUI-RMBG)

The workflow cuts the subject out with BiRefNet before running TRELLIS.

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/safe_node_install.sh ComfyUI-RMBG https://github.com/1038lab/ComfyUI-RMBG.git
```

This node's `requirements.txt` also lists CPU `onnxruntime` and an unpinned `onnxruntime-gpu`. The script
drops those lines and pins everything else. **Expected:** it ends with `[✓] onnxruntime-gpu==1.26.0` and
`[✓] ComfyUI-RMBG installed`. Some optional extras (for example `groundingdino-py`) may be reported as
failed. That's fine, because BiRefNet doesn't use them.

## Step 4 — Install TRELLIS (10–25 minutes; two parts compile from source)

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/install_trellis.sh 2>&1 | tee /workspace/install_trellis.log
```

It prints `=== 1/7 … 7/7 ===` sections, then runs the GPU check. **The ending matters most.** Paste
everything from `=== checking the install on this GPU ===` onward to Gemini. A good result looks like this:

```
  PASS  torch + CUDA                          torch 2.8.0+cu128, NVIDIA RTX PRO 6000 ... (sm_120)
  PASS  flash-attn (run)   ...or FAIL, as long as xformers passes
  PASS  xformers (run)
  PASS  spconv implicit_gemm (run)   ...or FAIL, as long as native passes
  PASS  spconv native (run)
  PASS  nvdiffrast (rasterize)
  PASS  diff-gaussian-rasterization (render)
  PASS  kaolin / flexicube
  PASS  mesh/postprocess libs
  PASS  onnxruntime-gpu (LivePortrait)

Use: SPARSE_ATTN_BACKEND=flash_attn  SPCONV_ALGO=implicit_gemm
TRELLIS stack OK. Restart ComfyUI with scripts/runpod/start_comfy.sh so it picks these up.
```

The script saves the working choices to `/workspace/.aether/trellis_env.sh`. TRELLIS only reads them when
ComfyUI starts.

**Troubleshooting (Gemini: use the full log at `/workspace/install_trellis.log`):**

| Symptom | Likely cause / fix |
|---|---|
| `no kernel image is available for execution on the device` in a FAIL line | That wheel has no kernels for this GPU. If flash-attn **and** xformers both fail, or both spconv algorithms fail, use an Ada or Ampere pod for 3D (see "Known risk" above). |
| nvdiffrast or diff-gaussian-rasterization fails to compile | Paste the first `error:` lines. Usually it's a missing `nvcc`, a GCC/CUDA version mismatch, or `TORCH_CUDA_ARCH_LIST`. The script sets that to this GPU's architecture. |
| `onnxruntime-gpu (LivePortrait)` FAIL | Run `source scripts/runpod/env.sh && repair_onnxruntime`, then rerun `check_trellis.py` (below). |
| kaolin line says "patched" | No kaolin wheel exists for this torch, so the script swapped in a tiny stand-in for the one helper TRELLIS uses. That's fine. |

To rerun only the check:
`/workspace/ComfyUI/venv/bin/python scripts/runpod/check_trellis.py --write-env /workspace/.aether/trellis_env.sh`

## Step 5 — Restart ComfyUI with the fixes applied

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/start_comfy.sh
```

This script stops the running ComfyUI and reapplies the per-boot fixes: the InsightFace symlink and the
CUDA library paths from the LivePortrait guide, plus the TRELLIS settings. Then it starts ComfyUI in the
background (log: `/workspace/comfyui.log`) and waits until port 8188 responds. **Run it after every pod
restart.**

**Expected:** `[✓] TRELLIS: SPARSE_ATTN_BACKEND=… SPCONV_ALGO=…` and `[✓] ComfyUI is up on :8188`.
If it prints `some custom nodes failed to import`, run
`grep -B2 -A20 -i "IF_Trellis\|RMBG" /workspace/comfyui.log | head -80` and paste the output.

*If the pod template keeps its own ComfyUI running (a second ComfyUI appears, or the port stays busy),
tell Gemini how the template starts ComfyUI so we can stop it the template's way.*

## Step 6 — Set up the client CLI (one time)

The CLIs only talk to ComfyUI over HTTP, so they get their own small venv. That way nothing touches
ComfyUI's Python.

```bash
python3 -m venv /workspace/aether-venv
/workspace/aether-venv/bin/pip install -q -e /workspace/aether-fx-engine
/workspace/aether-venv/bin/python /workspace/aether-fx-engine/scripts/generate_3d_asset.py --help | head -5
```

(If `python3` is 3.13 or newer, use `python3.12 -m venv` instead. numpy 1.26 needs Python 3.12 or older.)

## Step 7 — Upload an image and run

Run `mkdir -p /workspace/aether-fx-engine/inputs /workspace/exports`. Then upload the concept image with
JupyterLab's file browser (the up-arrow icon) into `/workspace/aether-fx-engine/inputs/`, and run:

```bash
cd /workspace/aether-fx-engine
A=/workspace/aether-venv/bin/python

# First test: quick mesh only (the first run downloads TRELLIS-image-large, several GB, and DINOv2; give it time)
$A scripts/generate_3d_asset.py --image inputs/dollface_isolated.png --output-dir /workspace/exports/3d/

# Mesh + Gaussian splat, final-quality texture bake
$A scripts/generate_3d_asset.py --image inputs/dollface_isolated.png \
    --export-splat --texture-mode opt --output-dir /workspace/exports/3d/

# Splat only (skips the slow texture bake)
$A scripts/generate_3d_asset.py --image inputs/dollface_isolated.png --export-splat --splat-only \
    --output-dir /workspace/exports/3d/
```

**Expected:** progress lines, then for example `[✓] mesh  /workspace/exports/3d/dollface_isolated_trellis_<seed>.glb`
and `[✓] splat /workspace/exports/3d/dollface_isolated_trellis_<seed>.ply`. Download them from the JupyterLab
file browser (right-click → Download). Add `--seed N` to make a run repeatable.

Useful options: `--steps 25` (shape detail, 20–30), `--slat-steps 20`, `--texture-size 1024|2048`,
`--padding 0.10`. Everything is listed in `--help`.

**Before queueing, the CLI checks the server.** If it prints `workflow doesn't match the server:` followed by
a list, that list names exactly what's missing: a node that didn't load, or a model name. Paste it to Gemini.

| Symptom | Likely cause / fix |
|---|---|
| `node class 'IF_TrellisImageTo3D' is not installed` | The node failed to import. Check `/workspace/comfyui.log` (Step 5). |
| `node class 'BiRefNetRMBG' is not installed` | Step 3 didn't finish, or ComfyUI wasn't restarted afterwards. |
| CUDA `no kernel image` during the run | Only `check_trellis.py` can confirm this. Rerun it. If it now fails, see "Known risk". |
| Stuck at the first progress step | The first run is downloading models. Watch with `tail -f /workspace/comfyui.log`. |
| `.ply could not be downloaded` | The node didn't write the splat. Look for `TRELLIS` errors near the end of `/workspace/comfyui.log`. |
| `CUDA out of memory` | Lower `--texture-size`, or use `--splat-only`. |

## Step 8 — In Blender (on the Mac)

- **Mesh:** *File → Import → glTF 2.0*, then *Ctrl+A → Apply All Transforms*. To remesh and set up shaders,
  see `docs/3d_ai_to_blender_workflow_guide.md`.
- **Splat:** import the `.ply` with the SkySplat add-on. **Check its orientation**: TRELLIS rotates the
  points when it saves, so you may need to rotate it 90° on X. The splat carries base colour only, with no
  view-dependent shading, so it can look flatter than splats from captured footage.

## Running from the Mac instead (optional)

The same CLI works from the Mac against the pod's public URL:

```bash
python scripts/generate_3d_asset.py --image ./inputs/doll.png --export-splat \
    --comfy-url https://<POD_ID>-8188.proxy.runpod.net --output-dir ./exports/3d/
```

## Notes on how it works (for Gemini)

- The workflow template is `workflows/templates/image_to_3d_api.json`. The CLI addresses nodes by title, not
  by numeric ID.
- The node saves `output/<job>/<job>.glb` and `.ply`, but `/history` doesn't report the `.ply`, so the CLI
  downloads it from that known path.
- `save_glb` must stay on: with it off, the node crashes before writing the `.ply`. `--splat-only` keeps it
  on but sets `texture_mode=blank`, which skips the bake.
- TRELLIS reads its attention backend when ComfyUI **starts** (`SPARSE_ATTN_BACKEND`). Changing the loader's
  dropdown later does nothing. That's why `start_comfy.sh` exports it.
- Hunyuan3D-2 (`--engine hunyuan`) is a mesh-only alternative. It's in the CLI but not covered by this
  install guide.

# Aether FX Engine

ComfyUI-based VFX pipeline: audio-reactive visuals, video warping, and 3D/depth effects — runnable interactively or headlessly via the API.

## Layout

| Path | Purpose |
|---|---|
| `workflows/UI/<category>/` | Native ComfyUI workflows (drag-and-drop into the editor) |
| `workflows/api/<category>/` | Same workflows exported with **Export (API)** for headless runs |
| `custom_nodes/` | Our own nodes (symlinked into ComfyUI on deploy) |
| `custom_nodes.json` | Third-party node repos auto-installed by the deploy script |
| `scripts/deploy_cloud.sh` | Provision ComfyUI + nodes on a GPU box (RunPod etc.) and launch |
| `scripts/run_api_job.py` | Queue an API workflow, wait, and download outputs |
| `src/aether_engine/` | Python package: ComfyUI client, template payload builder, env check, image/file utils |
| `workflows/templates/` | API templates driven by the CLIs below (nodes addressed by title) |
| `scripts/generate_3d_asset.py` | Concept image → `.glb` mesh (TRELLIS or Hunyuan3D-2) and/or Gaussian splat `.ply` (TRELLIS) |
| `scripts/render_blender_video.py` | Blender depth/normal passes → ControlNet AnimateDiff MP4 |
| `scripts/run_brand_stylizer.py` | Batch SDXL restyle: LoRA stack + IP-Adapter + depth ControlNet |

Categories: `audio_reactive`, `video_warp`, `3d_depth`.

## Local setup (API client)

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.10–3.12 (numpy 1.26)
pip install -e ".[exr]"        # or: pip install -r requirements.txt
cp .env.example .env           # set COMFY_URL
aether-env-check               # numpy 1.26.x + CUDA/MPS/CPU report
```

**NumPy is pinned to `>=1.26.0,<2.0.0`.** torch 2.8, onnxruntime-gpu and insightface are built
against the NumPy 1.x ABI; `deploy_cloud.sh` exports `PIP_CONSTRAINT=constraints.txt` so custom-node
installs (e.g. `rembg`) can't upgrade it, then runs `env_check --gpu-box`.

## Cloud setup (GPU box)

```bash
git clone <this repo> /workspace/aether-fx-engine
cd /workspace/aether-fx-engine
./scripts/deploy_cloud.sh            # installs everything and starts ComfyUI on :8188
# COMFY_DIR=/path/to/ComfyUI ./scripts/deploy_cloud.sh --no-launch
```

Models are not tracked in git — place them in `$COMFY_DIR/models/`.

## Running a job

```bash
python scripts/run_api_job.py workflows/api/video_warp/my_warp.json \
  --set 6.text="liquid chrome" --set 3.seed=1234 --out output/
```

`--set NODE_ID.input=value` overrides any node input (values are parsed as JSON when possible).

## Workflow CLIs

All three take `--comfy-url` (local, SSH tunnel, or `https://<pod-id>-8188.proxy.runpod.net`),
upload their inputs, stream progress over the WebSocket, and download results. Before queueing
they check the payload against the server's `/object_info` and list any missing node packs or
model files. `--dry-run --dump-payload out.json` builds the payload without a server.

```bash
python scripts/generate_3d_asset.py --image ./inputs/doll_head.png --engine trellis \
    --steps 25 --output-dir ./exports/3d/

# + Gaussian splat for Blender (SkySplat); --splat-only skips the .glb texture bake and download
python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --engine trellis \
    --export-splat --texture-mode opt --output-dir ./exports/3d/

python scripts/render_blender_video.py --depth-frames ./blender_out/depth/ \
    --normal-frames ./blender_out/normal/ --prompt "cinematic 90s vinyl doll, neon water splash" \
    --frames 120 --fps 24 --output ./exports/video/previz_shot_01.mp4

python scripts/run_brand_stylizer.py --input-dir ./inputs/concepts/ \
    --lora "latex_vinyl_v2.safetensors:0.8" --ip-adapter-weight 0.65 --denoise 0.55 \
    --prompt "hyper-gloss black latex outfit, molded toy seam details" \
    --batch-count 4 --output-dir ./exports/stylized/
```

- **TRELLIS is CUDA-only** (spconv / flash-attn); pointed at a Mac/MPS server it exits and asks for the RunPod URL.
- **Splats:** `--export-splat` downloads `<image>_trellis_<seed>.ply` next to the `.glb`. `--texture-mode`
  (`fast` / `opt`) only changes the `.glb` texture bake, not the splat. The node doesn't report the `.ply`
  in `/history`, so the CLI fetches it from `output/<job>/<job>.ply`.
- Depth passes can be 16-bit PNG, 8-bit PNG or EXR. They are normalised over the whole sequence and
  inverted to near = white (`--no-invert-depth` if already converted). `--normal-frames` is optional.
- Model filenames default to common names (`dreamshaper_8`, `v3_sd15_mm.ckpt`, `sd_xl_base_1.0`, …);
  override with `--checkpoint`, `--motion-model`, `--controlnet`, etc.

Tests: `pip install -e ".[dev,exr]" && pytest` (runs the CLIs against an in-process mock ComfyUI).

## Custom nodes

- **face_removal_node** — `Face Mask (MediaPipe)`: detects faces per frame and outputs a feathered MASK (plus face count) for inpainting faces out of footage.

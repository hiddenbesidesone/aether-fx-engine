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

Categories: `audio_reactive`, `video_warp`, `3d_depth`.

## Local setup (API client)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set COMFY_URL
```

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

## Custom nodes

- **face_removal_node** — `Face Mask (MediaPipe)`: detects faces per frame and outputs a feathered MASK (plus face count) for inpainting faces out of footage.

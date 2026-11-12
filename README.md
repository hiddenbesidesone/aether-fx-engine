# Aether FX Engine

ComfyUI-based VFX pipeline: stylized character animation, image-to-3D, audio generation, audio-reactive
visuals and Blender-driven video. Every workflow runs headlessly on a RunPod GPU box through the API, with
CLIs that run on the pod or on a Mac.

## Status

| Workflow | Entry point | Status |
|---|---|---|
| Stylized LivePortrait (image + driving video → talking clip) | `scripts/run_stylized_liveportrait.py` | ✅ **Tested on RunPod.** Setup quirks: `docs/runpod_comfyui_liveportrait_setup_guide.md` |
| Concept image → 3D mesh `.glb` + Gaussian splat `.ply` (TRELLIS) | `scripts/generate_3d_asset.py` | 🟡 Built, mock-tested; **not yet run on a GPU.** Guide: `docs/gemini/01_…` |
| Music / soundscapes (Stable Audio Open, MusicGen) + Demucs stems | `scripts/generate_audio.py`, `scripts/separate_stems.py` | 🟡 Built, mock-tested; not yet run on a GPU. Guide: `docs/gemini/02_…` |
| Foley / ambience from video (MMAudio), muxed into the MP4 | `scripts/add_foley.py` | 🟡 Built, mock-tested; not yet run on a GPU. Guide: `docs/gemini/03_…` |
| Audio-reactive animation (Yvann nodes + AnimateDiff) | Yvann's example workflows in the ComfyUI UI | 🟡 Install + models scripted; no CLI. Guide: `docs/gemini/03_…` |
| Blender depth/normal passes → AnimateDiff video | `scripts/render_blender_video.py` | 🟡 Built, mock-tested; not yet run on a GPU |
| Batch SDXL brand restyle (LoRA + IP-Adapter + depth) | `scripts/run_brand_stylizer.py` | 🟡 Built, mock-tested; not yet run on a GPU |
| Hunyuan3D-2 mesh (alternative 3D engine) | `scripts/generate_3d_asset.py --engine hunyuan` | 🟡 Built, mock-tested; no install guide yet |

"Mock-tested" means the CLI, payload and output handling pass `pytest` against an in-process fake
ComfyUI (`tests/mock_comfy.py`). Node input names were checked against each node pack's source, but the
models haven't been run.

## Guides for setting up on RunPod (written to paste into Gemini)

| Guide | Covers |
|---|---|
| `docs/gemini/01_image_to_3d_and_gaussian_splat.md` | TRELLIS + BiRefNet install, GPU checks, mesh/splat runs, Blender import |
| `docs/gemini/02_audio_music_and_stems.md` | Stable Audio Open, MusicGen, Demucs: install, gated-model download, runs |
| `docs/gemini/03_video_foley_and_audio_reactive.md` | MMAudio Foley CLI; Yvann audio-reactive workflows in the UI |
| `docs/runpod_comfyui_liveportrait_setup_guide.md` | LivePortrait: InsightFace symlink, onnxruntime-gpu 1.26 pin, ldconfig |
| `docs/3d_ai_to_blender_workflow_guide.md` | Input prep, Blender retopology and doll/plastic shaders |

## Layout

| Path | Purpose |
|---|---|
| `scripts/runpod/` | Pod-side install and boot scripts (see below) |
| `scripts/*.py` | Workflow CLIs (see Status) |
| `scripts/run_api_job.py` | Queue any API workflow, wait, and download outputs |
| `scripts/deploy_cloud.sh` | Provision ComfyUI + every manifest node on a fresh GPU box and launch |
| `workflows/templates/` | API templates the CLIs drive (nodes addressed by `_meta.title`) |
| `workflows/liveportrait_stylized_api.json` | LivePortrait API workflow |
| `workflows/UI/<category>/`, `workflows/api/<category>/` | Editor / API exports of hand-built workflows |
| `src/aether_engine/` | Python package: ComfyUI client, template payload builder, env check, image/file utils |
| `custom_nodes/` | Our own nodes (`face_removal_node`: per-frame MediaPipe face mask) |
| `custom_nodes.json` | Third-party node packs installed by `deploy_cloud.sh` |
| `tests/` | pytest suite with a mock ComfyUI server |

## RunPod scripts (`scripts/runpod/`)

Each one finds ComfyUI at `/workspace/ComfyUI` and its venv (`$COMFY_DIR/venv` or `/workspace/venv`;
override with `COMFY_DIR` / `VENV`).

| Script | Does |
|---|---|
| `start_comfy.sh` | **Run after every pod start.** Re-links InsightFace models, registers the venv's CUDA libs with `ldconfig`, loads the TRELLIS backend choices, and (re)starts ComfyUI on :8188 (log: `/workspace/comfyui.log`) |
| `safe_node_install.sh <name> <url>` | Clone a node pack and install its requirements **without** torch/torchaudio/xformers/onnxruntime lines, pinned to the installed GPU stack; then removes CPU `onnxruntime` if anything pulled it in |
| `install_trellis.sh` | TRELLIS with spconv, flash-attn/xformers, kaolin, nvdiffrast and diff-gaussian-rasterization matched to the installed torch (the node's own requirements target torch 2.5) |
| `check_trellis.py` | Runs each TRELLIS CUDA library on this GPU and writes the attention/spconv backends that work |
| `install_audio_video.sh audio\|video\|yvann-deps\|all` | Audio, Foley and audio-reactive node packs; matches torchaudio to torch |
| `download_models.sh stable-audio\|mmaudio\|yvann` | Model weights into `ComfyUI/models` (Stable Audio needs `HF_TOKEN`) |
| `env.sh` | Shared helpers (`safe_pip`, `repair_onnxruntime`, `ensure_torchaudio`); caches on `/workspace/.cache` |

**Why the safe installer exists:** several node packs (`ComfyUI-RMBG`, `ComfyUI-IF_Trellis`) list CPU
`onnxruntime` and an unpinned `onnxruntime-gpu`. Either one breaks LivePortrait. The CPU wheel shadows the
GPU one, and onnxruntime-gpu ≥ 1.27 targets CUDA 13. In both cases face detection silently falls back to the
CPU, and a render takes over an hour.

## Running the CLIs

On the pod (from a separate small venv, so ComfyUI's Python is untouched):

```bash
python3 -m venv /workspace/aether-venv && /workspace/aether-venv/bin/pip install -e /workspace/aether-fx-engine
```

Or on the Mac:

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.10–3.12 (numpy 1.26)
pip install -e ".[exr]"
cp .env.example .env           # set COMFY_URL, e.g. https://<pod-id>-8188.proxy.runpod.net
```

Every CLI takes `--comfy-url` (default `$COMFY_URL`, else `http://127.0.0.1:8188`). Each one uploads its
inputs and streams progress. Before queueing, it checks the payload against the server's `/object_info`
and lists missing node packs or model files. `--dry-run --dump-payload out.json` builds the payload
without a server, and `--seed N` makes a run repeatable.

```bash
# 3D: mesh, or mesh + Gaussian splat for Blender (SkySplat); --splat-only skips the texture bake
python scripts/generate_3d_asset.py --image ./inputs/doll_head.png --output-dir ./exports/3d/
python scripts/generate_3d_asset.py --image ./inputs/dollface_isolated.png --export-splat --texture-mode opt \
    --output-dir ./exports/3d/

# Audio: Stable Audio Open (≤47 s) or MusicGen (≤30 s); --bpm/--bars set the length, --stems adds Demucs stems
python scripts/generate_audio.py --engine stable-audio --prompt "dark ambient drone, rain on metal" --duration 40
python scripts/generate_audio.py --engine musicgen --prompt "boom bap beat, dusty drums" --bpm 90 --bars 8 --stems
python scripts/separate_stems.py --audio ./exports/audio/beat.flac --output-dir ./exports/stems/

# Foley: MMAudio watches the clip and writes <output>.mp4 with sound + <output>.flac
python scripts/add_foley.py --video ./exports/video/shot_01.mp4 --prompt "toy footsteps, water splash" \
    --output ./exports/video/shot_01_foley.mp4

# Blender previz → video; brand restyle
python scripts/render_blender_video.py --depth-frames ./blender_out/depth/ \
    --normal-frames ./blender_out/normal/ --prompt "cinematic 90s vinyl doll, neon water splash" \
    --frames 120 --fps 24 --output ./exports/video/previz_shot_01.mp4
python scripts/run_brand_stylizer.py --input-dir ./inputs/concepts/ \
    --lora "latex_vinyl_v2.safetensors:0.8" --ip-adapter-weight 0.65 --denoise 0.55 \
    --prompt "hyper-gloss black latex outfit, molded toy seam details" --batch-count 4 --output-dir ./exports/stylized/

# LivePortrait (on the pod): source_doll.png + driving_monologue.mp4 in /workspace/ComfyUI/input
python scripts/run_stylized_liveportrait.py
```

Notes:

- **TRELLIS is CUDA-only.** Pointed at a Mac/MPS server, the CLI exits and asks for the RunPod URL. TRELLIS
  reads its attention backend when ComfyUI starts (`SPARSE_ATTN_BACKEND`, set by `start_comfy.sh` from
  `check_trellis.py`). The CLI only picks a loader option the server offers.
- **Splats:** `--export-splat` downloads `<image>_trellis_<seed>.ply` next to the `.glb`. `--texture-mode`
  (`fast` / `opt`) only changes the `.glb` texture bake, not the splat. The node doesn't report the `.ply`
  in `/history`, so the CLI fetches it from `output/<job>/<job>.ply`.
- **MusicGen** catches its own errors and returns silence; the CLI reads the node's info output and fails
  loudly. `--bpm` is a prompt hint, not a tempo lock.
- **MMAudio** is trained on 8 s clips; run longer edits per shot. The muxed MP4 keeps the source frame rate.
- Depth passes can be 16-bit PNG, 8-bit PNG or EXR. They're normalised over the whole sequence and inverted
  to near = white (`--no-invert-depth` if already converted).

## NumPy pin

NumPy is pinned to `>=1.26.0,<2.0.0` (`pyproject.toml`, `requirements.txt`, `constraints.txt`). torch 2.8,
onnxruntime-gpu and insightface are built against the NumPy 1.x ABI. The RunPod scripts put the pin, plus the
installed torch/onnxruntime-gpu versions, into `PIP_CONSTRAINT` for every install.

## Fresh GPU box

```bash
git clone https://github.com/hiddenbesidesone/aether-fx-engine.git /workspace/aether-fx-engine
cd /workspace/aether-fx-engine
./scripts/deploy_cloud.sh            # ComfyUI + all manifest nodes (safe installer), then starts on :8188
```

Models aren't tracked in git; they go in `$COMFY_DIR/models/` (see `scripts/runpod/download_models.sh`).

## Tests

```bash
pip install -e ".[dev,exr]" && pytest     # CLIs run against an in-process mock ComfyUI
```

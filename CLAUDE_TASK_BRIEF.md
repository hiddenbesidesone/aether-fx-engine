# Engineering Brief: Multi-Workflow Expansion & Environment Architecture

## 1. Context & objectives

aether-fx-engine orchestrates ComfyUI workflows for 3D kitbash modeling, stylized character
generation, high-gloss brand imagery, and Blender-driven video diffusion.

| Environment | Spec | Role |
|---|---|---|
| RunPod | RTX PRO 6000, CUDA 12.8, Ubuntu 24.04 | Heavy compute: video diffusion, large batches, CUDA-only 3D extraction |
| Mac mini | Apple Silicon, 48 GB unified memory, PyTorch `mps` | Blender workstation, local ComfyUI for prototyping, remote orchestration |

## 2. Dependency fix

`rembg` upgraded numpy 1.26.4 → 2.x on RunPod. torch 2.8, onnxruntime-gpu 1.26 and insightface
are compiled against the NumPy 1.x C-API and fail with `_ARRAY_API` import errors on 2.x.

- Pin `numpy>=1.26.0,<2.0.0` everywhere (pyproject, requirements, setup scripts).
- `src/aether_engine/env_check.py` verifies numpy is 1.26.x and reports CUDA vs MPS.

## 3. Modules

| Module | File | Purpose |
|---|---|---|
| A | `src/aether_engine/client.py` | HTTP + WebSocket client: `upload_image`, `queue_prompt`, `track_execution`, `get_output_files` |
| B | `scripts/generate_3d_asset.py` | 2D concept → .glb (TRELLIS or Hunyuan3D-2), 1:1 framing with 10% padding |
| C | `scripts/render_blender_video.py` | Blender depth/normal passes → multi-ControlNet video diffusion → MP4 |
| D | `scripts/run_brand_stylizer.py` | SDXL + LoRA stack + IP-Adapter + depth ControlNet batch restyling |

## 4. Dual-platform rules

- Every CLI takes `--comfy-url` (local, SSH tunnel, or `https://<pod-id>-8188.proxy.runpod.net`).
- Local device resolution: cuda → mps → cpu (`env_check.get_torch_device()`).
- Jobs that need CUDA-only extensions (TRELLIS spconv/flash-attn) refuse non-CUDA servers with a
  message pointing at the RunPod URL.

## 5. Definition of done

- [x] `pyproject.toml` pins `numpy>=1.26.0,<2.0.0` (also requirements.txt, constraints.txt via `PIP_CONSTRAINT` in deploy)
- [x] `client.py` and `payload_builder.py` with WebSocket monitoring and error decoding
- [x] Non-null API templates in `workflows/templates/`
- [x] Three CLIs parse/validate args, build payloads, and stream live progress

## 6. Implementation notes

- Templates address nodes by `_meta.title`, not numeric id, so they can be re-exported from the
  editor as long as titles are kept.
- Before queueing, the CLIs compare the payload against the server's `/object_info` and list
  missing node packs, missing required inputs, and model filenames the server doesn't have.
- Brief deviations: IP-Adapter uses `IPAdapterAdvanced` (`IPAdapterApply` was removed from
  IPAdapter_plus); video uses AnimateDiff (SD1.5) because it supports the depth+normal
  multi-ControlNet route with existing nodes; Wan/LTX would need a separate template.

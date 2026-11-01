# RunPod ComfyUI LivePortrait: The Survival Guide

This document outlines the essential quirks, environment variables, and specific library versions required to run the LivePortrait pipeline successfully on a RunPod instance (PyTorch 2.8.0 / CUDA 12.8).

## 1. The Ephemeral Root Quirk (InsightFace Models)

**The Problem:** InsightFace hardcodes its model directory to `~/.insightface/models/` (which resolves to `/root/` on RunPod). Because `/root/` is wiped every time you start a new pod, ComfyUI will attempt to redownload the models or fail entirely if they are missing.
**The Fix:** You must keep the `buffalo_l` models inside your persistent `/workspace` volume and dynamically symlink them to `/root/` every time the pod starts.

## 2. The ONNX / CUDA Version Trap (The 70-Minute Render Bug)

**The Problem:** Running a standard `pip install onnxruntime-gpu` will fetch the latest version (1.27+). These newer versions default to **CUDA 13** and look for `libcublasLt.so.13`.
Because standard RunPod PyTorch 2.8.0 containers run **CUDA 12.8**, the `.so.13` library is missing. Instead of crashing, ONNX silently drops CUDA support and falls back to the CPU, increasing a 10-second face-detection step to over an hour.

**The Fix:** You must strictly pin the ONNX runtime to the last version built for CUDA 12 + cuDNN 9:
`pip install onnxruntime-gpu==1.26.0`

## 3. The Dynamic Library Linking Quirk

**The Problem:** Even with the correct `onnxruntime-gpu` version installed in the virtual environment, the system's dynamic linker doesn't know where the virtual environment's NVIDIA libraries are located.
**The Fix:** You must map the venv's `/nvidia/*/lib` paths into `/etc/ld.so.conf.d/` and run `ldconfig` so ONNX can find cuDNN and cuBLAS.

## 4. ComfyUI Workflow Quirks (LivePortrait)

* **Single Frame Collapse:** If your output video is only 1 frame long, check the `LivePortraitProcess` node in your workflow JSON. The `relative_motion_mode` must be set to `"relative"`. Using `"source_video_smoothed"` currently causes a bug that collapses the video generation.

* **API Timing:** ComfyUI takes \~10–15 seconds to fully bind to port `8188`. Always poll the `/system_stats` endpoint before blindly firing off a workflow via the API.

## The "Golden" 1-Liner for New Pods

Run this single command immediately after starting a new pod. It automatically handles the InsightFace symlink and correctly maps the CUDA 12 libraries to the system linker without having to reinstall ONNX:

```
mkdir -p /root/.insightface/models && ln -sfn "$(find /workspace -type d -name "buffalo_l" | head -n 1)" /root/.insightface/models/buffalo_l && /workspace/ComfyUI/venv/bin/python -c "import site, glob; print('\n'.join(glob.glob(site.getsitepackages()[0] + '/nvidia/*/lib')))" > /etc/ld.so.conf.d/nvidia-venv.conf && ldconfig

```

### How to Verify the GPU is Active

If you ever suspect the render is running too slowly, run this Python snippet to ensure the CUDA provider is active. If it says `CPUExecutionProvider`, the environment is broken.

```
import onnxruntime as ort
import glob

# Find your local model
model = glob.glob('/root/.insightface/models/buffalo_l/*.onnx')[0]
sess = ort.InferenceSession(model, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])

print('Active Provider:', sess.get_providers()[0])
# Expected Output: Active Provider: CUDAExecutionProvider

```
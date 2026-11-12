# SYSTEM CONTEXT & GOAL

You are continuing the configuration of a RunPod instance running ComfyUI. The user has already set up basic audio generation tools. The new objective is to install custom nodes that bridge audio and video, allowing for audio-reactive animations, video-to-audio Foley (sound effects), and final MP4 video multiplexing.

Your objective is to clone these specific video/audio repositories and securely install their Python dependencies within the ComfyUI environment.

## 1. Environment Verification

1. Ensure you are operating within the ComfyUI installation directory, typically `/workspace/ComfyUI` on RunPod.
2. Ensure you are using the correct Python virtual environment (if one is active, e.g., `/workspace/venv`).
3. Verify that `ffmpeg` is installed (`ffmpeg -version`), as it is strictly required by the VideoHelperSuite for merging audio and video tracks. If missing, install it via `apt-get install -y ffmpeg`.
4. Change directory to `/workspace/ComfyUI/custom_nodes`.

## 2. Install Custom Nodes

Execute the following clones in the `/workspace/ComfyUI/custom_nodes` directory:

**A. VideoHelperSuite (VHS)**
Essential for compiling image batches and audio tensors into synchronized MP4 files.
```bash
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
```

**B. Yvann Audio-Reactive Nodes**
Extracts frequency data and beat transients to drive ControlNet, AnimateDiff, and parameter morphing.
```bash
git clone https://github.com/yvann-ba/ComfyUI_Yvann-Nodes
```

**C. MMAudio (by kijai)**
Analyzes video inputs to generate synchronized ambient soundscapes and Foley/SFX.
```bash
git clone https://github.com/kijai/ComfyUI-MMAudio
```

## 3. Install Python Dependencies

Navigate into each newly cloned directory and install their specific requirements. 

```bash
cd /workspace/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite
pip install -r requirements.txt

cd /workspace/ComfyUI/custom_nodes/ComfyUI_Yvann-Nodes
pip install -r requirements.txt

cd /workspace/ComfyUI/custom_nodes/ComfyUI-MMAudio
pip install -r requirements.txt
```

*Crucial Check: During the MMAudio installation, ensure that no packages attempt to overwrite or downgrade the system's `torch` or `torchaudio` versions to CPU variants. They must remain compatible with the installed CUDA drivers.*

## 4. Prepare MMAudio Model Directory

MMAudio requires specific model weights. Create the target directory so the user can easily place the weights later:

```bash
mkdir -p /workspace/ComfyUI/models/mmaudio
```

## 5. Verification

1. Verify that all nodes were cloned and dependencies installed without breaking the existing ComfyUI environment.
2. Provide a summary of the newly installed tools.
3. Remind the user that a ComfyUI service restart is required for the UI to recognize these new nodes.
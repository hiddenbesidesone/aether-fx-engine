# SYSTEM CONTEXT & GOAL
You are configuring a RunPod instance running ComfyUI to support advanced AI audio generation and processing. The user wants to generate hip-hop beats and ambient soundscapes using Stable Audio Open and Meta MusicGen, and then separate the outputs into stems using Demucs. 

Your objective is to install the necessary system dependencies, clone the correct custom nodes into the ComfyUI workspace, and resolve any Python requirements.

## 1. Environment Verification
1. Locate the ComfyUI installation directory. On RunPod, this is typically located at `/workspace/ComfyUI`. 
2. Verify if a Python virtual environment is active (often at `/workspace/venv`). If it is, ensure all `pip` commands are routed through this environment.
3. Change your working directory to `/workspace/ComfyUI/custom_nodes`.

## 2. System Dependencies
Audio processing packages require `ffmpeg`.
1. Check if `ffmpeg` is installed by running `ffmpeg -version`.
2. If it is missing, install it using the system package manager:
   ```bash
   apt-get update && apt-get install -y ffmpeg
   ```

## 3. Install Custom Nodes
Execute the following commands within the `/workspace/ComfyUI/custom_nodes` directory to clone the required repositories:

**A. Audio Separation (Demucs)**
Used for post-generation stem splitting.
```bash
git clone https://github.com/christian-byrne/audio-separation-nodes-comfyui
```

**B. MusicGen (HuggingFace Integration)**
Used for structured, BPM-locked hip-hop beats.
```bash
git clone https://github.com/ebrinz/ComfyUI-MusicGen-HF
```

## 4. Install Python Dependencies
Navigate into each newly cloned directory and install their requirements. *Note: Ensure you are using the correct pip environment for ComfyUI.*

```bash
cd /workspace/ComfyUI/custom_nodes/audio-separation-nodes-comfyui
pip install -r requirements.txt

cd /workspace/ComfyUI/custom_nodes/ComfyUI-MusicGen-HF
pip install -r requirements.txt
```
*Crucial Check: Ensure `torchaudio` is installed and matches the existing PyTorch CUDA version already installed in the ComfyUI environment. Do not accidentally downgrade PyTorch to a CPU version.*

## 5. Prepare Model Directories
Ensure the following directories exist so the user can easily upload or download model weights later:
```bash
mkdir -p /workspace/ComfyUI/models/checkpoints
mkdir -p /workspace/ComfyUI/models/audio_checkpoints 
```

## 6. Verification and Restart
1. Verify that the nodes were cloned successfully and no catastrophic dependency conflicts occurred.
2. Provide a summary of the installed paths. 
3. (Optional) If you have access to the ComfyUI service manager, restart the ComfyUI service to load the new nodes, or instruct the user to restart their RunPod pod.
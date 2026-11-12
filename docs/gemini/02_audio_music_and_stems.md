# Music + soundscapes + stems (Stable Audio Open, MusicGen, Demucs) on RunPod — guide for Gemini

> **How to use this file:** paste the whole thing into Gemini and say *"Walk me through this one step at a
> time. I'll paste the terminal output after each step."* Gemini: please follow the steps in order, give me
> one step at a time, and wait for my output before moving on.

---

## Context for Gemini (read first)

I'm running ComfyUI on a **RunPod GPU pod** and working in the **JupyterLab terminal**. My repo,
`aether-fx-engine`, has scripts for three audio jobs:

| Job | Engine | CLI |
|---|---|---|
| Ambient soundscapes, textures, loops (up to 47 s) | **Stable Audio Open 1.0**, built into ComfyUI, no node pack needed | `scripts/generate_audio.py --engine stable-audio` |
| Hip-hop beats at a set tempo (up to 30 s) | **Meta MusicGen**, node pack `ComfyUI-MusicGen-HF` | `scripts/generate_audio.py --engine musicgen --bpm 90 --bars 8` |
| Split any track into bass / drums / other / vocals | **Hybrid Demucs**, node pack `audio-separation-nodes-comfyui` | `scripts/separate_stems.py`, or `--stems` on `generate_audio.py` |

**Status:** built and tested against a fake server only. **This is the first real run.**

What's already on the pod and working: ComfyUI plus a **LivePortrait** workflow. LivePortrait depends on
`onnxruntime-gpu==1.26.0` (CUDA 12) and torch 2.8 / CUDA 12.8. **Don't break that.**

### Rules for this install (important)

1. Install node packs **only** through `scripts/runpod/install_audio_video.sh` (it calls
   `safe_node_install.sh`). It drops `torch`/`torchaudio`/`onnxruntime` lines from each pack's
   `requirements.txt` and pins the installed versions. A plain `pip install -r requirements.txt` can replace
   the CUDA torch with a different build.
2. **torchaudio** must match torch exactly (for example torch 2.8.0+cu128 → torchaudio 2.8.0 from the cu128
   index). The script handles this. Don't `pip install torchaudio` by hand.
3. ComfyUI's Python is `/workspace/ComfyUI/venv/bin/python`. `/root` is wiped when the pod restarts and
   `/workspace` persists; the scripts point the model caches (`TORCH_HOME`, `HF_HOME`) at `/workspace/.cache`.

---

## Step 1 — Check the pod and update the repo

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv
/workspace/ComfyUI/venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
cd /workspace
[ -d aether-fx-engine ] || git clone https://github.com/hiddenbesidesone/aether-fx-engine.git
cd /workspace/aether-fx-engine && git fetch origin && git checkout feature/multi-workflow-engine && git pull
```

**Expected:** a GPU, a torch `2.8.x+cu128` line, `True`, and the repo on `feature/multi-workflow-engine`.

## Step 2 — Install the audio node packs

```bash
cd /workspace/aether-fx-engine
bash scripts/runpod/install_audio_video.sh audio 2>&1 | tee /workspace/install_audio.log
```

What it does: installs `ffmpeg` if it's missing, and installs `torchaudio` to match torch. Then it clones and
installs `audio-separation-nodes-comfyui` and `ComfyUI-MusicGen-HF`, creates the model folders, and repairs
`onnxruntime-gpu` if anything disturbed it.

**Expected ending:** `[✓] onnxruntime-gpu==1.26.0` and `[✓] done.` Paste any `[!]` lines to Gemini.

## Step 3 — Download Stable Audio Open (gated model, one-time)

Stable Audio Open needs a free Hugging Face account and a license click:

1. Log in at huggingface.co, open **https://huggingface.co/stabilityai/stable-audio-open-1.0**, and accept the
   license.
2. Create a **read** token at **https://huggingface.co/settings/tokens**.
3. On the pod:

```bash
cd /workspace/aether-fx-engine
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx      # your token; don't commit it anywhere
bash scripts/runpod/download_models.sh stable-audio
```

**Expected:** two files arrive, `models/checkpoints/stable-audio-open-1.0.safetensors` (~5 GB) and
`models/text_encoders/t5-base.safetensors` (~0.9 GB). A `401`/`403` error means the license isn't accepted
or the token is wrong.

MusicGen and Demucs need no manual download. They fetch their weights on first use: MusicGen goes to
`models/musicgen/` (medium is ~8 GB) and Demucs to `/workspace/.cache/torch`.

## Step 4 — Restart ComfyUI

```bash
bash /workspace/aether-fx-engine/scripts/runpod/start_comfy.sh
```

**Expected:** `[✓] ComfyUI is up on :8188`. If it prints `some custom nodes failed to import`, run
`grep -B2 -A20 -i "MusicGen\|audio-separation" /workspace/comfyui.log | head -80` and paste the output.

*Note:* the Demucs node hides its own import errors. If it fails to load, it just doesn't appear, and the CLI
later reports `node class 'AudioSeparation' is not installed`. In that case run
`/workspace/ComfyUI/venv/bin/python -c "from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB_PLUS; print('ok')"`
and paste the output.

## Step 5 — Set up the client CLI (one time; skip if already done for another guide)

```bash
python3 -m venv /workspace/aether-venv          # use python3.12 if python3 is 3.13+
/workspace/aether-venv/bin/pip install -q -e /workspace/aether-fx-engine
mkdir -p /workspace/exports
```

## Step 6 — Generate

```bash
cd /workspace/aether-fx-engine
A=/workspace/aether-venv/bin/python

# Ambient soundscape: Stable Audio Open
$A scripts/generate_audio.py --engine stable-audio \
    --prompt "dark ambient drone, rain on a metal roof, distant thunder, cinematic" --duration 40 \
    --output-dir /workspace/exports/audio/

# Hip-hop beat at 90 BPM, 8 bars (= 21.3 s): MusicGen; first run downloads the model
$A scripts/generate_audio.py --engine musicgen \
    --prompt "boom bap hip-hop beat, dusty vinyl drums, deep upright bass, jazzy piano chops" \
    --bpm 90 --bars 8 --stems --output-dir /workspace/exports/audio/

# Split an existing track into stems (upload it to /workspace/aether-fx-engine/inputs first)
$A scripts/separate_stems.py --audio inputs/my_track.wav --output-dir /workspace/exports/stems/
```

**Expected:** `[✓] track  /workspace/exports/audio/musicgen_<seed>.flac`, plus with `--stems` four lines like
`[✓] drums  …_drums.flac`. Download them from the JupyterLab file browser.

Options worth knowing (full list: `--help`):

- `--bpm N` appends "N BPM" to the prompt. MusicGen and Stable Audio both respond to it, but **neither locks
  the tempo exactly**, so check the grid in your DAW. `--bars N` sets the length to N bars of 4/4 at that BPM.
- `--name my_beat` names the output files; `--seed N` makes a run repeatable.
- Stable Audio: `--steps 50`, `--cfg 5`, `--negative "vocals, distortion"`.
- MusicGen: `--model-size small|medium|large` (small ≈ 2.4 GB, large ≈ 14 GB download and noticeably slower), `--cfg 3`.

| Symptom | Likely cause / fix |
|---|---|
| `checkpoint ckpt_name='stable-audio-open-1.0.safetensors' not available` | Step 3 isn't done, or the file landed under a different name. Run `ls /workspace/ComfyUI/models/checkpoints`. |
| `MusicGen failed (the node returned silence): Error …` | The node catches its own errors and returns silence. The message after `Error` is the real problem (often out of memory: try `--model-size small`). |
| `node class 'HuggingFaceMusicGen' is not installed` | Import failure. Check `/workspace/comfyui.log` (Step 4). |
| Stems sound phasey or have artefacts | Try `separate_stems.py --chunk-length 20`. Longer windows give cleaner results but use more VRAM. |

## Running from the Mac instead (optional)

```bash
python scripts/generate_audio.py --engine musicgen --prompt "..." --bpm 90 --bars 8 \
    --comfy-url https://<POD_ID>-8188.proxy.runpod.net --output-dir ./exports/audio/
```

## Notes on how it works (for Gemini)

- Templates: `workflows/templates/stable_audio_api.json`, `musicgen_api.json`, `stem_split_api.json`. The CLIs
  address nodes by title.
- Stable Audio graph: `CheckpointLoaderSimple` + `CLIPLoader(type=stable_audio, t5-base)` →
  `ConditioningStableAudio(seconds_total)` + `EmptyLatentAudio(seconds)` → `KSampler(dpmpp_3m_sde,
  exponential)` → `VAEDecodeAudio` → `SaveAudio` (FLAC).
- `--stems` appends `AudioSeparation` plus four `SaveAudio` nodes to the same job, so you get one queue entry
  and one download.
- Outputs on the server are under `ComfyUI/output/AetherFX/audio/` and `…/stems/`.

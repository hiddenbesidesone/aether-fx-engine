# ComfyUI workflow backlog

What's left to build or test in aether-fx-engine, gathered from the docs (README, `docs/comfyui-workflow-ideas`,
`CLAUDE_TASK_BRIEF.md`, the Police Bike brief) plus recommendations from what's already built. Updated 2026-11-25.

## Verified on a real GPU (done)

LivePortrait stylised · TRELLIS image → mesh + splat (single view) · Audio: Stable Audio, MusicGen, Demucs (02) ·
Foley MMAudio + Yvann Text-to-Video (03) · Police Bike W2 world, Wan VACE (05) · **C2 start/end frame → 1080p24 video
(Wan 2.2 + SeedVR2 + RIFE), which also covers C3 upscaling** (`render_flf_video.py`, SOP 02) · W3 composite preview (local).

## A. Built, but never run on a GPU

| Workflow | Entry point | Notes |
|---|---|---|
| TRELLIS **multi-view** (4–6 views → one asset) | `generate_3d_asset.py --image a.png b.png …` | The user's main way of working (Gemini views). Risk: BiRefNet on a batch. ~$0.30 test |
| Blender previz → AnimateDiff video (guide 04) | `render_blender_video.py` | Older SD1.5 route; Police Bike uses 05 instead. Test only if wanted for something else |
| Brand stylizer (SDXL + LoRA + IP-Adapter + depth) | `run_brand_stylizer.py` | Never run; needs a LoRA/brand reference to test against |
| Hunyuan3D-2 (alternative 3D engine) | `generate_3d_asset.py --engine hunyuan` | No install guide yet. Compare with TRELLIS on the same inputs |
| Yvann **Images-to-Video** and **Video-to-Video** | Yvann example workflows | Install is scripted; needs extra ControlNet / IP-Adapter models. V2V = restyle real footage to the beat |

## B. Mentioned in the docs, not built yet

| Workflow | Source | Notes |
|---|---|---|
| Police Bike **W1 rider** (SeedVR2 upscale + matte + despill) | `brief.md`, guide 05 Step 10 | Next up once the rider clips are handed over (`next_steps.md` step 5) |
| Police Bike later items: IC-Light relight, unifying tile pass, rider stylisation, `env` as a second control, prompt crossfades, audio-driven cuts | `brief.md` "Later" | After the first finished shot |
| **Blender-controlled video for show-reel shots** ("Seedance" idea) | `comfyui-workflow-ideas` #1 | W2 (Blender depth → VACE) is already this pattern, open-source. Seedance itself is a paid API model; ComfyUI has API nodes for some of these services, so a comparison is possible |
| **Concept-art front end for 3D**: FLUX/SDXL + ControlNet/LoRA → background removal → TRELLIS | `comfyui-workflow-ideas` #2 | Would generate the multi-view images inside ComfyUI instead of Gemini |
| **Image-to-video** (general) | `comfyui-workflow-ideas` #3 | See C2: first/last-frame image-to-video |
| Scene/person splats → Blender camera paths | session log | **Parked by the user**: only if something works well out of the box |

## C. Recommended (builds on what's already working)

| # | Workflow | Why | Reuses |
|---|---|---|---|
| C1 | **Sound pass CLI**: a folder of shots → Foley per shot (with and without a prompt) + a Stable Audio stereo bed → a rough stereo mix per shot | Foley is the tool the user expects to use most; this automates what was done by hand on 2026-11-24 | `add_foley.py`, `generate_audio.py`, ffmpeg mixing |
| C2 ✅ | **First/last-frame image-to-video** (Wan 2.2 FLF2V; built 2026-11-25) | The Police Bike rider clips are made with start + end frame = the home pose; doing this in ComfyUI keeps it in-house and repeatable. Also covers ideas #3 | Wan models already on the pod workflow |
| C3 ½ | **Standalone video upscaler** (SeedVR2). Inside C2 now; a standalone CLI is still to do | Needed for W1 and the Police Bike finals anyway; useful on its own | The W1 work |
| C4 | **Real footage → restyled world**: video → depth (DepthAnythingV2, already in `custom_nodes.json`) → W2 VACE | Uses the proven W2 pipeline on any filmed or AI clip, not just Blender greyboxes | `render_world_vace.py` |
| C5 | **Wan 2.2 vs 2.1** for W2 | A possible quality jump for the same layout control | `render_world_vace.py` templates |

## Suggested order

1. Police Bike, per `docs/projects/police-bike/next_steps.md` (steps 1, 3, 5, 7 are ComfyUI work).
2. **C1 sound pass**: quick to build and immediately useful.
3. **TRELLIS multi-view** test (A): cheap, and it's how the user actually works.
4. **C2 first/last-frame image-to-video**, then **C3 upscaler** (they share models and support W1).
5. The rest when a project needs it.

# Police Bike — ComfyUI workflows brief

For building the ComfyUI side of the Police Bike music video. Written 2026-11-18 from the Blender
side (blender-lab, worktree `blender-lab-police-bike`). Self-contained: hand it to whoever builds the workflows.

> Copied into aether-fx-engine on 2026-11-19. What's built for it, and how to run it:
> `docs/gemini/05_police_bike_comfyui.md`.

## The film in one paragraph

A music video. A policeman on a police motorcycle, seen **side-on, locked at the centre of the frame,
for the whole film**. He never leaves the centre; only the world around him changes, scrolling past
as he rides (like a Geometry Dash level as a film). The camera's only move is zooming: pulling far back
to show a huge world with him tiny at the centre, or pushing in. The rider is **real AI-video footage**
(a photo of a real policeman animated with image-to-video, on green screen). The worlds are
**AI video, controlled by a Blender greybox**: a simple grey 3D scene (road, buildings) that scrolls and
zooms in time with the edit, so the AI paints the style but follows our layout, speed and camera.

## What Blender delivers (per shot, PNG sequences, 24 fps, same frame count, frame N = frame N)

| File | What it is | Used for |
| --- | --- | --- |
| `depth_####.png` | Depth of the world **without the rider**, greyscale, white = near, black = far/sky | The main control input for the world generation |
| `env_####.png` | The grey world without the rider, shaded | Optional second control (edges/lineart via a preprocessor, or low-strength v2v) |
| `matte_####.png` | White where the rider is | Compositing; optional "keep out" mask |
| `shadow_####.png` | The rider's shadow alone on the ground, white = no shadow | Multiplied over the AI world in comp |
| `beauty_####.png` | Greybox + rider + shadow | Reference only: what the shot should look like |

Preview resolution 960x540 (16:9); finals at 1920x1080 or above. Shots so far: `loop` (89 frames,
seamless: frame 90 = frame 1) and `zoom` (267 frames, camera pulls from 5.5 m to 160 m).

## Hardware

The artist's machine is a 2019 Intel Mac: these models will not run on it. Run ComfyUI on a rented GPU
(the artist has a RunPod account and network volume; a 24-48 GB card, e.g. RTX 4090 / A6000 / L40S /
RTX PRO 6000, depending on the model size).

---

## Workflow 1: Rider clips: upscale + matte

**Input:** a green-screen rider clip (mp4, 24 fps, 1280x720 today; every clip starts and ends on the same
"home" frame so clips join, see below).
**Output:** an RGBA PNG sequence (straight alpha), same frame count, same frame timing, upscaled.

1. **Upscale** with a temporally stable video upscaler, the same one, same settings, for every clip, so
   all clips share texture. Suggested: SeedVR2 (`ComfyUI-SeedVR2_VideoUpscaler`). Target: 1920x1080 at least
   (the bike must stay sharp at ~1150 px wide in the closest framing), 3840x2160 if affordable.
   No creative/high-denoise upscalers: his face, the bike's livery and the panniers' text must not change
   between clips.
2. **Matte.** Video matting so the edge doesn't flicker: try MatAnyone (needs a first-frame mask, e.g. from
   SAM2) and BiRefNet (per frame); keep whichever flickers least on the wheel spokes, the windscreen, the
   helmet visor and the beacon pole. The background is a flat green studio with a soft floor shadow under
   the wheels: the floor shadow must **not** be in the matte.
3. **Despill** green from the edges and the see-through parts (spokes, windscreen) **without** turning the
   hi-vis jacket and bike livery yellow: they are genuinely yellow-green (the jacket is roughly RGB 140/180/105).
4. Save RGBA PNG, frame numbers matching the input.

Batch: a folder of clips in, a folder per clip out.

## Workflow 2: The world (the main one): depth-controlled video-to-video

**Inputs:** `depth_####.png` (required), optionally `env_####.png`, a text prompt per section, optionally
a style reference image. **Output:** a PNG sequence of the AI world, **same frame count and the same frame
for frame** as the input (no trimming, no dropped or added frames, no frame interpolation, no reframing or
cropping; the aspect stays 16:9).

- Suggested model: **Wan 2.1 VACE** (14B for quality, 1.3B for fast tests) or **Wan 2.2 Fun Control/VACE**.
  VACE takes a control video (depth), optional masks and optional reference images.
  Kijai's `ComfyUI-WanVideoWrapper` or the native `WanVaceToVideo` nodes. (Older route, more flicker:
  AnimateDiff + ControlNet Depth.)
- Wan works natively at 16 fps and in chunks of 81 frames. Feed our 24 fps frames 1:1 anyway: the control
  video sets the motion, so the output played at 24 fps still matches our road speed. Don't resample to 16 fps.
- **Longer than one chunk:** continue across chunks with overlap (use the last ~8-16 generated frames to
  start the next chunk, or the wrapper's context windows) so there is no visible jump at chunk borders.
- **Loops:** the `loop` shot must stay seamless after generation (the last frame must lead into the first).
  Ideas: generate a few frames past the end and crossfade; or a VACE pass whose control is the end and the
  start of the clip with the middle masked, to generate a joining section.
- **The rider is not generated.** The depth has no rider in it; the AI paints the road straight through where
  he is, and Workflow 3 puts the real footage on top. Don't ask the model to draw a policeman.
- Strength settings to expose: control strength (how strictly it follows the depth), and seed (fixed per
  section, so a re-run is repeatable).
- Prompts change per music section: completely different worlds (neon city at night, watercolour forest,
  1980s synthwave grid, desert, underwater...). Allow a prompt schedule (prompt A until frame X, prompt B
  after) for transitions.
- Resolution for tests: 832x480 or 960x540; finals at 1280x720 then upscaled (same upscaler as the rider is
  ideal).

## Workflow 3: Composite (can be ComfyUI, After Effects, Resolve or Blender)

Per frame: `AI world` x `shadow` (multiply, strength adjustable) then the rider RGBA over it, placed
at exactly the position and scale given by `matte_####.png` (the Blender stage already puts him in the right
place, size and zoom; the rider sequence for a shot will be supplied rendered into frame, so a plain
overlay works).

Optional, per section: relight the rider to the world (IC-Light, using the AI frame as the light source),
and a very light unifying pass over the whole frame (low-denoise tile upscale, 0.1-0.15) so rider and
world share grain. These come later: the fundamentals are 1-3 working end to end.

## Later (not yet)

- Audio-driven: the track's beats/sections drive prompt changes, zoom keys and cuts between rider clips
  (and possibly audio-to-video models for the world). The track isn't chosen yet.
- Stylising the rider himself in some sections (pixelated, painted) with low-denoise passes on the rider
  layer only.

## First test to run (the go/no-go for the whole approach)

Take the `loop` shot's `depth_####.png` (89 frames), prompt "rainy neon city street at night, cinematic",
run Workflow 2, and check: does the road stay where our road is, does the world scroll smoothly at our
speed, is there flicker? Then the same for the `zoom` shot: does it hold up as the camera pulls back 30x?
Report what control strength and model size worked.

## The rider "home pose" (context for Workflow 1)

Every rider clip is generated (image-to-video, start + end frame mode) with the same image as its first
**and** last frame: `projects/police-bike/plates/home.png` (or its upscaled version). Then any clip can follow
any other with no jump, and the edit can cut wherever the music wants. A clip that ends in a new state
(visor down) uses its last frame as a second home image for clips in that state.

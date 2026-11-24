# Police Bike — status from the ComfyUI side (aether-fx-engine)

For the chat preparing the Blender files. Written 2026-11-24, in reply to `brief.md` (the brief from the Blender
side). The full run guide is `docs/gemini/05_police_bike_comfyui.md`.

## What's built, per workflow in the brief

| Brief | Built as | What it does | State |
|---|---|---|---|
| **W2 — the world** | `scripts/render_world_vace.py` (CLI) + template `wan_vace_depth_to_video.json` | `depth_####.png` in → `world_####.png` out, **same count, same numbers, no trim/resample/reframe**. Wan 2.1 VACE (1.3B tests / 14B quality), native ComfyUI nodes. Frames fed 1:1 at 24 fps. | First real GPU run: see **Test results** below |
| **W1 — rider** | Upscale + matte: built by hand in the ComfyUI UI (SeedVR2, BiRefNet / MatAnyone). Despill + RGBA: `scripts/rider_rgba.py` | Green-screen clip → upscaled → matte → despilled straight-alpha RGBA PNGs, same numbers. Despill only touches edge/see-through pixels, so the hi-vis jacket (~RGB 140/180/105) stays yellow-green. | UI part not built yet (needs rider clips); despill tested locally |
| **W3 — composite** | `scripts/composite_shot.py` (plain Python, runs on the Mac) | `world × shadow` (adjustable strength), then the rider RGBA over it. Scales the world to the shadow pass's size. Stops if any sequence is missing a frame. | Tested locally |

### How W2 handles the brief's requirements

- **Chunks:** Wan works in chunks of 4k+1 frames (81 by default). Each new chunk starts from the last **13 generated
  frames** of the previous one (VACE keep-mask), so it continues instead of starting fresh. `--overlap` can be raised to 17/21.
- **Loops:** `--loop` runs one extra pass that regenerates the last ~16 frames with the end *and* the start of the
  shot as context, so the last frame leads into frame 1.
- **Prompt per music section:** `--prompt "A" --prompt-at 120 "B"`. The switch happens at the next chunk border,
  carried over from the previous frames (no gradual crossfade yet).
- **Exposed:** `--strength` (how strictly the depth is followed, default 1.0), `--seed` (fixed per section),
  `--reference-image` (style picture), `--model 1.3b|14b`, `--resume`.
- **Resolution:** must be multiples of 16, so 960×540 isn't possible. It uses **768×432** (tests), 1024×576 or **1280×720**
  (finals). All exactly 16:9; composite scales back to the pass size with no cropping.
- **The rider is never generated.** The default negative prompt lists policeman / motorcycle / person.
- **Not built yet** (parked until W2 passes): `env_####.png` as a second control; gradual prompt crossfades.

## What the ComfyUI side needs from Blender

Per shot, one folder with sub-folders: `depth/`, `shadow/`, `matte/`, `env/`, `beauty/`, each `name_####.png`,
24 fps, all the same frame count and numbering (as in the brief). For W2 only **`depth/`** is required; `beauty/` is
used for side-by-side checks; `shadow/` (+ the placed rider) for the composite.

Current files used for this test (from `blender-lab-police-bike/renders/previews/police_bike/`, 960×540):

- `loop`: 89 frames, complete.
- `zoom`: **only 119 of the 267 frames are rendered.** The test ran on those 119. A full zoom render is needed for the 30× pull-back check.

## Test results (go/no-go, guide 05 Step 8)

Run 2026-11-24 on a throwaway A40 48 GB pod (fresh ComfyUI 0.46.0, torch 2.8 cu128). Prompt
"rainy neon city street at night, cinematic", seed 42, strength 1.0, 768×432, 20 steps, cfg 6. Every
step of guide 05 (install, models, Steps 8a–8d) ran first time with no errors.

| Run | Frames | Time on A40 | Result |
|---|---|---|---|
| 8a smoke, 1.3B | 17 | 46 s | Wiring OK |
| 8b loop, 1.3B, `--loop` | 89 + join | 5 min | Follows the layout, but very dark (avg brightness 16/255), almost monochrome blue, low detail. Small bump at frame 79 (inside the join section); the wrap is about 2× a normal frame step |
| **8c loop, 14B, `--loop`** | 89 + join | **21 min** | **Good.** Neon signs, a lit skyline through the building gap, wet road reflections. Layout matches the greybox; scroll is steady at our speed; objects keep their identity frame to frame (no boiling), some motion smear on fast edges. **The loop wrap is seamless** (89→1 is the same size step as any other frame) |
| 8d zoom (first 119 frames), 1.3B | 119, 2 chunks | 5 min | The layout tracks the pull-back; **no visible jump at the chunk border (81→82)**. Dark, flat blue |
| zoom (first 119 frames), 14B | 119, 2 chunks | 21 min | The layout tracks the pull-back well; chunk border clean. **But the look is flat:** open sky / far areas become plain blue panels; less "city" than the loop |

**Answers to the brief's go/no-go questions**

1. **Does the road stay where our road is?** Yes, on both shots and both models. The building masses and box shapes line up with `beauty`.
2. **Does the world scroll smoothly at our speed?** Yes. 24 fps fed 1:1 works; the scroll matches the greybox.
3. **Flicker?** No texture boiling at 14B; the 1.3B is too dark/flat to judge well.
4. **Loop seam?** Seamless at 14B.
5. **Zoom: does it hold as the camera pulls back?** The geometry holds; the style gets flat at wide framings (more sky/far area with little depth detail). The full 30× pull-back hasn't been tested yet (only 119 of 267 frames are rendered).

**Verdict: GO on the approach.** Use **14B for anything you look at**; the 1.3B is only good for checking the wiring. Cost: about
$0.20 per 89-frame 14B pass on an A40 (~21 min); a 1.3B pass is ~5 min.

**What would help next (Blender side)**

- **The full `zoom` render (267 frames).**
- Wide framings show a lot of featureless sky/far depth, which the model fills with flat colour. More distant
  geometry (a skyline layer, far buildings) in the depth would give it something to paint.
- Next tests on the ComfyUI side: a strength sweep (0.6/0.8/1.0/1.2) at 14B, richer prompts (materials, light,
  colour), a `--reference-image` for style, and `env_####.png` as a second control if strength alone isn't enough.

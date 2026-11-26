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
- `zoom`: **only 119 of the 267 frames are rendered.** `zoom.log` stops partway through frame 120 (sample 1/16), so the
  render looks interrupted rather than finished. The test ran on those 119 (~5 s, the start of the pull-back). Re-render
  frames 120–267 (all passes) for the widest part of the 30× pull-back.

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

## Update 2026-11-25: composite preview, look pass, rider clips

**Composite preview (W3, step 1): done.** `loop` with the 14B neon world × `shadow` and the rider cut from `beauty` by
`matte` (`output/comp-preview-loop/`, shadow 0.6 and 0.85). Everything lines up and the loop holds. **The big gap:** the
rider is lit for a bright daytime studio and the world is dark neon night, so he looks pasted on. Relighting the rider
(IC-Light, brief "Later") should move up to the fundamentals.

**Look pass (step 3): done**, 14B on `loop`, seed 42, on an L40S (~12 min per 89-frame pass; about 2× the A40).

| Run | Result |
|---|---|
| neon, strength 0.7, richer prompt | Brighter (avg 40/255 vs 26 before), more surface detail, a believable skyline; layout holds; seamless wrap |
| neon, strength 1.2, same prompt | **Nearly identical to 0.7**, slightly more window detail |
| watercolour forest road, 1.0 | **A completely different world works** on the same greybox: bright, painted. But the building boxes become green *boxes*, not trees. One jump around frame 8 |
| 1980s synthwave, 1.0 | Excellent: magenta grid road, setting sun, chrome blocks. One jump around frame 53 |

**What this means for the project:**

1. **Strength isn't the lever; the prompt is.** Keep `--strength 1.0` and write rich prompts: materials, light, colour,
   distance (e.g. "glowing pink and cyan signs, wet asphalt reflections, distant skyline").
2. **The greybox shapes come through in every world.** Boxes stay boxes. For organic worlds (forest, underwater), either
   block out matching shapes in Blender (tree masses, rocks), or test a lower strength (~0.5) for those sections.
3. Watch for the occasional single-frame jump (2 of 4 runs). A different seed, or re-running only that chunk, fixes it.

**New: rider clips can now be made in ComfyUI.** `scripts/render_flf_video.py` (SOP `docs/sop/02_…`): start
frame = end frame = `home.png` + a prompt ("he turns his head to the camera, nods, looks ahead again") gives a
**1920×1080, 24 fps, 5 s clip that returns to the home pose**, on green, in ~7 min (fast mode). Tested on `home.png`: the action
worked and the last frame matches the first closely. That's the brief's home-pose rule, in-house and repeatable. Fast mode matched
the 20-step quality mode on this clip. Watch faces: the 1080 upscale adds detail and can shift the face slightly.

## Update 2026-11-26: R1 (test worlds) and R3 (rider RGBA), answering `police-bike-comfyui-requests.md`

One L40S pod, ~1.75 h, **$2.04** (quote ~$3: the SeedVR2 pass was dropped, see R3). All files on the Mac, not in git.

### R1. T1–T3 on the new `loop`, then the best on `zoom`

14B, strength 1.0, seed 42, your prompts and negative (no "illustration" in T3's negative), `--loop` on `loop`. ~12 min per loop, 28 min for the zoom.

| World | Result |
|---|---|
| **T2 British parade** | **The strongest.** Real shopfronts: the chicken shop with the red backlit sign and white interior, shutters, a red phone box, flats above, a wet reflective road. **Shop identity holds across the seam**: the same shop with the same sign is in the same place at 89 → 1. The only world where the **skyline layer reads** (towers against the sky). |
| **T3 abstract game level** | Works as a graphic level: flat black, cyan outlines, cyan spikes along the ground, outlined towers. The 3D greybox flattens fine at 1.0, so no special greybox is needed. |
| **T1 night motorway** | The weakest: mostly black with sodium-orange glow and streaks. It reads as an underpass at night rather than "photographed". Needs a brighter prompt (more streetlights, lit lane markings, a visible skyline) before it's usable. |

- **Single-frame jumps:** none found. The automatic check flagged frames, but they're fast-moving foreground (a near post, the skyline gap passing), not glitches. Worth one watch of the `_x3` files.
- **`zoom` with T2** (267 frames, 4 chunks): the pull-back holds the layout, the chunk joins are clean, and **the wide end is now a night skyline** with lit windows and a row of lit shops, **not flat blue any more** (the skyline layer worked). Two things: the big flat ground in the lower half goes **almost black** at the wide end (give it lit kerbs, streetlights or road markings in the greybox, or prompt them), and the shopfronts **repeat the same chicken shop** many times along the street (vary the block widths/heights in the greybox, or use `--prompt-at` per section).

**Files** (`aether-fx-engine/output/r1-worlds/`): `loop_<world>/world_####.png` (89 frames), `loop_<world>_vs_beauty.mp4`
(world under `beauty`), `loop_<world>_x3.mp4` (loop played three times), `zoom_t2_parade/world_####.png` (267), `zoom_t2_parade_vs_beauty.mp4`.

### R3. Rider RGBA from `fixed/` ride-idle, ride-jump, ride-look-camera

**Result: use `green_key.py` + `rider_rgba.py` on the original clips, with no SeedVR2.** 744 RGBA frames, 1920×1080, same numbering
as the clips (`rider_0001.png` = the clip's first frame), straight alpha.

- **Matte: green_key beats BiRefNet.** I ran BiRefNet_HR (AI matte) on every frame. It **fills the wheels solid** (grey-green disc
  where the spokes should show the background) and leaves a faint green rim on the tyres. green_key shows the background through
  the spokes and the windscreen and keeps the hi-vis and black parts solid. MatAnyone wasn't needed. The BiRefNet mattes are kept
  in case they're useful as a garbage mask later.
- **SeedVR2: don't use it on the rider.** The clips are already 1080, so it can only re-detail at the same size. On 2 s of
  `ride-look-camera` it made the **face more specific and photographic** (sharper eye, mouth lines, stubble), which is exactly the
  identity risk. It also **garbles text** ("POLICE" → "POLIOE") and **warps the BMW roundel**. Kept as `seedvr_look_2s.mp4` for you to compare.
- **Small things left:** the flipped-up visor on top of the helmet is clear plastic, so it keeps a faint mint tint. Fast-spinning
  spokes may carry a trace of green in motion blur. Neither showed at preview size over the parade.

**Files** (`aether-fx-engine/output/r3-rider/`): `<clip>/rgba/rider_####.png` (360 / 192 / 192), `preview_<clip>.mp4` (over a T2 frame),
`seedvr_look_2s.mp4`.

### What this unlocks

- **R4 relight (IC-Light)** can start now: the RGBA is clean and T2 is the obvious first world to light him for.
- First finished shot (`next_steps` step 7): T2 `loop` world × `shadow` + the placed rider RGBA, once Blender has placed it.

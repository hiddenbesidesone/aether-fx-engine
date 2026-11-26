# SOP 06 — Blender greybox → AI world → composite

**Use this for:** a shot laid out in Blender (camera, speed, timing in a greybox) that should come out as a
painted or photographed world in any style, with a live-action or rendered subject composited on top.
Built for Police Bike (W2 + W3), but it works for any shot.
**What you get:** `world_####.png` frame for frame with the Blender render (same count, numbering and
camera), and `comp_####.png` with the shadow and subject added.

**Engine:** Wan 2.1 VACE 14B driven by the depth pass (`scripts/render_world_vace.py`) · a numpy composite
(`scripts/composite_shot.py`, Mac) · green-screen key + RGBA (`scripts/green_key.py`, `scripts/rider_rgba.py`, Mac). Tested on RunPod
2026-11-24/25. Setup, once per pod: `docs/gemini/05_police_bike_comfyui.md` Steps 1–7
(`install_audio_video.sh police-bike`, `download_models.sh wan-vace` + `wan-vace-14b`).

| Time | 14B: ~21 min per 89 frames at 768×432 on an A40, ~12 min on an L40S. 1.3B: ~5 min (wiring checks only) |
|---|---|
| Status | ✅ W2 verified (loop + zoom, seamless loop) · ✅ composite verified locally · subject keying: see step 4 |

## 1. Render the passes in Blender

One folder per shot with `depth/`, `shadow/`, `matte/`, `env/`, `beauty/`, each `name_####.png`, all the same
frame count and numbering, 24 fps. Only **depth** (white = near, subject hidden) is needed for the world.

- **Give wide framings something far away** (a skyline or far-building layer). Empty depth = flat sky in the AI world.
- **Block out the shapes you want.** The model keeps the greybox's forms: boxes stay boxes. For a forest, model
  tree and rock masses.

## 2. Render the world

```bash
python scripts/render_world_vace.py --depth-frames shots/loop/depth --model 14b --chunk 89 --loop --seed 42 \
    --prompt "rainy neon city street at night, wet asphalt reflecting pink and cyan signs, skyline, cinematic" \
    --output-dir exports/world/loop_neon
```

- **Prompts matter, strength doesn't:** 0.7 and 1.2 looked almost identical; a richer prompt changed the look a lot.
  Keep `--strength 1.0` and write the world in detail (materials, light, colour accent, "no people, no vehicles").
- `--loop` makes the last frame lead back into the first. `--chunk 89` renders an 89-frame shot in one go.
- Long shots: chunks of 81 with 13 frames of overlap; `--prompt-at FRAME TEXT` switches the world at the next chunk
  border; `--resume` continues after an interruption.
- Occasional **single-frame jumps** (2 of 4 test runs): rerun with another seed, or patch the frame in the edit.
- Start with `--frames 17 --model 1.3b` to check the wiring for ~1 min before a long 14B run.

## 3. Composite (Mac, free)

```bash
python scripts/composite_shot.py --world exports/world/loop_neon --shadow shots/loop/shadow \
    --rider rider_rgba/loop --output exports/comp/loop_neon --shadow-strength 0.85
```

World × shadow (0.85 looked right), then the subject's RGBA on top. Without `--rider` you get world × shadow only.

## 4. The subject's RGBA (keying)

**Don't cut the subject from `beauty` with Blender's `matte`.** In the first preview that gave a hard,
one-pixel matte and the green fringes of the original key (on the windscreen, the wheels, the outline). Key from
the **original green-screen clip** instead, at full resolution:

```bash
ffmpeg -i ride-idle.mp4 -start_number 1 green/ride_idle/f_%04d.png
python scripts/green_key.py --frames green/ride_idle --output matte/ride_idle --choke 1
python scripts/rider_rgba.py --frames green/ride_idle --matte matte/ride_idle \
    --output rider_rgba/ride_idle --edge 5 --tolerance 0.45
```

1. **Matte:** `green_key.py` (Mac, free, tested 2026-11-25 on `ride-idle`) keys the screen in shadow as well as in
   light, and keeps hi-vis yellow-green and black parts solid. For finals, the AI matte from W1 (BiRefNet /
   MatAnyone in ComfyUI) can replace it. `--choke 1` pulls the edge in by a pixel if a thin rim remains.
2. **RGBA:** `rider_rgba.py` takes the screen colour back out of see-through pixels (windscreen, spokes) and
   despills the edge.
3. Blender places the RGBA in frame (the brief's step) and renders `rider/` per shot.

Watch for watermarks in generated source clips (the library clips have a sparkle in the bottom-right corner): it
keys as subject. Use the project's `fixed/` versions, or crop it out.

Tested on the Police Bike clips (2026-11-26): **green_key beats BiRefNet_HR** (BiRefNet fills wheels solid and leaves a green
rim). **Don't run SeedVR2 on 1080 footage of a person**: at the same size it only re-details, and it made the face more photographic,
garbled text and warped logos. On a 1080 clip, rider_rgba takes ~18 s/frame on the Mac (the edge filter is slow), so for long clips
run it on a pod's CPUs in parallel (744 frames took ~2 min with 24 workers).

Remaining weak spot: fast-spinning spokes mix with the screen; only an AI matte gets them fully clean. Relight the
subject (IC-Light, not built yet) when the world's light differs a lot from the green-screen light.

## 5. Check

- The road and building masses sit where the greybox has them (compare against `beauty`).
- The loop: play it ×3 (`ffmpeg -stream_loop 2 …`) and watch the cut.
- The composite: the shadow lands under the subject, no green rim on the subject, no jumps.

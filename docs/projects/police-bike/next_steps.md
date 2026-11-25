# Police Bike — recommended next steps (from the ComfyUI side)

Written 2026-11-25 by the aether-fx-engine (ComfyUI) chat for the Police Bike project chat. Read with
`aether_side_status.md` (what's built + the go/no-go results) and `brief.md`.

**How we work together:** the project chat decides and prepares the files; the ComfyUI side builds and tests
workflows on a throwaway RunPod GPU and reports back. Come back to the ComfyUI side for any step marked
**[ComfyUI]**, or when you need a new test or workflow.

## Where things stand

- **W2 (world) passed the go/no-go** with Wan 2.1 VACE **14B**: it follows the greybox, scrolls smoothly at your
  speed, has no flicker, and the loop is seamless. Weak spot: wide framings go flat blue.
- W1 (rider) and W3 (composite) are built as scripts but haven't been run on real footage yet.
- Timing on an A40 (48 GB, $0.59/hr): 14B ≈ **21 min per 89 frames at 768×432** (about $0.20). The 1.3B is only for wiring checks.

## Next steps, in order

| # | Who | Step | Needs from the project | Output |
|---|---|---|---|---|
| 1 | **[ComfyUI]** | **Composite preview of `loop`**: the 14B neon world × `shadow`, with the rider cut from `beauty` by `matte`. Free, runs on the Mac. | Nothing (uses the existing preview passes) | `loop` as an actual shot, to judge the overall look |
| 2 | **Blender** | **Re-render `zoom` frames 120–267** (all five passes). The preview render stopped partway through frame 120. While doing it, consider **distant geometry** (a skyline or far-building layer) for the wide framings, so the depth isn't mostly empty sky. | — | The full 267-frame `zoom` |
| 3 | **[ComfyUI]** | **Look pass at 14B on `loop`** (~$1–1.5): strength 0.7 / 1.0 / 1.2, plus 2–3 other worlds, with an optional style reference image. Then the full `zoom` at the best setting. | **The list of worlds per music section** (a short prompt each) and any **style reference images** | A recommended strength + a prompt pattern; proof that different worlds work on the same greybox |
| 4 | **Project** | **Pick the rider clips** (home-pose clips, 24 fps mp4) to test. 2–3 is enough, including one with spokes or windscreen clearly visible. | — | Clips handed to the ComfyUI side |
| 5 | **[ComfyUI]** | **Build W1 as a script**: SeedVR2 upscale (same settings for every clip) → matte (BiRefNet vs MatAnyone, keep whichever flickers least) → despill to RGBA. Test on the clips from step 4. | Step 4 | Batch rider CLI + RGBA sequences |
| 6 | **Blender** | **Place the rider RGBA into each shot** (the brief says the rider sequence comes rendered into frame) | Step 5 | `rider/` per shot, same frame numbers |
| 7 | **[ComfyUI]** | **First finished shot**: W2 world + shadow + placed rider through W3, then one **final-resolution test** (1280×720 14B → upscale) to measure the real time and cost per shot. | Steps 3 + 6 | A finished shot + a time/cost estimate for the whole film |
| 8 | **Project** | **Choose the track.** Once it's chosen: Demucs splits it into stems (already working) to time section changes, prompt switches and cuts to the beat. | The track | Section timings → the prompt schedule (`--prompt-at`) |

## Decisions for the project chat

1. **The worlds:** which world for which music section (one line of prompt each). That drives steps 3 and 8.
2. **Final resolution:** 1920×1080 or 4K. It decides the upscaler settings, and roughly doubles or quadruples the upscale time.
3. **GPU budget per shot:** the A40 works but is slow at 14B. A faster card (L40S / RTX PRO 6000, ~$0.9–2/hr) roughly halves
   the time. Worth deciding once step 7 gives real numbers.

## Later (not needed for the fundamentals)

From the brief: relight the rider to each world (IC-Light); a very light unifying pass over the whole frame (low-denoise
tile upscale); stylising the rider in some sections; `env_####.png` as a second control if strength alone doesn't hold
the layout; gradual prompt crossfades (today the prompt switches at a chunk border). Also worth a test: **Wan 2.2**
(Fun Control / VACE) against Wan 2.1 for W2 quality.

# SOP 02 — Start frame + end frame → 1080p video

**Use this for:** any shot where you know the first and last frame: a rider "home pose" clip that returns to its
start, a move between two stills, a transition between two designs.
**What you get:** a 1920×1080, 24 fps MP4 (5 s by default) that starts on your first frame and ends on your last.

**Engine:** Wan 2.2 14B first/last frame (ComfyUI's official workflow) → SeedVR2 7B upscale to 1080 → RIFE
interpolation 16 → 24 fps. CLI: `scripts/render_flf_video.py`. Tested on RunPod 2026-11-25.

## 1. Hand over the frames

Make a folder per clip in `inputs/flf/` (video and images are kept out of git):

```
inputs/flf/rider_nod/
    start.png        # required
    end.png          # optional; leave it out and the clip ends on the start frame
    prompt.txt       # one or two sentences: what happens between the frames
```

- **Frames:** any size. 16:9 renders at 1280×720, portrait at 720×1280, square at 960×960, then gets upscaled. The images
  are centre-cropped to that shape, never stretched, so keep the subject away from the edges if the aspect differs.
- **Prompt:** describe the **motion** and keep the camera instruction explicit ("static camera", "slow push in").
  Example: *"He turns his head towards the camera, gives a small nod, then turns back to face forward. The motorcycle
  stays still. Static camera, studio lighting."*
- Tell Claude which clips to run, and whether to use **fast** or **quality** (below).

## 2. Fast or quality

Times are for one 5 s clip on an **L40S** (48 GB, ~$1.09/hr), including the upscale and interpolation.

| Mode | Flag | Time | Use for |
|---|---|---|---|
| **Fast** (recommended) | `--fast` | ~7 min | Most clips. 4-step LightX2V LoRAs. In the rider test it matched quality (same action, as much motion) |
| **Quality** | (default) | ~30 min | Try when fast looks stiff on big motion, or when something must be kept out (below). 20 steps |

**Fast mode ignores `--negative`** (its LoRAs run at cfg 1). When a fast clip has an unwanted extra (feet in a first-person walk,
a glow round an object, a police beacon switching on), first try **another `--seed`** (~6 min). If that doesn't fix it, use
**quality mode with a `--negative`** naming it. That fixed both cases in the Police Bike batch (2026-11-25).

Wan itself renders about 3 min (fast) or 25 min (quality); the rest is the upscale (SeedVR2 7B) and the interpolation.

## 3. Run it (Claude does this on a throwaway pod)

```bash
python scripts/render_flf_video.py --start inputs/flf/rider_nod/start.png [--end inputs/flf/rider_nod/end.png] \
    --prompt "$(cat inputs/flf/rider_nod/prompt.txt)" --fast --seed 42 \
    --output exports/video/rider_nod.mp4
```

Options worth knowing:

| Want | Flag |
|---|---|
| Longer / shorter | `--seconds 3` … `--seconds 7.5` (5 is Wan's sweet spot; past ~7 s motion drifts) |
| Different output frame rate | `--fps 16` (raw), `24` (default), `32`, `48` |
| No upscale (raw 720p) | `--resolution 0` |
| 4K | `--resolution 2160` (slower, more VRAM) |
| Same result again | keep `--seed` |
| Variations | change `--seed` |

**Server setup** (fresh pod): `install_audio_video.sh police-bike` (VHS, KJNodes, SeedVR2, RIFE frame interpolation),
then `download_models.sh flf-wan22` (~38 GB). SeedVR2 and RIFE weights download themselves on first use.

## 4. Check

- First and last frame match your stills (for a loop clip, it should cut back to itself cleanly).
- Faces: the upscale adds detail and can shift a face slightly. Compare against the start frame. If it matters,
  try `--resolution 0` and upscale separately, or a different `--seed`.
- Background: on a green screen it stays flat green, ready for keying.

## Tested alternative: LTX 2.3 (not used by default)

ComfyUI's LTX 2.3 first/last-frame template (`download_models.sh flf-ltx23`) renders **native 1080 at 24 fps in ~3 min**
and even generates audio. But in the test it **invented a TV-style logo** in the corner for part of the clip, rendered
1920×1056 (it needs multiples of 32), and its distilled model ignores negative prompts, so the logo can't be blocked.
Worth retrying when a newer LTX release lands.

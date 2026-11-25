# SOP 03 — Sound for a clip: Foley + stereo bed + rough mix

**Use this for:** giving a finished or near-finished video clip its sound: synced effects (Foley) generated
from the picture, an optional stereo atmosphere underneath, and a rough mix to judge it with.
**What you get, per clip:** a Foley MP4 + `.flac` (mono, synced), optionally 2 stereo beds (`.flac`), and a
mixed MP4 with stereo AAC audio.
**Not for:** music (SOP 04) or making visuals react to audio (SOP 05).

**Engines:** MMAudio large 44k (Foley, `scripts/add_foley.py`) · Stable Audio Open 1.0 (bed,
`scripts/generate_audio.py --engine stable-audio`) · ffmpeg (mix, on the Mac). Tested on RunPod 2026-11-24 on
four CG clips. Setup, once per pod: `docs/gemini/03_…` (Foley) and `docs/gemini/02_…` (Stable Audio, gated:
needs the HF token).

| Time per 10 s clip | Foley ~1 min · bed ~30 s per seed · mix ~2 s (A40) |
|---|---|
| Status | ✅ verified (Foley with/without prompt, beds, mix) |

## 1. Hand over the clips

Put them in `inputs/foley/<batch>/` (MP4/MOV, kept out of git). Optionally add `<clip>.txt` next to a clip with
the sounds you want, one line. Tell Claude whether you want beds as well.

- **Clip length:** MMAudio is trained on 8 s; up to ~12 s is fine. Cut longer edits into shots and run each.
- **Variable frame rate** (phone footage) drifts out of sync. Re-encode first:
  `ffmpeg -i in.mp4 -r 25 -c:v libx264 -crf 18 -c:a copy fixed.mp4`.

## 2. Foley: two runs per clip

Same seed, one without a prompt (MMAudio only watches the picture) and one with the house-style prompt:

```bash
python scripts/add_foley.py --video inputs/foley/b1/bear.mp4 --seed 42 \
    --output exports/foley/bear_noprompt.mp4
python scripts/add_foley.py --video inputs/foley/b1/bear.mp4 --seed 42 \
    --prompt "ambient, reverb, conveyor belt rattle, plastic toy clicks, soft motor hum" \
    --output exports/foley/bear_prompt.mp4
```

**Prompt style:** always start with `ambient, reverb, ` and then name **concrete sound sources**
(materials and actions: "glass marble clink", "rubber squeak", "metal spring boing"). Don't describe the
mood or the picture.

What the test showed:

- MMAudio is precise on **clear visual events** (impacts, a sudden zoom, a cut) and recognisable sources. On
  slow, abstract CG motion it falls back to texture, so the prompt matters most there.
- The defaults (cfg 6.5, negative `white noise, static, crackling, rain, fire, typewriter, music, speech, talking`)
  fixed the "everything sounds like rain/typewriter" problem. Keep them unless a clip *should* have rain or fire:
  then pass `--negative "music, speech, talking"`.
- Output is **mono** and levels vary a lot (−6 to −31 LUFS); the mix step normalises.
- Not happy? Change `--seed` before rewriting the prompt; seeds vary more than you'd expect.

## 3. Stereo bed (optional)

A Stable Audio atmosphere the length of the clip, two seeds to choose from:

```bash
for s in 42 7; do
  python scripts/generate_audio.py --engine stable-audio --duration 15 --seed $s \
      --prompt "ambient, reverb, quiet factory hall room tone, distant machinery hum, air conditioning" \
      --name bed_bear_s$s --output-dir exports/foley/
done
```

Prompt it as a **place**, not events (room tone, weather, distant traffic); the Foley does the events. Beds come
out quiet (down to −38 LUFS); the mix normalises them. Make the bed at least as long as the clip (max 47 s).

## 4. Rough mix (Mac, free)

Bed at −24 LUFS under Foley at −19 LUFS, stereo AAC, the video copied untouched:

```bash
ffmpeg -i inputs/foley/b1/bear.mp4 -i exports/foley/bed_bear_s42.flac -i exports/foley/bear_prompt.flac \
  -filter_complex "[1:a]loudnorm=I=-24:TP=-2,aformat=channel_layouts=stereo[bed];\
[2:a]loudnorm=I=-19:TP=-2,aformat=channel_layouts=stereo[fx];\
[bed][fx]amix=inputs=2:duration=shortest:normalize=0,alimiter=limit=0.89[mix]" \
  -map 0:v -map "[mix]" -c:v copy -c:a aac -b:a 256k -ar 48000 -shortest exports/foley/bear_mix.mp4
```

The result sits around −17 LUFS (good for web previews). For the final, take the `.flac` files into Resolve or
After Effects instead: Foley on a mono track (pan it if the source moves), the bed on a stereo track.

## 5. Check

- Do the hits land on the picture? If a run drifts, re-encode the clip to a constant frame rate (step 1).
- Listen for hiss or crackle under everything: change the seed, or add the offending sound to `--negative`.
- The Foley peaks can reach 0 dBFS; the limiter in the mix catches them, but check the raw `.flac` before using it.

**Coming next (C1 in `docs/WORKFLOW_BACKLOG.md`):** one CLI that does steps 2–4 for a whole folder.

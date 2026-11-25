# Session log

One entry per request, newest at the bottom. Read the last few entries to pick up after a cut-off.

Format: date/time · what was asked · what was done · state / next step.

---

## Backfill (reconstructed from git history)

- **2026-11-01** · LivePortrait stylized workflow + headless runner, aether_engine package, CLIs, numpy <2 pin
  (`db22279`…`be41e82`). LivePortrait working on the RunPod pod.
- **2026-11-12 00:18** · Gaussian splat export added to `generate_3d_asset` (TRELLIS) (`e23ef0c`).
- **2026-11-12 00:45** · Audio, Foley and safe RunPod installers + Gemini guides 01–03 (`b3673e5`).
- **2026-11-13 03:44** · Synced TRELLIS fixes from the verified RunPod (L40S) run (`a371790`).
  **Guide 01 (TRELLIS + splat) is verified working on the pod.**
- **2026-11-13 04:02** · Blender previz → video prepared for its first RunPod run (`2679ae6`):
  `--clay` option on `scripts/render_blender_video.py`, `install_audio_video.sh previz`,
  `download_models.sh previz` (~6 GB), guide `docs/gemini/04_blender_previz_to_video.md`.
  Tested against a fake server only.

## Status board

| Guide | Pipeline | State |
|---|---|---|
| 01 | Image → 3D + Gaussian splat (TRELLIS) | ✅ verified on pod · multi-view + tidy + turntable views added; **next: first multi-view run on pod** (SOP `docs/sop/01_…`) |
| 02 | Audio: Stable Audio / MusicGen / Demucs | ✅ **verified by Claude** on a throwaway A40 (2026-11-24): all 3 CLIs work; HF login on the Mac (`~/.venvs/hf`, user gou-hb1) |
| 03 | Video Foley + audio-reactive | ✅ **Part A (Foley CLI) + Part B (Yvann Text-to-Video) both verified** on fresh A40 pods (2026-11-23) |
| 04 | Blender previz → video (AnimateDiff + ControlNet) | ⬜ ready; general route. Police Bike uses 05 instead |
| 05 | **Police Bike** (Wan VACE world, rider matte, composite) | ✅ **W2 go/no-go passed** (2026-11-24, 14B); look pass + W3 composite preview done (2026-11-25). W1 (rider) still to run. Status for the Blender side: `docs/projects/police-bike/aether_side_status.md` |

Known risk for 04: `controlnet_aux` requirements may change numpy/onnxruntime; guide Step 3 stops if so.
Paste the output to Claude.

---

## Entries

- **2026-11-13** · Session cut off; user asked if I still had context and wanted a log after each request.
  Rebuilt the context from git and the guides, created this log, and saved a memory rule to update it after
  every request. **Next:** finish guide 02 with Gemini. If it fails, paste the errors here.

- **2026-11-13 ~14:30** · Reviewed the TRELLIS results (output/trellis-splat: m1 m2 m4 p1 p2 p3 s1) and the other
  chat's feedback (docs/claude-code--check--feedback-on-trellis-slat-workflow). Goals: (a) white-background
  image(s) → textured models for kitbashing; (b) subject/person/scene images → splat → Blender camera paths.
  Findings: meshes are clean (only m2 and p2 had 40 and 122 faces of specks), 1 m box, 1024 fast textures.
  Splats are Y-up with the head at −Y (Rx −90° aligns them with the mesh, verified on all 7).
  Built: `generate_3d_asset.py` multi-view (`--image` takes several images or a turntable folder, `--views`, `--multimode`; IF_Trellis
  `mode=multi` → `run_multi_image`). `scripts/blender/tidy_trellis_asset.py` drops specks, rotates the splat to Z-up, applies `--height`, puts the base on the ground,
  and keeps mesh and splat aligned. `src/aether_engine/utils/splat_tools.py`, tests (68 pass), guide 01 Step 7b + Step 8.
  Tidy script verified locally on all 7 assets. Multi-view still needs a real pod run. Committed in the next entry.
  For (b), recommended: captured video → COLMAP → splat training (SkySplat add-on already does video → COLMAP → Brush → animated cameras),
  and/or the feed-forward few-image models (AnySplat / WorldMirror / Apple SHARP) as an experiment. 

- **2026-11-13 ~15:00** · User: commit and push, finish multi-view, write an SOP. **Avenue (b) (scene splats + camera
  paths) is PARKED by the user**: only revisit if something works really well out of the box.
  Added `scripts/blender/render_turntable_views.py` (N evenly spaced transparent RGBA views of a .blend object or an
  imported mesh, view_00 = front, optional fallback light). Tested locally on m4: 8 views in about 23 s.
  SOP `docs/sop/01_image_to_kitbash_asset_sop.md` covers input routes A/B/C → pod → generate → tidy → Blender → QA, and is linked from the README.
  Committed and pushed to feature/multi-workflow-engine.
  **Next:** on the pod, `git pull`, then a multi-view run (e.g. the bear turntable, `--views 6`). Risk: BiRefNetRMBG on a
  batch of images hasn't been tested. Guide 02 audio is still paused.

- **2026-11-13 ~15:10** · User mostly uses 4–6 Gemini-generated views (front/side/back/top/bottom) rather than turntables. No
  code change needed (all named images are used; put the front first). Built a review file
  `output/trellis-splat/trellis_first_tests_review.blend` (not in git, since output/ is ignored): the 7 tidied meshes in a row
  with labels, plus a coloured point preview of each splat behind it (geometry nodes, not a real splat render).
  Back to the earlier plan: user + Gemini on guide 02 (audio); guide 04 (Blender previz) is ready to hand over after 02.

- **2026-11-13 ~15:20** · Session cut off again (4th time). User pasted my last message. Checked: branch is in sync with
  origin at ed3a750, working tree clean, nothing lost. No new work. **Next:** unchanged. Guide 02 (audio) with Gemini, then guide 04 after a `git pull` on the pod.

- **2026-11-19** · User: guide 02 (audio) with Gemini is **still not finished**. New project brief: **Police Bike** music video
  (saved as `docs/projects/police-bike/brief.md`). Checked it against guide 04: 04 covers only the "older route" of Workflow 2
  (SD1.5 AnimateDiff, resizes, MP4), so it isn't enough. Built guide **05** `docs/gemini/05_police_bike_comfyui.md`:
  W2 `scripts/render_world_vace.py` + template `wan_vace_depth_to_video.json` (native WanVaceToVideo, PNG in → PNG out with
  the same frame numbers, 4k+1 chunks carrying 13 generated frames over with a VACE keep-mask, a seamless `--loop` join pass, `--prompt-at`
  schedule, `--resume`, 1.3B/14B, fp8); W1 upscale + matte to be built by hand in the UI (SeedVR2 + BiRefNet/MatAnyone) +
  `scripts/rider_rgba.py` (unmix + despill that keeps the yellow-green jacket); W3 `scripts/composite_shot.py`. Installer group
  `police-bike` (updates ComfyUI only if WanVaceToVideo is missing), `matanyone`; downloads `wan-vace`, `wan-vace-14b`.
  80 tests pass (mock server only; nothing has run on a GPU yet). User also asked if Claude can drive RunPod directly: `runpodctl` 3.1.1 + an SSH key
  are configured on the Mac, so yes, with the user's go-ahead per pod start. Noticed **3 pods named blender-lab-bear-macro-full-1
  RUNNING** (RTX PRO 4000) and flagged them to the user. **Next:** finish 02, then 05 Step 8 (go/no-go), on the pod or driven by Claude.

- **2026-11-20** · Session cut off (5th time). User pasted my last message and asked for a re-print as actions. Checked: tree clean at
  d8178c2. The 3 blender-lab-bear-macro-full-1 pods are **gone** now (`runpodctl pod list` shows only 4 EXITED pods). Re-printed the
  to-do list. No new code. **Next:** unchanged. Finish 02, then 05 Step 8 (go/no-go).

- **2026-11-21** · User checked the log was up to date before closing the chat. It was, and it was in sync with origin. Closing.
  **Next on resume:** guide 02 (audio) with Gemini → pod setup (`git pull`, `install_audio_video.sh police-bike`,
  `download_models.sh wan-vace`) → guide 05 Step 8 go/no-go → W1 rider workflow built in the UI (send the saved JSON to Claude to batch).

- **2026-11-23** · User asked for a status check: where we are, what's next, what's open for them. Checked: tree clean and in sync
  with origin at 35de227. `runpodctl pod list` is **empty** (the 4 EXITED pods are gone too, so nothing is billing). Summarised the
  status board and the open decisions. No new code. **Next:** unchanged. Guide 02 → pod setup → 05 Step 8 go/no-go.

- **2026-11-23 ~21:20–21:36 UTC** · User asked me to start a cheap pod, test guide 03 myself and report back. EU-NL-1 (where
  `aether-fx-storage` lives) had **no GPUs at all**, so I used a throwaway **A40 at $0.59/hr in EU-SE-1** with no network volume
  (image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, a fresh ComfyUI with a `--system-site-packages` venv, repo sent with `git archive`).
  Guide 03 Steps 2–4 + A1–A2 all passed on the first try: `install_audio_video.sh video` clean, `download_models.sh mmaudio` 5 GB,
  ComfyUI 0.46.0 with no import failures. `add_foley.py` on `waves.mp4` (8 s, 24 fps): 63 s the first time, 42 s warm. Output keeps
  24 fps and 1280×720, AAC 44.1 kHz **mono**, about −17 LUFS. Ran once with a prompt and once without. Results in `output/test-03-foley/`
  (not in git). **Pod deleted** after downloading; about 15 min, roughly $0.15. Part B (Yvann audio-reactive) not tested: it needs about
  5 GB more models and the UI. **Next:** user listens to the results; decide on Part B. Otherwise unchanged (02 → 05 Step 8).

- **2026-11-23 ~23:15–23:43 UTC** · User: both Foley clips are good (prompt and no prompt sound similar). Test Part B; guide 02 the same
  way **after** this. Explained mono → stereo in Resolve, and Foley (video → sound) vs audio-reactive (sound → video).
  Part B: no music on the Mac, so I made a synthetic 120 BPM drum loop. A throwaway **A40 at $0.59/hr** (EU-SE-1, no volume), fresh ComfyUI,
  `install_audio_video.sh video` + `yvann-deps` and `download_models.sh yvann` all clean. Chrome couldn't open the pod proxy (curl could),
  so I loaded the **AudioReactive_TextToVideo_Yvann** template in headless Chromium **on the pod** (Playwright → `app.loadGraphData` →
  `graphToPrompt` → `/prompt`): set the audio, bypassed the 2x-sudo upscaler (node 735). No node errors; ran in 245 s.
  Peaks detected exactly every 15 frames (0.5 s = 120 BPM). Visuals switch between orchids and swirls on the beats. **Gotcha:** the template's
  frame count is fixed (100 frames at 30 fps = 3.3 s), so it ignores the audio length. Set it to `seconds × 30` for a full track.
  Results in `output/test-03b-reactive/` (not in git). Pod deleted; both tests together cost about $0.50.
  **Next:** guide 02 (audio) tested the same way by Claude, then 05 Step 8.

- **2026-11-24** · User asked what Part B's source is. Explained: audio + text prompts in → brand-new generated video out (music unchanged);
  Foley is the reverse. Mentioned the untested Images-to-Video and Video-to-Video examples (V2V restyles existing footage to the beat;
  may suit Police Bike). No code change. **Next:** unchanged. Guide 02 tested by Claude when the user says go.

- **2026-11-24** · User expects to use Foley most and will prepare test clips. Created the drop folder `inputs/foley-tests/` (video is
  gitignored; an optional `<clip>.txt` holds the prompt; 8–12 s clips with clear visible events). Explained guide 02's uses: Stable Audio =
  ambience/texture beds (≤47 s, gated on HF), MusicGen = tempo-ish scratch music (≤30 s, tempo not locked), Demucs = 4-stem split.
  **Open for user:** include Stable Audio in the 02 test? (They accept the HF licence and run `hf auth login`; Claude never types the
  token.) MusicGen + Demucs can be tested without it. **Next:** Foley test on the user's clips when dropped; guide 02 test.

- **2026-11-24 ~00:30–00:52 UTC** · Foley test on the user's 3 clips in `inputs/foley-tests/` (censor_figure 12 s, smoke-vessel 10 s,
  smuggle_bear_assembly 8.25 s), each with no prompt and with a prompt (rule from the user: **prompts always include "ambient, reverb"** plus
  per-clip detail), seed 42. A throwaway A40 ($0.59/hr). All 6 OK, about 56 s each. Results in `output/foley-tests/` (not in git). The bear clip
  is quiet (about −31 LUFS vs −19 to −22 for the others), so raise it in the edit. HF downloads were slow on this host; MMAudio's first-use
  BigVGAN download pulls **1.9 GB** (including the discriminator/optimizer). Worth pre-fetching in `download_models.sh mmaudio` for the user's volume.
  Pod deleted. **Noticed a pod not started by me:** `blender-lab-bear-fall-test4-1` (RTX 4090, $0.89/hr, created 00:48 UTC), left alone and
  flagged to the user. **Next:** user listens; guide 02 (Stable Audio licence question still open).

- **2026-11-24** · User feedback on the Foley tests: they all sound similar and noise-like (typewriter/rain/fire). Only the zoom into the
  bear's eye (smuggle_bear noprompt) felt precise. Measured spectral flatness: user clips 0.13–0.29 vs waves 0.13, so they are as noisy as
  literal waves (the bear prompt is the noisiest). Diagnosis: MMAudio is trained on real-world video, so for abstract or stylised CG it falls back to texture;
  it syncs well to clear visual events; "ambient, reverb" probably pushes towards noise (reverb is better added in Resolve). Proposed a re-run:
  concrete sound-source prompts, negative "white noise, static, crackling, rain, fire, typewriter", cfg 6–7, plus a version without
  "ambient, reverb". Recommended the workflow **Stable Audio stereo bed + MMAudio sync hits + mix/reverb in Resolve**.
  User: yes to Stable Audio if it's good; Claude said it's worth it. **Waiting on the user:** accept the HF licence and `! hf auth login`.
  **Next:** one pod for guide 02 (Stable Audio + MusicGen + Demucs) + the Foley re-run + Stable Audio beds for the 3 clips.

- **2026-11-24 ~11:15–11:50 UTC** · User made a HF read token (`aether-runpod`) and logged in on the Mac (`~/.venvs/hf/bin/hf`, saved to
  `~/.cache/huggingface/token`). Gated access to stable-audio-open-1.0 confirmed. One A40 pod ($0.59/hr): the token was copied to `/root/.hf_token`
  (mode 600), used only for `download_models.sh stable-audio`, then **deleted**. **Guide 02 fully verified:** Stable Audio 40 s (stereo; quiet at
  −38 LUFS, normalise it), MusicGen 90 BPM 8 bars + `--stems`, `separate_stems.py` (the beat is basically drums + bass; the "other" stem is near
  silent, so no piano came through; the tempo hasn't been checked). Stable Audio **stereo beds**, 15 s × 2 seeds per user clip. **Foley re-run** with
  negative "white noise, static, crackling, rain, fire, typewriter, music, speech" and cfg 6.5, as amb_reverb + concrete variants. Spectral
  flatness dropped a lot (censor 0.13–0.16 → 0.04–0.06, smoke ~0.2 → 0.10); **the "ambient, reverb" variant came out *less* noisy than the
  concrete one**, so my earlier guess was wrong: the negative prompt + cfg did the work. The bear concrete version is still noisy (0.32). The censor
  concrete version peaks at 0 dBFS (may clip). Combined previews (bed s42 at −24 LUFS + amb_reverb Foley at −19 LUFS, stereo AAC) are in
  `output/test-02-audio/combined/`. All in `output/test-02-audio/` (not in git). Pod deleted. Balance 33.27 → 26.90; this pod only cost about
  $0.35, so the rest is most likely the `blender-lab-bear-fall-test4-1` 4090 pod (the API key has no billing:read to confirm).
  VHS logs "Error opening output files" for silent source clips, which is harmless.
  **Next:** user listens. Then guide 05 Step 8 (Police Bike go/no-go), or update guides/scripts with the findings (Foley negative default,
  pre-fetch the BigVGAN vocoder, Yvann frame count = seconds × fps).

- **2026-11-24 ~11:55–15:20 UTC** · User: guides 02/03 results "pretty good", so update guides/scripts, commit, push, then guide 05 + an
  explainer for the Claude chat preparing the Blender files. **Committed `973dcfc`:** add_foley cfg 6.5 + noise negative default (template),
  download_models mmaudio pre-fetches the 2 BigVGAN files, guide 02/03 verified + notes (Yvann frame count), test asserting the Foley defaults (80 pass).
  **Guide 05 Step 8** on a throwaway A40 ($0.59/hr, ~2 h, **$1.06**): Blender frames from `blender-lab-police-bike/renders/previews/police_bike/`
  (loop 89 complete; **zoom only 119/267 rendered**). Installer `police-bike` clean (numpy 1.26.4 held), wan-vace + 14b downloaded fast.
  8a 46 s; 8b loop 1.3B 5 min (dark, flat blue); loop 14B 21 min (**good**: neon, skyline, reflections, seamless wrap, no boiling); zoom 119f
  1.3B 5 min and 14B 21 min (layout tracks the pull-back, chunk border clean, but wide framings go flat blue). **Verdict: GO, use 14B.**
  Wrote `docs/projects/police-bike/aether_side_status.md` for the Blender chat. Results + side-by-side MP4s in `output/test-05-world/` (not in git).
  Pod deleted. Gotcha: `ssh … 'nohup …&'` holds the ssh open unless the outer stdout is redirected too.
  **Next:** the full zoom render from Blender; a 14B strength sweep + richer prompt / reference image; W1 rider needs rider clips.

- **2026-11-25** · User: the zoom results look great; sharing `aether_side_status.md` with the main Police Bike chat. Asked what "full zoom" meant:
  Blender's `zoom.log` stops partway through frame 120, so the preview render was **interrupted** (119/267 frames, the first ~5 s of the
  pull-back); added that to the status doc. Recommended next steps (in order): (1) a free local W3 composite preview of the loop
  (14B world × shadow + the rider cut from `beauty` with `matte`); (2) a 14B look pass on the loop (~$1–1.5: strength 0.7/1.0/1.2 + 2 other
  worlds from the brief, e.g. watercolour forest / synthwave grid) to fix the flat wide shots and prove the "new world per section" idea;
  (3) W1 rider as a script (SeedVR2 + BiRefNet + `rider_rgba.py`), needing the rider clips (the Blender repo log says a clip library exists);
  (4) the full zoom when Blender re-renders it. Backlog: TRELLIS multi-view pod run, guide 04 (park unless needed), Foley for the film later.
  **Waiting on the user:** which to start.

- **2026-11-25** · User asked to be told when the waiting is over; nothing is running (no pods, no jobs). We're waiting on the user's go-ahead
  and on Blender (zoom frames 120–267, rider clips). Wrote **`docs/projects/police-bike/next_steps.md`** (ordered steps with owner: ComfyUI
  vs Blender vs project, what's needed, decisions) for the Police Bike chat. Its role: that chat takes the recommendations and comes back for
  tests/new workflows. Wrote **`docs/WORKFLOW_BACKLOG.md`** (A: built but GPU-untested, B: in docs but not built, C: recommended, plus an order).
  README status table updated (02/03/05 verified) and linked to the backlog.
  **Next:** user's call. The suggested order is Police Bike steps 1+3 (composite preview + 14B look pass), then the C1 sound-pass CLI, then a TRELLIS multi-view test.

- **2026-11-25 ~01:20–03:58 UTC** · User: proceed with Police Bike steps 1+3 (the project chat is on step 2), agreed the order → C1 sound pass → TRELLIS
  multi-view → C2/C3, and urgently wants **start + end frame → 1080 video**. **Step 1 (local, free):** the loop composite (14B neon world × shadow
  + rider cut from beauty by matte) in `output/comp-preview-loop/`; lines up; the rider's daylight vs night world → relight needed.
  **Pod: L40S $1.09/hr, EU→US-TX-4, ~2.4 h, $3.76.** Exported ComfyUI's official `video_wan2_2_14B_flf2v` and `video_ltx2_3_flf2v` templates
  through the real frontend (Playwright: load → `graphToPrompt`) → API JSON. Tests on `home.png` (start = end): Wan 2.2 fast 3 min 720p16 clean; LTX 2.3
  3 min native 1080p24 **but a hallucinated TV-style logo**, 1920×1056, and the distilled cfg 1 ignores negatives → not default.
  Wan quality 20 steps ≈ 25 min (76 s/it). **I killed the first quality run by restarting ComfyUI to load RIFE** (~$0.50 lost).
  **Built `render_flf_video.py`** + `flf_wan22_api.json` / `flf_wan22_fast_api.json` (generated from the exports: titled, + SeedVR2 7B fp8 →
  RIFE rife49 x3 → every 2nd → VHS 24 fps), `download_models.sh flf-wan22|flf-ltx23`, 13 tests (95 pass), SOP 02, committed `2412bb6`.
  End to end: fast **7 min → 1920×1080, 24 fps, 121 frames**; quality 29 min; fast had as much motion → recommended. RIFE needs
  `ComfyUI-Frame-Interpolation` (via safe_node_install; not in an installer group yet). Drop folder: `inputs/flf/<clip>/start.png [end.png] prompt.txt`.
  **Step 3 look pass** (VACE 14B, L40S ~12 min/pass): neon 0.7 ≈ 1.2 (strength barely matters; the richer prompt brightened it), watercolour
  works but boxes stay boxes, synthwave excellent; single-frame jumps in 2 of 4. Results in `output/look-pass/` (+ `look_grid_4.mp4`).
  Updated `aether_side_status.md` + `next_steps.md` (relight moves up; greybox shapes for organic worlds; rider clips can be generated).
  Gotcha: on the pod, `nohup … & disown` with `< /dev/null` still held the ssh open sometimes; harmless.
  **Next:** C1 sound pass per the agreed order; add Frame-Interpolation to an installer group; IC-Light relight test when the project asks.

- **2026-11-25 ~09:20–10:10 UTC** · User: the keying in the composite looks bad, can it be improved? The Police Bike chat shared
  `docs/pieces/police-bike-world-prompts.md` (T1–T3 worlds, step 4 rider clips) but doesn't know where we are. Also: which ComfyUI
  workflows lack an SOP (Foley and the other audio?). **Keying:** the composite cut the rider from Blender's `beauty` with a binary
  `matte` at 960×540, which gave a hard edge plus the original key's green fringes. Re-keyed the **original 1080 green-screen** `ride-idle`
  (24 frames) on the Mac: a colour-difference key on green *relative to brightness* (the shadowed screen keys too) with guards for
  near-black and anything reddish (hi-vis stays solid), then `rider_rgba.py --edge 5 --tolerance 0.45`, plus a 1 px choke. Clean
  outline, see-through windscreen and spokes, no floor blob; some green remains in the motion-blurred spokes. Source clips carry a Gemini
  sparkle watermark (bottom right). Made it **`scripts/green_key.py`** (+2 tests, 97 pass). Results in `output/key-test/`
  (`old_vs_new.mp4`, `new_softkey_1080.mp4`, stills). **SOPs written:** 03 Foley + bed + rough mix (ffmpeg mix recipe verified: −16.8 LUFS
  stereo), 04 music/soundscape/stems, 05 audio-reactive (Yvann UI), 06 Blender depth → AI world → keyed composite. README links them;
  LivePortrait has a setup guide but no SOP. `next_steps.md`: zoom ✅ (full 267 with skyline), a "where the ComfyUI side is" section (T1–T3
  sweep not run yet, ~$3 on an L40S, waiting for a go; `loop` predates the skyline; keying ask: supply RGBA from the green clip, never re-cut
  from `beauty`; W1 can start on the 3 named clips). No pod used, $0.
  **Next:** the user's go on the T1–T3 sweep + W1 pod session; the user is preparing FLF start/end frames; C1 sound pass after.

- **2026-11-25 ~10:00–13:40 UTC** · User: run the 11 Police Bike start/end-frame tests (`inputs/flf/pb_*`, prepared by the project chat; fast mode,
  quality if walk-in/mount look stiff). **Pod: L40S $1.09/hr, US-NC-1.** Setup 13 min. 11 clips fast seed 42, ~6 min each, no failures.
  The Mac disk filled up during the download (ENOSPC, even for tool output). The user freed space, and the pod waited (billing). Results:
  walk-in, mount, gun-away, tp-walk, hairdryer, rat, tazer good (walk-in/mount not stiff → no quality rerun). **Beacons light up blue** in the bike clips,
  **sneakers pop in** on fp baton/spoon, **halo** round the glock. **Fast mode = cfg 1, so negatives are ignored.** Seed 7 fixed spoon and glock (beacon
  reduced to a one-frame flicker; baton still has feet). Quality + negative (`feet, shoes, legs, floor, glow, halo, outline`) fixed spoon and glock (~28 min each).
  Wrote `docs/projects/police-bike/flf_batch_2026-11-25.md`, `output/flf-pb/picks/` (one per clip), SOP 02 note (fast ignores negatives → seed, then quality+neg).
  **Still running:** visor-down-idle quality + beacon negative; baton seeds 3/11/23. Then delete the pod.

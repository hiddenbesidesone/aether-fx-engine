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
| 02 | Audio: Stable Audio / MusicGen / Demucs | ⏸ paused mid-run (user back to it later) |
| 03 | Video Foley + audio-reactive | ⬜ not run yet |
| 04 | Blender previz → video (AnimateDiff + ControlNet) | ⬜ ready, waits until 02 is done, then `git pull` on pod first |

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

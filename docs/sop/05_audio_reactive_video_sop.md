# SOP 05 — Audio-reactive video (visuals driven by a track)

**Use this for:** generating an animation whose motion, intensity or prompts pulse with a piece of music:
music visuals, beat-synced loops, abstract backgrounds.
**What you get:** an MP4 (with the track) where the picture changes on the beats of the chosen stem.
**Source:** an **audio** file. The video is generated from scratch; nothing is edited. (To add sound *to* a
video, use SOP 03.)

**Engine:** Yvann audio-reactive nodes + AnimateDiff (SD1.5), using the pack's example workflow
**AudioReactive_TextToVideo_Yvann** in the ComfyUI web UI (there's no CLI). Tested on RunPod 2026-11-24 on a
120 BPM beat. Setup, once per pod: `docs/gemini/03_…` (Steps 2–4: `install_audio_video.sh video` +
`yvann-deps`, `download_models.sh yvann`).

| Time | ~5–10 min for 8 s (240 frames) on an A40 |
|---|---|
| Status | ✅ Text-to-Video verified · Images-to-Video / Video-to-Video 🟡 need extra models, untested |

## 1. Hand over

- The track: `inputs/audio/<name>.wav|flac|mp3`. Short is better: 4–15 s per run.
- A prompt for the visuals (or several, one per section), and which part should drive them: drums (default),
  bass, vocals, or the whole mix.

## 2. Run it (ComfyUI UI)

1. Open ComfyUI → **Workflow → Browse Templates** → **ComfyUI_Yvann-Nodes** → **AudioReactive_TextToVideo_Yvann**.
2. Load the track in the audio loader; set the prompts.
3. **Set the frame count to seconds × 30.** The template is fixed at 100 frames at 30 fps (3.3 s) whatever the track
   length: an 8 s track needs 240.
4. Bypass the `2x-sudo-UltraCompact` upscaler group (Ctrl+B) unless that model has been added.
5. **Queue.** The MP4 lands in `ComfyUI/output/`.

The workflow splits the track with Hybrid Demucs and maps the chosen stem's energy onto the animation
strength and prompt switching. To use a generated beat, make it with `generate_audio.py --stems` (SOP 04) and
load the full mix.

## 3. Check

- Do the visual pulses land on the hits? If they're late, the frame count or fps doesn't match the track.
- Too jittery: point it at a smoother stem (bass) or lower the reactive weight in the "Audio Analysis" nodes.
- SD1.5 AnimateDiff looks soft and dreamy by design. For sharper output, upscale afterwards (SeedVR2, as in SOP 02).

**Not built yet:** Images-to-Video (animate your own images to the beat) and Video-to-Video (restyle real footage
to the beat). Both need extra ControlNet / IP-Adapter models; ask if you need either.

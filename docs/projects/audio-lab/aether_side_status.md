# Audio Lab: aether side status

Answers `audio-lab/docs/aether-requests.md`. Outputs go to `audio-lab/_input/from-aether/`. Newest at the bottom.

---

## A1. Stems for five tracks: quote (2026-11-27)

**Inputs checked:** all five MP3s are in `_input/original-tracks/` (hb1-4-skeng-4, hb1-2, hb1-3, one-drop-3, hidden-besides-one).

**How I'll run it:** on one throwaway pod, using the separation tools directly (demucs + `audio-separator` in a venv),
not through ComfyUI. Our `separate_stems.py` only has plain 4-stem `htdemucs` with FLAC out. The direct route gives
htdemucs_ft, 6s and RoFormer, plus 24-bit WAV.

| Pass | Model | Tracks |
|---|---|---|
| D4 | `htdemucs_ft` (4-stem, fine-tuned bag) | all 5 |
| R+D | BS-RoFormer vocals/instrumental (`model_bs_roformer_ep_317_sdr_12.9755`), then `htdemucs_ft` on the instrumental → drums/bass/other | all 5 |
| D6 | `htdemucs_6s` (+ piano, guitar) | hb1-2 and skeng (2 tracks, not 1, because the hb1-2 synth lead is the reason for it) |
| (if available) | a 6-stem RoFormer (BS-RoFormer SW) | hb1-2 only, as a second opinion on `other` |

**Output format:** 24-bit WAV at 44.1 kHz, no resampling, trimming or normalising. Demucs by default **rescales**
stems that would clip. That is normalising, and it breaks "stems sum back to the input". So I'll write float first,
check peaks and the sum, then write 24-bit. If a stem peaks over 0 dBFS (likely, because the bounces sit at 0 dB),
I'll deliver that stem as 32-bit float as well and say so, rather than clamp it.
Note: the MP3 decoder adds encoder padding at the start. I'll check that stem length matches the decoded input to the sample.

**Back to you:** `_input/from-aether/stems/<model>/<track>/{drums,bass,vocals,other[,piano,guitar]}.wav` +
`stems/README.md` with which model I'd keep per track, where each one bleeds (listened + measured: sum residual,
cross-stem correlation), and spectrogram PNGs of `other` per model for hb1-2.

**Time and cost:** L40S or A40 (~$0.45–1.10/hr). Setup ~15 min, the separations ~15–20 min, checks + download ~15 min.
That's **~1 h ≈ $0.50–1.10**, well under the $3 cap. I'll stop and report if it heads past $2.

**Status:** done, see below.

---

## A1 + A2: done (2026-11-27)

**Delivered:** `audio-lab/_input/from-aether/stems/` (71 WAVs, 3.2 GB, with `README.md`, `report.json`, `_spectrograms/`) and
`_input/from-aether/textures/` (18 WAVs). I checked every file sample by sample against the pod copy (ffmpeg md5) before deleting the pod.

**Picks** (detail in `stems/README.md`):
- **hb1-2:** `bs-roformer-sw`. Its stems sum to −43 dB residual (Demucs: −24 to −33), and the breakdowns are true silence. No model isolates the synth
  lead: it sits in `other` with a chord part (~400–1100 Hz) and low-mid energy. Options: band-split at ~1.2 kHz, or a lead/melody model pass on `other` (cheap follow-up).
- **skeng:** `bs-roformer+htdemucs_ft` (it has a real vocal part). **hb1-3, one-drop-3:** `roformer+ft` (the vocals come out cleaner). **hidden-besides-one:** either.
- None of the models sums back exactly, so every folder has `residual.wav` (input − stems); stems + residual = input exactly. No stem over 0 dBFS.
- The bleed notes are measured (levels, correlation, spectrograms), not listened to.

**Method:** demucs 4.x + audio-separator 0.48 in a venv on the pod (not ComfyUI). Each MP3 is decoded once to float WAV and every model runs on that.
`--float32 --clip-mode none` for Demucs (no rescaling); RoFormer wrote 32-bit and its level was unchanged (fitted gain 0.99–1.02 across all,
which is the model, not scaling). A2 used `generate_audio.py` on a fresh ComfyUI 0.46 with `download_models.sh stable-audio` (HF token).

**Cost:** $1.91 (balance 19.13 → 17.22). An RTX 4090 pod on `runpod/pytorch:1.0.3` sat at "awaiting container" for ~20 min with no SSH
port. I deleted it; that cost ~$0.35. Then an A40 on `1.0.2` + `--ports 22/tcp`. The GPU work took ~25 min. **The download dominated**: ~0.5 MB/s, and the
first tar broke after 65 min, so I sent the rest as lossless FLAC and decoded it on the Mac.

**Lessons for next time:** send stems as FLAC (lossless, about a third of the size; near-silent stems are almost free) and decode to WAV on arrival.
Use image `1.0.2` + `--ports 22/tcp` (runpodctl `--wait` doesn't add the SSH port itself).

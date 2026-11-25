# SOP 04 — Text → music / soundscape, and splitting tracks into stems

**Use this for:** an ambient bed or texture from a text prompt, a scratch beat at a set tempo, or splitting
any track (generated or your own) into bass / drums / other / vocals.
**What you get:** `.flac` files (stereo for Stable Audio), plus 4 stem `.flac`s when you split.
**Not for:** sound synced to a video (SOP 03).

**Engines:** Stable Audio Open 1.0 · Meta MusicGen · Hybrid Demucs, all via ComfyUI. CLIs:
`scripts/generate_audio.py`, `scripts/separate_stems.py`. Tested on RunPod 2026-11-24. Setup, once per pod:
`docs/gemini/02_audio_music_and_stems.md` (Stable Audio is gated: it needs the HF token).

| Pick | Good for | Limits |
|---|---|---|
| **Stable Audio** (`--engine stable-audio`) | Ambience, drones, textures, room tone, one-shots. **Stereo.** The one to use under Foley | Up to 47 s. Levels swing −13 to −38 LUFS between seeds |
| **MusicGen** (`--engine musicgen`) | Scratch / temp beats at a tempo | Up to 30 s, mono-ish, tempo not locked, named instruments may not appear. Not for finals |
| **Demucs** (`separate_stems.py`, or `--stems`) | Clean 4-stem splits: drive visuals from the drums (SOP 05), time cuts, duck music under dialogue/Foley | Bass/drums/vocals are strong; "other" is thin on beats |

## 1. Ask for it

Tell Claude: the engine (or just the use), a prompt, the length, how many seeds. For stems, drop the track in
`inputs/audio/` (wav/flac/mp3).

## 2. Run it

```bash
# Ambient bed: 2–4 seeds, keep the best
python scripts/generate_audio.py --engine stable-audio --duration 40 --seed 42 \
    --prompt "dark ambient drone, rain on a metal roof, distant thunder" --output-dir exports/audio/

# Scratch beat: 8 bars at 90 BPM, split into stems as well
python scripts/generate_audio.py --engine musicgen --prompt "boom bap hip-hop beat, dusty vinyl drums" \
    --bpm 90 --bars 8 --stems --output-dir exports/audio/

# Stems from any track
python scripts/separate_stems.py --audio inputs/audio/track.mp3 --output-dir exports/stems/
```

Prompt tips (tested):

- **Stable Audio:** name the place, the sources and the texture ("quiet factory hall room tone, distant machinery
  hum"). `--negative` defaults to the template's; add things you keep hearing.
- **MusicGen:** genre + drums + one or two instruments. `--bpm` is added to the prompt but not enforced; check the
  tempo before cutting to it.
- **Demucs:** `--chunk-length` (default 10 s) trades VRAM for quality; the default is fine on 24 GB+.

## 3. Check and finish

- **Normalise** every generated file in the edit (or `ffmpeg -i in.flac -af loudnorm=I=-24 out.flac` for a bed).
- Loops: Stable Audio doesn't make seamless loops by itself; crossfade the ends in the edit.
- Stems: they should sum back to the original. If the drums bleed into "other", that's normal for dense mixes.

## Licence note

Stable Audio Open is under the Stability AI Community licence (free under $1M annual revenue). MusicGen weights
are CC-BY-NC 4.0: **non-commercial**, so keep it to scratch music.

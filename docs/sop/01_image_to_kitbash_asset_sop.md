# SOP: Image(s) → textured kitbash asset + splat (TRELLIS)

**Use this for:** turning a concept image, a few photos or a Blender turntable of one subject into a textured
`.glb` for kitbashing (plus an optional Gaussian splat `.ply`), placed in Blender at the right size.
**Not for:** whole scenes or rooms. TRELLIS reconstructs single objects.
**Setup:** done once per pod with `docs/gemini/01_image_to_3d_and_gaussian_splat.md`. This SOP is the
day-to-day routine after that.

| Time per asset | ~1–2 min mesh (fast) · ~3–5 min with `opt` 2048 texture · tidy ~3 s |
|---|---|
| GPU | RunPod L40S (verified). Multi-view: 4–8 views fit comfortably. |
| Status | Single view ✅ verified on pod · multi-view 🟡 built, first pod run pending · tidy ✅ verified locally |

---

## 1. Prepare the input (Mac)

Pick **one** route. All inputs must show the **same subject**, no clutter, nothing cropped off.

| Route | When | How |
|---|---|---|
| **A. Single image** | Concept art, a product shot | A PNG with a transparent background, or the subject on plain white. One subject, centred, nothing cropped off. The back will be guessed. |
| **B. Photos / several images** | Real object, or AI images of it from several angles | Front, sides and back on a plain background, same lighting. Name them so the front sorts first (`01_front.png`, `02_side.png` …). |
| **C. Blender turntable** (best) | The subject already exists in Blender | Run the renderer below. You get exact, evenly spaced views on transparent backgrounds. |

Route C:

```bash
cd ~/Development/Projects/creative-ai-suite/aether-fx-engine
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

# From a .blend (name the object, or leave --object out to frame every visible mesh)
$BLENDER -b path/to/scene.blend -P scripts/blender/render_turntable_views.py -- \
    --object Bear --out input/bear_views --views 8

# From a mesh file
$BLENDER -b -P scripts/blender/render_turntable_views.py -- --import model.glb --out input/model_views
```

Check the PNGs: the whole subject is visible in each one, and the lighting is even. If a scene has no lights,
the script adds a soft one. `--engine workbench` is fastest but flat; `--elevation 10` sets the camera height.
Nothing is saved back to your `.blend`.

> Already have a turntable (e.g. 96 frames)? Use that folder as it is. The CLI picks evenly spaced frames itself.

## 2. Upload to the pod

Start the pod, then in the JupyterLab terminal:

```bash
cd /workspace/aether-fx-engine && git pull
bash scripts/runpod/start_comfy.sh          # after every pod restart
mkdir -p inputs /workspace/exports/3d
```

Upload the image(s) or folder into `/workspace/aether-fx-engine/inputs/`. In the JupyterLab file browser you
upload files with the up-arrow icon. For a folder, make it first and upload its files into it.

## 3. Generate

```bash
cd /workspace/aether-fx-engine
A=/workspace/aether-venv/bin/python

# A. single image
$A scripts/generate_3d_asset.py --image inputs/thing.png --export-splat \
    --texture-mode opt --texture-size 2048 --output-dir /workspace/exports/3d/

# B. named views (front first)
$A scripts/generate_3d_asset.py --image inputs/01_front.png inputs/02_side.png inputs/03_back.png \
    --export-splat --texture-mode opt --texture-size 2048 --output-dir /workspace/exports/3d/

# C. a folder of views / turntable frames (6 evenly spaced are used; --views changes that)
$A scripts/generate_3d_asset.py --image inputs/bear_views/ --views 6 --export-splat \
    --texture-mode opt --texture-size 2048 --output-dir /workspace/exports/3d/
```

**Iterating?** Leave out `--texture-mode opt --texture-size 2048` for quick ~1 min previews, then rerun the
keeper with the same `--seed N` (printed as `seed=` in the run output) for the final.

**Expected:** a `[*] framed …` line per image, `[*] multi-view: N views, stochastic` for B/C, then
`[✓] mesh …_trellis_<seed>.glb` and `[✓] splat …_trellis_<seed>.ply`.

Download both files (right-click → Download) into `output/<project>/` in the repo on the Mac.

## 4. Tidy (Mac, ~3 s per asset)

```bash
$BLENDER -b -P scripts/blender/tidy_trellis_asset.py -- output/<project>/thing_trellis_42.glb --height 0.35
```

For each `.glb` and `.ply` with the same name this writes `_tidy.glb` / `_tidy.ply`. The tidy step:
- removes loose specks (`--min-piece 0` keeps everything)
- turns the splat upright (Z-up) so it sits exactly on the mesh
- scales the asset to `--height` metres (leave it out to keep TRELLIS's 1 m box)
- puts the base on the ground at the origin (`--no-ground` turns that off)

Give it a folder instead of a file to tidy everything in it at that one height.

## 5. Into Blender

- **Mesh:** *File → Import → glTF 2.0*, then pick `…_tidy.glb`. Its size and position are already right. Next steps
  (remesh, decimate, shaders): `docs/3d_ai_to_blender_workflow_guide.md`, Phases 3–4.
- **Splat:** import `…_tidy.ply` with your splat add-on. It should stand upright, overlapping the mesh. If it
  lies on its back, your add-on applies its own Y-up conversion. In that case use the original `.ply` and tell
  Claude which add-on it is.

## 6. Check the result

| Look at | Good | If not |
|---|---|---|
| Back and sides | Colour and detail are carried all the way round | Use more views (route B/C). With one image, the back is always a guess. |
| Surface | Smooth, no blobs | `--steps 30`; different `--seed` |
| Texture | Sharp at the distance you'll use it | `--texture-mode opt --texture-size 2048` |
| Multi-view looks smeared or doubled | One clean shape | Views aren't the same subject or pose, or the lighting differs. Try `--multimode multidiffusion`, or fewer, cleaner views. |
| Thin parts (straps, fingers) | Present | TRELLIS often merges or drops these. Model them yourself in Blender. |

## Known limits (the technology, not settings)

- The splat stores colour only, with no shine that changes with viewing angle, so it looks flatter than splats trained from footage.
- Only the outside surface exists. Hidden or internal parts are never generated.
- One object per run. For scenes, see the parked "avenue b" in `docs/SESSION_LOG.md`.

## Troubleshooting

Problems with the server, the node or CUDA: see the table in guide 01, Step 7. Otherwise, paste the full terminal output to Claude.

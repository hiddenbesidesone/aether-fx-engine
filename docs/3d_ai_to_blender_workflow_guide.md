# 3D Modeling Workflow: RunPod (ComfyUI) to Blender
**Target:** Realistic Barbie doll characters and detailed hard-surface props (water pistols, household items).

---

### Phase 1: Prepping the 4K Source Image
Generative 3D models hallucinate geometry if the background has shadows, gradients, or clutter. The input image must have a clean alpha mask.

1. **Aspect Ratio and Framing:** Crop your 4K render so the subject is centered with roughly 10% padding around the edges. Keep the aspect ratio square (1:1, e.g., 2048x2048 or 4096x4096).
2. **Handle Single-View Face vs. Full Body:**
   * **Full Body:** Ensure limbs are not clipped. An A-pose or neutral pose yields the cleanest 3D back-projection.
   * **Face Only:** Single-view face images will generate a complete bust/head, but the AI must guess the back of the hair and head. If you need 360° fidelity for the head, generating a quick side-profile reference or using multi-view diffusion first produces significantly better topology.

---

### Phase 2: 3D Extraction in ComfyUI (RunPod)
The best open-source pipeline on RunPod is **TRELLIS** (using `ComfyUI-TRELLIS`) or **Hunyuan3D-2** (`ComfyUI-Hunyuan3D-Wrapper`). TRELLIS preserves sharp facial features, molded plastic seams, and thin geometry much better than commercial tools like Meshy.

#### ComfyUI Node Graph Setup
1. **`Load Image`:** Load your 4K source image.
2. **`BiRefNet` or `RMBG-1.4` (Background Removal):**
   * Connect `Load Image (IMAGE)` -> `BiRefNet (image)`.
   * Feed the processed output into an `Image Crop/Pad` node to ensure a transparent, centered alpha cutout.
3. **`TRELLIS Pipeline Loader`:**
   * Load the TRELLIS checkpoint (requires an instance with at least 16GB–24GB VRAM, such as an RTX 4090, A40, or L40).
4. **`TRELLIS Image-to-3D`:**
   * Connect the masked image into the input.
   * **SS Sampling Steps:** Set between `20` and `30` (higher improves surface smoothness).
   * **SLAT Sampling Steps:** Set to `20` (controls fine geometric structure).
   * **Texture Resolution:** Set to `1024` or `2048`.
5. **`Export GLB / Save 3D Mesh`:**
   * Save the extracted asset as `.glb` directly into your RunPod shared network volume or download it locally.

---

### Phase 3: Blender Import and Retopology
AI-generated meshes output as a dense, triangulated "soup" of polygons that cannot deform cleanly for animation or accept procedural subdivision.

1. **Import the Asset:**
   * In Blender: `File` -> `Import` -> `glTF 2.0 (.glb/.gltf)`.
   * Select the imported object and press `Ctrl + A` -> `Apply All Transforms`.
2. **Remeshing for Clean Topology:**
   * **Quick Built-in Option:** Go to the **Data Object Properties** tab (green triangle) -> **Remesh** -> select **QuadriFlow** -> set target face count between `15,000` and `40,000` -> click **QuadriFlow Remesh**.
   * **Production Option:** If you have the third-party **Quad Remesher** (Exoside) add-on installed, use it with Symmetry enabled on the X-axis for characters.
3. **Separating Hard-Surface Props (Water Pistols):**
   * Enter **Edit Mode** (`Tab`).
   * Select a face on the reservoir, trigger, or nozzle, press `Ctrl + L` (select linked), and press `P` -> `Selection` to split into separate objects for independent shading.

---

### Phase 4: Shader Assembly in Blender
AI texturing generates a single "baked" diffuse map that includes lighting. To make the doll look like real manufactured vinyl and the water pistol look like translucent toy plastic, replace the default material settings in the **Shader Editor**.

#### 1. Vinyl/Molded Plastic Doll Skin
* **Base Color:** Connect the AI-generated texture map into the Base Color of the **Principled BSDF**.
* **Subsurface Scattering (Crucial for Doll Vinyl):**
  * **Subsurface Weight:** `0.04` to `0.08`
  * **Subsurface Radius:** Warm pinkish-red (`1.0`, `0.4`, `0.2`)
  * **Subsurface Scale:** `0.05`
* **Surface Polish:**
  * **Roughness:** `0.28` to `0.35`
  * **IOR:** `1.46` (standard PVC plastic)
* **High-Gloss Paint Accents (Eyes & Lips):**
  * In Edit Mode, assign the faces of the eyes and lips to a new material slot. Use the same texture, but drop the **Roughness** to `0.05` and set **Coat** to `1.0` to mimic factory-painted gloss lacquer on matte vinyl.

#### 2. Translucent Toy Water Pistol Plastic
* **Transmission Weight:** `1.0`
* **Base Color:** Saturated neon pink, green, or cyan.
* **Roughness:** `0.08` to `0.15` (creates a slightly foggy molded acrylic look).
* **IOR:** `1.49`
* **Internal Water (Optional):** Duplicate the tank geometry, scale it down slightly (`Alt + S`), invert its normals, and set its material to pure clear glass (IOR `1.333`).

---

### Alternative: Rodin (Cloud SaaS)
If you need to bypass RunPod for quick turnarounds, use **Rodin (Hyper3D)** rather than Meshy. 

* Upload your high-res cutout directly to the Rodin web interface.
* Unlike Meshy, Rodin preserves fine eye and facial contours with significantly less distortion, allows 360° free previews before credit spending, and provides cleaner quad-retopology downloads natively.
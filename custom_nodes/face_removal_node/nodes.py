"""MediaPipe face detection -> ComfyUI MASK, for inpainting faces out of frames."""
import cv2
import numpy as np
import torch

try:
    import mediapipe as mp
except ImportError:  # surfaced at execution time so ComfyUI still loads
    mp = None


class FaceMaskMediaPipe:
    CATEGORY = "aether/face"
    RETURN_TYPES = ("MASK", "INT")
    RETURN_NAMES = ("mask", "face_count")
    FUNCTION = "detect"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "min_confidence": ("FLOAT", {"default": 0.5, "min": 0.05, "max": 1.0, "step": 0.05}),
                "model": (["short_range", "full_range"],),
                "padding": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 2.0, "step": 0.05}),
                "feather": ("INT", {"default": 15, "min": 0, "max": 255, "step": 1}),
            }
        }

    def detect(self, images, min_confidence, model, padding, feather):
        if mp is None:
            raise RuntimeError("mediapipe is not installed: pip install -r custom_nodes/face_removal_node/requirements.txt")

        batch, h, w, _ = images.shape
        masks = np.zeros((batch, h, w), dtype=np.float32)
        total = 0

        with mp.solutions.face_detection.FaceDetection(
            model_selection=0 if model == "short_range" else 1,
            min_detection_confidence=min_confidence,
        ) as detector:
            for i in range(batch):
                frame = (images[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                result = detector.process(frame)  # expects RGB, which ComfyUI images are
                for det in result.detections or []:
                    box = det.location_data.relative_bounding_box
                    pw, ph = box.width * padding, box.height * padding
                    x0 = int(max(0, (box.xmin - pw) * w))
                    y0 = int(max(0, (box.ymin - ph) * h))
                    x1 = int(min(w, (box.xmin + box.width + pw) * w))
                    y1 = int(min(h, (box.ymin + box.height + ph) * h))
                    center = ((x0 + x1) // 2, (y0 + y1) // 2)
                    axes = (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2))
                    cv2.ellipse(masks[i], center, axes, 0, 0, 360, 1.0, -1)
                    total += 1
                if feather > 0:
                    k = feather * 2 + 1
                    masks[i] = cv2.GaussianBlur(masks[i], (k, k), 0)

        return (torch.from_numpy(masks), total)


NODE_CLASS_MAPPINGS = {"AetherFaceMaskMediaPipe": FaceMaskMediaPipe}
NODE_DISPLAY_NAME_MAPPINGS = {"AetherFaceMaskMediaPipe": "Face Mask (MediaPipe)"}

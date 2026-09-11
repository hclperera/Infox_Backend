import os
import cv2
import tempfile
import logging
import numpy as np
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PAGE_MODEL_PATH = os.getenv("PAGE_MODEL_PATH", "models/page/best.pt")
DOT_MODEL_PATH  = os.getenv("DOT_MODEL_PATH",  "models/dots/best.pt")
DEVICE          = os.getenv("DEVICE", "cpu")
FRONT_CLASS_ID  = int(os.getenv("FRONT_CLASS_ID", "2"))

_page_model = None
_dot_model  = None

def _get_page_model():
    global _page_model
    if _page_model is None:
        from ultralytics import YOLO
        _page_model = YOLO(PAGE_MODEL_PATH)
    return _page_model

def _get_dot_model():
    global _dot_model
    if _dot_model is None:
        from sahi import AutoDetectionModel
        _dot_model = AutoDetectionModel.from_pretrained(
            model_type="ultralytics",
            model_path=DOT_MODEL_PATH,
            confidence_threshold=0.35,
            device=DEVICE,
        )
        # Override to handle dense braille pages (~3500 dots)
        if hasattr(_dot_model.model, "overrides"):
            _dot_model.model.overrides["max_det"] = 3500
        if hasattr(_dot_model.model, "predictor") and _dot_model.model.predictor is not None:
            _dot_model.model.predictor.args.max_det = 3500
    return _dot_model

def run_vision_stages(image_path: str) -> dict:
    """
    Person 1 calls this.
    Executes Page Crop -> Preprocess -> SAHI Dot Detection.
    """
    logger.info("[Pipeline] Stage 1: Page crop")
    # 1. Page Crop
    model = _get_page_model()
    results = model.predict(source=image_path, save=False, max_det=1, conf=0.6, verbose=False)
    result = results[0]
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image at path: {image_path}. File may be missing or corrupt.")


    if len(result.boxes) == 0:
        logger.warning("No page detected in %s — using full image.", image_path)
        cropped = img
    else:
        box = result.boxes.xyxy[0].cpu().numpy().astype(int)
        cropped = img[box[1]:box[3], box[0]:box[2]]

    logger.info("[Pipeline] Stage 2: Preprocessing")
    # 2. Preprocess (Grayscale -> Bilateral -> CLAHE)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    logger.info("[Pipeline] Stage 3: SAHI Dot Detection")
    # 3. Detect dots (SAHI)
    from sahi.predict import get_sliced_prediction
    img_h, img_w = enhanced.shape[:2]

    # SAHI requires a file path, so we save the preprocessed image temporarily
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cv2.imwrite(tmp_path, enhanced)
        dot_model = _get_dot_model()
        sahi_result = get_sliced_prediction(
            tmp_path,
            dot_model,
            slice_height=640,
            slice_width=640,
            overlap_height_ratio=0.20,
            overlap_width_ratio=0.20,
            postprocess_type="NMS",
            postprocess_match_threshold=0.3,
            postprocess_class_agnostic=False,
            verbose=0,
        )
    finally:
        os.unlink(tmp_path)

    # Convert SAHI output to standard YOLO format arrays
    yolo_outputs = []
    for obj in sahi_result.object_prediction_list:
        bbox = obj.bbox
        w_px = bbox.maxx - bbox.minx
        h_px = bbox.maxy - bbox.miny
        cx_norm = (bbox.minx + w_px / 2.0) / img_w
        cy_norm = (bbox.miny + h_px / 2.0) / img_h
        yolo_outputs.append([obj.category.id, cx_norm, cy_norm, w_px / img_w, h_px / img_h])

    return {
        "yolo_outputs": yolo_outputs,
        "img_width": img_w,
        "img_height": img_h
    }

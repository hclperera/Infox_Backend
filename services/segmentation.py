"""Page crop, trained grayscale/bilateral/CLAHE preprocessing, and SAHI inference."""
import os
import tempfile
import logging
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
_page_model = _dot_model = None
_inference_lock = threading.Lock()


def _get_page_model():
    global _page_model
    if _page_model is None:
        from ultralytics import YOLO
        _page_model = YOLO(os.getenv('PAGE_MODEL_PATH', 'models/page/best.pt'))
    return _page_model


def _get_dot_model():
    global _dot_model
    if _dot_model is None:
        from sahi import AutoDetectionModel
        _dot_model = AutoDetectionModel.from_pretrained(
            model_type='ultralytics', model_path=os.getenv('DOT_MODEL_PATH', 'models/dots/best.pt'),
            confidence_threshold=float(os.getenv('DOT_CONF', '.25')),
            device=os.getenv('DEVICE', 'cpu'))
        _dot_model.model.overrides.update(max_det=int(os.getenv('DOT_MAX_DET', '3500')),
                                         agnostic_nms=False,
                                         iou=float(os.getenv('DOT_IOU', '.7')))
    return _dot_model


def _front_id(names):
    if not isinstance(names, dict):
        names = dict(enumerate(names))
    names = {int(k): str(v) for k,v in names.items()}
    configured = os.getenv('FRONT_CLASS_ID')
    if configured is not None:
        cid = int(configured)
        if cid not in names:
            raise ValueError(f'FRONT_CLASS_ID={cid} absent from model classes: {names}')
        return cid, names
    matches = [k for k,v in names.items() if v.strip().lower() in ('front', 'recto', 'front dots', 'front_dot')]
    if len(matches) != 1:
        raise ValueError(f'Cannot resolve front class from {names}; set FRONT_CLASS_ID explicitly')
    return matches[0], names


def run_vision_stages(image_path: str, *, debug_dir=None) -> dict:
    # Cached SAHI/YOLO predictor state is shared by FastAPI background threads.
    with _inference_lock:
        return _run(image_path, debug_dir=debug_dir)


def _run(image_path, *, debug_dir=None):
    import cv2
    import numpy as np
    from sahi.predict import get_sliced_prediction
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f'Cannot decode image: {image_path}')
    ih, iw = img.shape[:2]
    crop_box = [0,0,iw,ih]
    warnings = []
    if os.getenv('PAGE_CROP', '1') == '1':
        result = _get_page_model().predict(source=img, save=False, max_det=1, conf=.6,
                                           device=os.getenv('DEVICE','cpu'), verbose=False)[0]
        if result.boxes is not None and len(result.boxes):
            x1,y1,x2,y2 = result.boxes.xyxy[0].cpu().numpy()
            crop_box = [max(0,int(np.floor(x1))), max(0,int(np.floor(y1))),
                        min(iw,int(np.ceil(x2))), min(ih,int(np.ceil(y2)))]
        else:
            warnings.append('No page detected; used full image')
    x1,y1,x2,y2 = crop_box
    if x2 <= x1 or y2 <= y1:
        raise ValueError('Page model returned an empty crop')
    crop = img[y1:y2,x1:x2]
    # Match the images used to train the dot model. Cropping only selects a
    # region; these operations run on that region before dot inference.
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    enhanced = cv2.createCLAHE(clipLimit=2., tileGridSize=(8,8)).apply(gray)
    detector_input = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    model = _get_dot_model()
    front_id, names = _front_id(model.model.names)
    settings = dict(slice_height=640, slice_width=640, overlap_height_ratio=.2,
                    overlap_width_ratio=.2, postprocess_type='NMS',
                    postprocess_match_metric=os.getenv('SAHI_MATCH_METRIC','IOS'),
                    postprocess_match_threshold=float(os.getenv('SAHI_MATCH_THRESHOLD','.3')),
                    postprocess_class_agnostic=False,
                    perform_standard_pred=os.getenv('SAHI_STANDARD_PRED','1') == '1', verbose=0)
    # PNG avoids an extra lossy JPEG encode. Use a file path to make channel
    # ordering explicit across SAHI versions.
    with tempfile.TemporaryDirectory(prefix='infox-') as tmp:
        path = str(Path(tmp)/'input.png')
        if not cv2.imwrite(path, detector_input):
            raise OSError('Could not write detector input')
        pred = get_sliced_prediction(path, model, **settings)
    h,w = crop.shape[:2]
    output = []
    for obj in pred.object_prediction_list:
        b = obj.bbox
        bw,bh = b.maxx-b.minx,b.maxy-b.miny
        output.append([int(obj.category.id),(b.minx+b.maxx)/(2*w),
                       (b.miny+b.maxy)/(2*h),bw/w,bh/h,float(obj.score.value)])
    if debug_dir is not None:
        folder = Path(debug_dir); folder.mkdir(parents=True,exist_ok=True)
        for name, data in [('crop.png',crop),('detector_input.png',detector_input)]:
            if not cv2.imwrite(str(folder/name),data):
                raise OSError(f'Could not save {name}')
    return {'yolo_outputs': output, 'img_width': w, 'img_height': h,
            'front_class_id': front_id, 'class_names': names, 'crop_box': crop_box,
            'warnings': warnings, 'settings': {'preprocess': 'clahe',
                'confidence': float(os.getenv('DOT_CONF','.25')), 'sahi': settings,
                'model_path': os.getenv('DOT_MODEL_PATH','models/dots/best.pt')}}

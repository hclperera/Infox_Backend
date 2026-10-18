"""Page-crop validation independent of detector/runtime dependencies."""
import math


def page_crop_box(boxes, width, height, *, allow_full_image=False):
    if len(boxes) == 0:
        if allow_full_image:
            return [0, 0, width, height], ['No page detected; used full image by explicit configuration']
        raise ValueError('No Braille page detected. Retake the photo with the entire page '
                         'inside the frame, filling most of the image, and the camera facing the page.')
    box = boxes[0]
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError('Page model returned invalid crop coordinates')
    x1, y1, x2, y2 = box
    crop = [max(0, math.floor(x1)), max(0, math.floor(y1)),
            min(width, math.ceil(x2)), min(height, math.ceil(y2))]
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError('Page model returned an empty crop')
    return crop, []

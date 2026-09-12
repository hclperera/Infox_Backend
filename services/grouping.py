import math
import logging
import numpy as np

import os

def group_dots(yolo_outputs: list, img_width: int, img_height: int) -> list:
    """
    Person 1 calls this.
    Takes raw YOLO outputs, filters them, handles slant, 
    and groups into 6-bit binary strings.
    """
    if not yolo_outputs:
        return []

    # 1. Geometric Noise Filter
    valid_dots = []
    front_class_id = int(os.getenv("FRONT_CLASS_ID", "2"))
    for detection in yolo_outputs:
        class_id, x_c_norm, y_c_norm, w_norm, h_norm = detection
        if int(class_id) != front_class_id:
            continue
            
        w_px = w_norm * img_width
        h_px = h_norm * img_height
        area = w_px * h_px
        aspect_ratio = max(w_px, h_px) / min(w_px, h_px) if min(w_px, h_px) > 0 else 0
        
        if 80 <= area <= 12000 and aspect_ratio <= 2.2:
            valid_dots.append([x_c_norm, y_c_norm, w_norm, h_norm])

    if not valid_dots:
        return []

    raw_pixel_dots = []
    widths, heights = [], []
    
    for dot in valid_dots:
        x_px, y_px = dot[0] * img_width, dot[1] * img_height
        widths.append(dot[2] * img_width)
        heights.append(dot[3] * img_height)
        raw_pixel_dots.append([x_px, y_px])
        
    median_w, median_h = np.median(widths), np.median(heights)
    
    # 2. Detect Slant
    angles = []
    for i, dot1 in enumerate(raw_pixel_dots):
        for j, dot2 in enumerate(raw_pixel_dots):
            if i == j: continue
            dx = dot2[0] - dot1[0]
            dy = dot2[1] - dot1[1]
            if 0 < dx < (median_w * 10):
                angle = math.degrees(math.atan2(dy, dx))
                if -15 < angle < 15:
                    angles.append(angle)
    
    # Guard: if too few dots for reliable angle estimation, skip slant correction
    if len(raw_pixel_dots) < 5:
        angles = []
                    
    # 3. Apply Virtual Rotation (Centered)
    rotated_dots = []
    if angles:
        page_slant = np.median(angles)
        logging.debug(f"Detected page slant: {page_slant:.2f} degrees. Flattening coordinates...")
        theta = math.radians(-page_slant)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        
        # Rotate around the center of the image
        cx = img_width / 2.0
        cy = img_height / 2.0
        
        for idx, (x, y) in enumerate(raw_pixel_dots):
            dx = x - cx
            dy = y - cy
            x_rot = dx * cos_t - dy * sin_t + cx
            y_rot = dx * sin_t + dy * cos_t + cy
            rotated_dots.append([x_rot, y_rot, x, y])
    else:
        logging.debug("No significant slant detected.")
        rotated_dots = [[x, y, x, y] for x, y in raw_pixel_dots]

    # 4. Line Grouping
    rotated_dots.sort(key=lambda d: d[1])
    lines = []
    current_line = [rotated_dots[0]]
    
    for i in range(1, len(rotated_dots)):
        y_dist_prev = abs(rotated_dots[i][1] - current_line[-1][1])
        y_dist_first = abs(rotated_dots[i][1] - current_line[0][1])
        
        if y_dist_prev < (median_h * 2.0) and y_dist_first < (median_h * 4.0):
            current_line.append(rotated_dots[i])
        else:
            lines.append(current_line)
            current_line = [rotated_dots[i]]
    lines.append(current_line)
    
    logging.debug(f"Lines detected: {len(lines)}")
    
    # Calculate intra-line horizontal gaps for cell boundary detection
    all_gaps = []
    for line in lines:
        line.sort(key=lambda d: d[0])
        for i in range(1, len(line)):
            gap = line[i][0] - line[i-1][0]
            if gap > (median_w * 0.2): 
                all_gaps.append(gap)
    
    if all_gaps:
        gaps_arr = np.array(all_gaps)
        cell_boundary = np.percentile(gaps_arr, 25) * 1.25
    else:
        cell_boundary = median_w * 1.5
    
    max_cell_width = cell_boundary
    logging.debug(f"Cell boundary threshold: {max_cell_width:.1f}px")

    six_bit_codes = []
    
    # Calculate global cell pitch to accurately detect spaces and missing columns
    all_cell_dists = []
    for line in lines:
        current_cell = [line[0]]
        raw_cells = []
        for i in range(1, len(line)):
            gap = line[i][0] - line[i-1][0]
            if gap < max_cell_width and (line[i][0] - current_cell[0][0]) < max_cell_width:
                current_cell.append(line[i])
            else:
                raw_cells.append(current_cell)
                current_cell = [line[i]]
        raw_cells.append(current_cell)
        
        for i in range(1, len(raw_cells)):
            dist = raw_cells[i][0][0] - raw_cells[i-1][0][0]
            if dist < max_cell_width * 3.0:  # Exclude obvious word spaces
                all_cell_dists.append(dist)
                
    pitch = np.median(all_cell_dists) if all_cell_dists else median_w * 2.5
    logging.debug(f"Calculated Global Cell Pitch: {pitch:.1f}px")
    
    # 5. Horizontal Cell Grouping
    for line in lines:
        current_cell = [line[0]]
        raw_cells = []
        for i in range(1, len(line)):
            gap = line[i][0] - line[i-1][0]
            if gap < max_cell_width and (line[i][0] - current_cell[0][0]) < max_cell_width:
                current_cell.append(line[i])
            else:
                raw_cells.append(current_cell)
                current_cell = [line[i]]
        raw_cells.append(current_cell)
        
        cells = [raw_cells[0]]
        for i in range(1, len(raw_cells)):
            dist = raw_cells[i][0][0] - raw_cells[i-1][0][0]
            num_spaces = int(round(dist / pitch)) - 1
            for _ in range(max(0, num_spaces)):
                cells.append("SPACE")
            cells.append(raw_cells[i])
        
        prev_left_x = None
        for cell in cells:
            if cell == "SPACE":
                six_bit_codes.append("000000")
                if prev_left_x is not None:
                    prev_left_x += pitch
                continue
                
            cell.sort(key=lambda d: d[0])
            cell_width = max(d[0] for d in cell) - min(d[0] for d in cell)
            
            if prev_left_x is None:
                prev_left_x = cell[0][0]
            else:
                steps = round((cell[0][0] - prev_left_x) / pitch)
                prev_left_x += steps * pitch
            
            if cell_width > (median_w * 0.6):
                cell_mean_x = np.mean([d[0] for d in cell])
                left_col = [d for d in cell if d[0] < cell_mean_x]
                right_col = [d for d in cell if d[0] >= cell_mean_x]
                prev_left_x = cell[0][0] # Realignment
            else:
                # Single column cell
                if (cell[0][0] - prev_left_x) > (pitch * 0.3):
                    left_col = []
                    right_col = cell
                else:
                    left_col = cell
                    right_col = []
                    prev_left_x = cell[0][0] # Realignment
            
            # Localized Row Detection
            cell_mean_x = np.mean([d[0] for d in cell])
            local_dots = [d for d in line if abs(d[0] - cell_mean_x) < pitch * 3]
            if not local_dots: local_dots = cell
            
            local_y_min = min(d[1] for d in local_dots)
            local_y_max = max(d[1] for d in local_dots)
            local_y_range = local_y_max - local_y_min
            
            if local_y_range > (median_h * 1.5):
                row_boundary_top = local_y_min + local_y_range / 3
                row_boundary_bot = local_y_min + 2 * local_y_range / 3
            else:
                local_mean_y = np.mean([d[1] for d in local_dots])
                row_boundary_top = local_mean_y - (median_h * 0.5)
                row_boundary_bot = local_mean_y + (median_h * 0.5)
            
            binary_code = [0] * 6
            
            for dot in left_col:
                if dot[1] < row_boundary_top: binary_code[0] = 1
                elif dot[1] > row_boundary_bot: binary_code[2] = 1
                else: binary_code[1] = 1
                
            for dot in right_col:
                if dot[1] < row_boundary_top: binary_code[3] = 1
                elif dot[1] > row_boundary_bot: binary_code[5] = 1
                else: binary_code[4] = 1
                
            code_str = "".join(map(str, binary_code))
            six_bit_codes.append(code_str)
            
        # Add newline at the end of each physical Braille line
        six_bit_codes.append("\n")
            
    return six_bit_codes

"""Regular six-dot lattice reconstruction with explicit calibration and diagnostics.

Requires numpy and scipy. Coordinates are normalized YOLO class,x,y,w,h[,score].
The public group_dots signature is unchanged. Use group_dots_detailed to inspect
uncertainty. Curled/perspective-distorted pages need rectification first.
"""
from dataclasses import dataclass, asdict
import os
import numpy as np
from scipy.spatial import cKDTree


@dataclass
class GridConfig:
    front_class_id: int = 2
    angle_degrees: float | None = None
    column_spacing: float | None = None
    row_spacing: float | None = None
    cell_pitch: float | None = None
    line_pitch: float | None = None
    x_origin: float | None = None
    y_origin: float | None = None
    tolerance: float = 0.28
    max_aspect_ratio: float = 2.2
    max_cells_per_line: int = 300


def _clusters(values, tolerance):
    groups = []
    for v in sorted(values):
        if not groups or v - np.mean(groups[-1]) > tolerance:
            groups.append([float(v)])
        else:
            groups[-1].append(float(v))
    return np.array([np.median(g) for g in groups])


def _angle(points, diameter):
    if len(points) < 6:
        return 0.0
    tree = cKDTree(points)
    _, inds = tree.query(points, k=min(18, len(points)))
    a = []
    for i, neighbors in enumerate(inds):
        delta = points[neighbors[1:]] - points[i]
        for dx, dy in delta:
            if dx > diameter and abs(dy / dx) < np.tan(np.deg2rad(15)):
                a.append(np.rad2deg(np.arctan2(dy, dx)))
    if not a:
        return 0.0
    counts, edges = np.histogram(a, bins=np.arange(-15, 15.101, .1))
    center = (edges[np.argmax(counts)] + edges[np.argmax(counts)+1])/2
    near = np.array(a)[np.abs(np.array(a)-center) < .2]
    return float(np.median(near))


def _assign(values, origin, spacing, pitch, slots):
    k = np.arange(slots)
    indices = np.rint((values[:, None] - origin - k*spacing)/pitch).astype(int)
    errors = values[:, None] - (origin + indices*pitch + k*spacing)
    slot = np.argmin(np.abs(errors), axis=1)
    ix = np.arange(len(values))
    return indices[ix, slot], slot, errors[ix, slot]


def _fit_axis(values, slots, diameter, spacing=None, pitch=None, origin=None):
    spacing_given = spacing is not None
    levels = _clusters(values, diameter * .45)
    gaps = np.diff(levels)
    if spacing is None:
        if len(gaps) < slots:
            raise ValueError('Too little grid evidence; supply spacing, pitch and origin calibration')
        spacing = float(np.percentile(gaps, 20))
    if spacing <= 0 or not np.isfinite(spacing):
        raise ValueError('Grid spacing must be positive and finite')
    if pitch is not None and (not np.isfinite(pitch) or pitch <= (slots-1)*spacing):
        raise ValueError('Grid pitch must exceed the span of its dot slots')
    if origin is not None and not np.isfinite(origin):
        raise ValueError('Grid origin must be finite')
    # Candidate periods come from actual level differences, not box widths.
    if pitch is None:
        low, high = ((2.05, 3.5) if slots == 2 else (3.1, 6.0))
        differences = []
        for step in range(1, min(7, len(levels))):
            ds = levels[step:] - levels[:-step]
            differences.extend(ds[(ds > low*spacing) & (ds < high*spacing)])
        if not differences:
            raise ValueError('Cannot infer grid pitch; provide calibration')
        ds = np.array(differences)
        bins = np.round(ds/(spacing*.04)).astype(int)
        candidates = sorted(set(bins), key=lambda b: -np.sum(bins == b))[:14]
        pitches = [float(np.median(ds[bins == b])) for b in candidates]
    else:
        pitches = [float(pitch)]
    sample = levels if len(levels) <= 160 else levels[np.linspace(0, len(levels)-1, 160).astype(int)]
    trials = []
    for period in pitches:
        origins = [origin] if origin is not None else [v-s*spacing for v in levels[:24] for s in range(slots)]
        for start in origins:
            n, s, err = _assign(sample, start, spacing, period, slots)
            score = np.mean(np.minimum((err/spacing)**2, .25))
            trials.append((score, float(start), spacing, period))
    # Refine several starts by alternating assignments and least squares.
    best = None
    for _, start, gap, period in sorted(trials)[:16]:
        for _ in range(8):
            n, s, err = _assign(sample, start, gap, period, slots)
            keep = np.abs(err) < gap*.40
            if np.sum(keep) < 4:
                break
            cols, fixed, names = [], np.zeros(np.sum(keep)), []
            for name, col, known, val in [('o', np.ones(np.sum(keep)), origin, start),
                                          ('d', s[keep], spacing if spacing_given else None, gap),
                                          ('p', n[keep], pitch, period)]:
                if known is None:
                    cols.append(col); names.append(name)
                else:
                    fixed += col*known
            if cols:
                matrix = np.array(cols).T
                if np.linalg.matrix_rank(matrix) < len(cols):
                    break
                sol = np.linalg.lstsq(matrix, sample[keep]-fixed, rcond=None)[0]
                fit = dict(zip(names, sol))
                new_start, new_gap, new_period = fit.get('o', start), fit.get('d', gap), fit.get('p', period)
                if new_gap <= 0 or new_period <= (slots-1)*new_gap or abs(new_gap/spacing-1) > .35:
                    break
                start, gap, period = new_start, new_gap, new_period
        n, s, err = _assign(sample, start, gap, period, slots)
        score = float(np.mean(np.minimum((err/gap)**2, .25)))
        if best is None or score < best[0]:
            best = (score, float(start), float(gap), float(period))
    score, start, gap, period = best
    _, used_slots, _ = _assign(sample, start, gap, period, slots)
    if origin is None and len(set(used_slots)) < slots:
        raise ValueError('Missing complete row/column evidence; origin is ambiguous. Supply calibration')
    return start, gap, period, score


def group_dots_detailed(yolo_outputs, img_width, img_height, *, config=None):
    cfg = config or GridConfig(front_class_id=int(os.getenv('FRONT_CLASS_ID', '2')))
    if img_width <= 0 or img_height <= 0:
        raise ValueError('Image dimensions must be positive')
    if not 0 < cfg.tolerance < .5:
        raise ValueError('Grid tolerance must lie between 0 and 0.5')
    warnings, rejected, records = [], [], []
    other_centers = []
    for idx, row in enumerate(yolo_outputs):
        if len(row) not in (5, 6):
            raise ValueError(f'Detection {idx} must have 5 or 6 values')
        a = np.asarray(row, dtype=float)
        if not np.all(np.isfinite(a)) or a[0] != int(a[0]) or not (0 <= a[1] <= 1 and 0 <= a[2] <= 1) or not (0 < a[3] <= 1 and 0 < a[4] <= 1) or (len(a) == 6 and not 0 <= a[5] <= 1):
            rejected.append({'index': idx, 'reason': 'invalid detection'})
            continue
        if int(a[0]) != cfg.front_class_id:
            other_centers.append([a[1]*img_width, a[2]*img_height])
            continue
        w, h = a[3]*img_width, a[4]*img_height
        if max(w,h)/min(w,h) > cfg.max_aspect_ratio:
            rejected.append({'index': idx, 'reason': 'aspect ratio'})
            continue
        records.append([a[1]*img_width, a[2]*img_height, w, h, a[5] if len(a)==6 else 1., idx])
    if not records:
        return {'codes': [], 'cells': [], 'warnings': ['No front dots'], 'rejected': rejected, 'grid': None}
    data = np.array(records)
    diameter = float(np.median(np.sqrt(data[:,2]*data[:,3])))
    if other_centers:
        distances, _ = cKDTree(other_centers).query(data[:,:2], k=1)
        conflicts = int(np.sum(distances < .35*diameter))
        if conflicts:
            warnings.append(f'{conflicts} front detections have near-coincident other-class detections; inspect classification')
    # Broad scale-relative rejection; never shrink a box to manufacture a dot.
    ok = (np.sqrt(data[:,2]*data[:,3]) >= diameter*.35) & (np.sqrt(data[:,2]*data[:,3]) <= diameter*3.5)
    for r in data[~ok]:
        rejected.append({'index': int(r[5]), 'reason': 'relative size outlier'})
    data = data[ok]
    if not len(data):
        raise ValueError('All front detections failed relative-size filtering')
    # Same-class duplicates only. Highest confidence wins; area breaks ties.
    order = sorted(range(len(data)), key=lambda j: (-data[j,4], data[j,2]*data[j,3]))
    tree = cKDTree(data[:,:2]); suppressed, kept = set(), []
    for j in order:
        if j in suppressed:
            rejected.append({'index': int(data[j,5]), 'reason': 'same-class duplicate'})
            continue
        kept.append(j)
        suppressed.update(k for k in tree.query_ball_point(data[j,:2], .35*diameter) if k != j)
    data = data[kept]
    angle = cfg.angle_degrees if cfg.angle_degrees is not None else _angle(data[:,:2], diameter)
    if not np.isfinite(angle):
        raise ValueError('Grid angle must be finite')
    theta = np.deg2rad(angle)
    # Coordinates rotate around (0,0); calibration origins use this frame.
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    flat = data[:,:2] @ rotation
    x0, dx, px, xs = _fit_axis(flat[:,0], 2, diameter, cfg.column_spacing, cfg.cell_pitch, cfg.x_origin)
    y0, dy, py, ys = _fit_axis(flat[:,1], 3, diameter, cfg.row_spacing, cfg.line_pitch, cfg.y_origin)
    ci, col, ex = _assign(flat[:,0], x0, dx, px, 2)
    li, row, ey = _assign(flat[:,1], y0, dy, py, 3)
    good = (np.abs(ex) <= dx*cfg.tolerance) & (np.abs(ey) <= dy*cfg.tolerance)
    if np.mean(good) < .80:
        raise ValueError('Poor regular-grid fit (<80% of dots). Check rectification, class ID or calibration')
    if cfg.x_origin is None or cfg.y_origin is None:
        warnings.append('Automatically inferred lattice; verify its overlay before trusting sparse text')
    if np.any(~good):
        warnings.append(f'{int(np.sum(~good))} off-grid detections excluded; inspect rejected dots')
    cells = {}
    for j in range(len(data)):
        if not good[j]:
            rejected.append({'index': int(data[j,5]), 'reason': 'off grid', 'residual': [float(ex[j]), float(ey[j])]})
            continue
        key = (int(li[j]), int(ci[j]))
        cell = cells.setdefault(key, {'bits': [0]*6, 'detections': [], 'scores': [], 'residuals': []})
        bit = int(col[j]*3 + row[j])
        cell['bits'][bit] = 1
        cell['detections'].append(int(data[j,5]))
        cell['scores'].append(float(data[j,4]))
        cell['residuals'].append([float(ex[j]), float(ey[j])])
    codes, output_cells = [], []
    if cells:
        min_line, max_line = min(k[0] for k in cells), max(k[0] for k in cells)
        if max_line-min_line > 500:
            raise ValueError('Implausible line count')
        for line in range(min_line, max_line+1):
            occupied = [k[1] for k in cells if k[0] == line]
            if occupied:
                lo, hi = min(occupied), max(occupied)
                if hi-lo+1 > cfg.max_cells_per_line:
                    raise ValueError('Implausible cell count; verify pitch')
                for c in range(lo,hi+1):
                    entry = cells.get((line,c))
                    code = ''.join(map(str,entry['bits'])) if entry else '000000'
                    # Return predicted original-image dot positions for an overlay.
                    sites = np.array([[x0+c*px+column*dx, y0+line*py+r*dy] for column in range(2) for r in range(3)]) @ rotation.T
                    output_cells.append({'line': line-min_line, 'column': c-lo, 'grid_column': c,
                        'code': code, 'token_index': len(codes), 'sites': sites.tolist(),
                        'detections': entry['detections'] if entry else [],
                        'min_score': min(entry['scores']) if entry else None,
                        'residuals': entry['residuals'] if entry else []})
                    codes.append(code)
            codes.append('\n')
    return {'codes': codes, 'cells': output_cells, 'warnings': warnings, 'rejected': rejected,
            'grid': {'angle_degrees': float(angle), 'x_origin': x0, 'y_origin': y0,
                     'column_spacing': dx, 'row_spacing': dy, 'cell_pitch': px, 'line_pitch': py,
                     'x_fit_error': xs, 'y_fit_error': ys, 'accepted_fraction': float(np.mean(good))},
            'config': asdict(cfg)}


def group_dots(yolo_outputs: list, img_width: int, img_height: int) -> list:
    return group_dots_detailed(yolo_outputs, img_width, img_height)['codes']

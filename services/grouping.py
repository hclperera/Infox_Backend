"""Regular six-dot lattice reconstruction with explicit calibration and diagnostics.

Revision 6: optional guarded bends within lines and classification recovery.
Requires numpy and scipy. Coordinates are normalized YOLO class,x,y,w,h[,score].
The public group_dots signature is unchanged. Use group_dots_detailed to inspect
uncertainty. Severe curvature or perspective can still require image rectification.
"""
from dataclasses import dataclass, asdict
import os
import logging
import numpy as np
from scipy.spatial import cKDTree

GROUPING_VERSION = "2026-10-08-r6"
_logger = logging.getLogger(__name__)


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
    fit_mode: str = "auto"  # auto, regular, or warped
    cell_pitch_bounds: tuple = (2.05, 3.5)  # pitch / within-cell column spacing
    line_pitch_bounds: tuple = (3.5, 5.5)  # pitch / within-cell row spacing
    max_spacing_to_diameter: float = 2.5
    min_accepted_fraction: float = .90
    refine_lines: bool = False  # Experimental; opt in after reviewing real-page text.
    refine_segments: bool = False  # Guarded local bends within a refined line.
    recover_back_dots: bool = False
    back_class_id: int = 1


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


def _fit_axis(values, slots, diameter, spacing=None, pitch=None, origin=None,
              pitch_bounds=None, max_spacing_to_diameter=2.5, refine_spacing=False):
    spacing_given = spacing is not None and not refine_spacing
    levels = _clusters(values, diameter * .45)
    gaps = np.diff(levels)
    if spacing is None:
        if len(gaps) < slots-1:
            raise ValueError('Too little grid evidence; supply spacing, pitch and origin calibration')
        spacing = float(np.percentile(gaps, 20))
        if spacing > diameter * max_spacing_to_diameter:
            raise ValueError('Observed gaps do not establish within-cell dot spacing; supply calibration')
    if spacing <= 0 or not np.isfinite(spacing):
        raise ValueError('Grid spacing must be positive and finite')
    if pitch is not None and (not np.isfinite(pitch) or pitch <= (slots-1)*spacing):
        raise ValueError('Grid pitch must exceed the span of its dot slots')
    if origin is not None and not np.isfinite(origin):
        raise ValueError('Grid origin must be finite')
    # A complete isolated cell/line establishes its slots but not repetition.
    # The provisional period cannot merge another line: all observed levels
    # must fit inside this one slot span. Partial rows remain ambiguous.
    if pitch is None and len(levels) == slots:
        step = spacing if spacing_given else float(np.median(gaps))
        if np.max(np.abs(gaps-step)) <= .15*step:
            start = float(levels[0]) if origin is None else float(origin)
            bounds = pitch_bounds or ((2.05, 3.5) if slots == 2 else (3.5, 5.5))
            period = step*float(np.clip(2.4 if slots == 2 else 4., *bounds))
            _, _, residual = _assign(values,start,step,period,slots)
            return start, step, period, float(np.mean((residual/step)**2))
    # Candidate periods come from actual level differences, not box widths.
    if pitch is None:
        low, high = pitch_bounds or ((2.05, 3.5) if slots == 2 else (3.5, 5.5))
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
                if pitch is None and not low <= new_period/new_gap <= high:
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


def _features(points, center, span):
    u, v = ((points-center)/span).T
    return np.column_stack([np.ones(len(points)), u, v, u*u, u*v, v*v,
                            u**3, u*u*v, u*v*v, v**3, u**4,u**3*v,u*u*v*v,u*v**3,v**4])


def _feature_derivatives(points, center, span):
    u, v = ((points-center)/span).T
    z, o = np.zeros(len(points)), np.ones(len(points))
    fx = np.column_stack([z,o,z,2*u,v,z,3*u*u,2*u*v,v*v,z,4*u**3,3*u*u*v,2*u*v*v,v**3,z])/span[0]
    fy = np.column_stack([z,z,o,z,u,2*v,z,u*u,2*u*v,3*v*v,z,u**3,2*u*u*v,3*u*v*v,4*v**3])/span[1]
    return fx, fy


def _local_spacings(points, diameter):
    """Estimate local steps from nearby near-horizontal/vertical pairs."""
    from scipy.ndimage import gaussian_filter1d
    _, neighbors = cKDTree(points).query(points, k=min(12,len(points)))
    delta = np.abs(points[neighbors[:,1:]]-points[:,None,:])
    steps = []
    for axis in (0,1):
        along, across = delta[:,:,axis], delta[:,:,1-axis]
        distances = along[(along>.8*diameter)&(along<2.2*diameter)&(across<.4*diameter)]
        if len(distances)<20:
            raise ValueError('Too few local pairs to estimate a curved-page grid')
        counts, edges = np.histogram(distances,bins=np.linspace(.8*diameter,2.2*diameter,90))
        peak_index = np.argmax(gaussian_filter1d(counts.astype(float),2))
        peak = (edges[peak_index]+edges[peak_index+1])/2
        steps.append(float(np.median(distances[np.abs(distances-peak)<.12*diameter])))
    return steps


def _warp_axis(points, axis, diameter, spacing, center, span, train, pitch_bounds=None, tolerance=.28):
    """Grow a local grid into a smooth page warp, without using language scores."""
    features = _features(points,center,span)
    best = None
    # A heading, blank paragraph gap or curvature at the page center must not
    # determine the entire reconstruction. Try distributed, measured seeds.
    seeds = [(center, f) for f in (.20, .28, .36)]
    seeds += [(center + span*np.array(offset), .32)
              for offset in ((-.2,-.2),(.2,-.2),(-.2,.2),(.2,.2),(0.,-.25),(0.,.25))]
    for anchor, seed_fraction in seeds:
        seed = np.all(np.abs(points-anchor)<span*seed_fraction/2,axis=1)&train
        if np.sum(seed)<24:
            continue
        try:
            origin, step, period, error = _fit_axis(points[seed,axis],axis+2,diameter,
                                                  spacing=spacing, pitch_bounds=pitch_bounds,
                                                  refine_spacing=True)
        except ValueError:
            continue
        if error > .045:
            continue
        ratio = period/step
        coeff = np.zeros(15)
        coeff[0] = (center[axis]-origin)/step
        coeff[axis+1] = span[axis]/step
        for fraction in np.linspace(seed_fraction,1.65,40):
            region = np.all(np.abs(points-anchor)<span*fraction/2,axis=1)&train
            count = 6 if fraction<.45 else (10 if fraction<.70 else 15)
            for _ in range(6):
                indices, slots, residual = _assign(features@coeff,0.,1.,ratio,axis+2)
                good = region&(np.abs(residual)<.32)
                if np.sum(good)<max(20,3*count):
                    break
                matrix = features[good,:count]
                if np.linalg.matrix_rank(matrix)<count:
                    break
                regularizer = np.zeros((count-3,count))
                regularizer[:,3:] = np.eye(count-3)*.03
                target = slots[good]+indices[good]*ratio
                fitted = np.linalg.lstsq(np.vstack([matrix,regularizer]),
                                        np.r_[target,np.zeros(count-3)],rcond=None)[0]
                candidate = coeff.copy(); candidate[:count] = fitted
                fx, fy = _feature_derivatives(points[region],center,span)
                derivative = (fx if axis==0 else fy)@candidate
                if len(derivative) and (np.min(derivative)<.5/spacing or np.max(derivative)>1.6/spacing):
                    break
                coeff = candidate
        # Select by evidence outside the seed, including the held-out dots.
        _, _, residual = _assign(features@coeff,0.,1.,ratio,axis+2)
        gx, gy = np.meshgrid(np.linspace(points[:,0].min(),points[:,0].max(),8),
                             np.linspace(points[:,1].min(),points[:,1].max(),8))
        probes = np.column_stack([gx.ravel(),gy.ravel()])
        fx, fy = _feature_derivatives(probes,center,span)
        derivative = (fx if axis==0 else fy)@coeff
        if np.min(derivative)<.5/spacing or np.max(derivative)>1.6/spacing:
            continue
        score = float(np.mean(np.minimum(residual[train]**2,.25)))
        accepted = float(np.mean(np.abs(residual[train])<=tolerance))
        candidate_key = (-accepted, score)
        if best is None or candidate_key < best[0]:
            best = (candidate_key, coeff, ratio)
        if accepted > .98:
            break
    if best is None:
        raise ValueError('No spatial seed establishes a reliable grid; supply calibration or rectify the page')
    return best[1], best[2]


def _fit_warp(points, diameter, tolerance, config=None):
    if len(points)<120:
        raise ValueError('Curved-page fitting needs at least 120 retained dots; use measured calibration for sparse text')
    center = np.median(points,axis=0)
    span = np.ptp(points,axis=0)
    if np.min(span)<8*diameter:
        raise ValueError('Insufficient page coverage for curved-page fitting')
    steps = _local_spacings(points,diameter)
    # A spatially distributed 20% is excluded from parameter fitting.
    order = np.lexsort((points[:,1],points[:,0]))
    train = np.ones(len(points),dtype=bool);train[order[::5]]=False
    bounds = (config.cell_pitch_bounds, config.line_pitch_bounds) if config else (None, None)
    fits = [_warp_axis(points,ax,diameter,steps[ax],center,span,train,bounds[ax],tolerance) for ax in (0,1)]
    coefficients = np.array([f[0] for f in fits]).T
    ratios = np.array([f[1] for f in fits])
    latent = _features(points,center,span)@coefficients
    nx,c,ex = _assign(latent[:,0],0.,1.,ratios[0],2)
    ny,r,ey = _assign(latent[:,1],0.,1.,ratios[1],3)
    good = (np.abs(ex)<=tolerance)&(np.abs(ey)<=tolerance)
    held_out = float(np.mean(good[~train]))
    # Reject folding/scale collapse across the entire supported page rectangle.
    gx,gy = np.meshgrid(np.linspace(points[:,0].min(),points[:,0].max(),12),
                        np.linspace(points[:,1].min(),points[:,1].max(),12))
    probes = np.column_stack([gx.ravel(),gy.ravel()])
    fx,fy = _feature_derivatives(probes,center,span)
    jx,jy = fx@coefficients,fy@coefficients
    determinant = jx[:,0]*jy[:,1]-jy[:,0]*jx[:,1]
    if (np.min(determinant)<=0 or np.min(jx[:,0])<.5/steps[0]
            or np.max(jx[:,0])>1.6/steps[0] or np.min(jy[:,1])<.5/steps[1]
            or np.max(jy[:,1])>1.6/steps[1]):
        raise ValueError('Curved-page fit would fold or distort the grid excessively')
    local = None
    local_quality = None
    if config is None or config.refine_lines or config.refine_segments:
        from services.line_refinement import refine_lines
        coarse = {'center':center.tolist(),'span':span.tolist(),'coefficients':coefficients.tolist()}
        def coarse_sites(q, rows, line):
            return _warp_sites(np.column_stack([q,line*ratios[1]+rows]),coarse)
        try:
            candidate = refine_lines(points,nx,c,ny,r,good,train,ratios,steps,tolerance,coarse_sites,
                                     refine_segments=bool(config and config.refine_segments))
        except (ValueError, np.linalg.LinAlgError) as error:
            # Optional refinement must not invalidate an otherwise usable fit.
            candidate = None
            local_quality = {'rejected_reason': str(error)}
        if candidate is not None:
            old_loss = np.minimum(np.sum(candidate['coarse_physical_residual']**2,axis=1),.5)
            new_loss = np.minimum(candidate['ex']**2+candidate['ey']**2,.5)
            local_quality = {'accepted_fraction':float(np.mean(candidate['good'])),
                             'held_out_accepted_fraction':candidate['held_out_accepted_fraction'],
                             'old_residual_loss':float(np.mean(old_loss)),
                             'new_residual_loss':float(np.mean(new_loss))}
            local_quality.update(old_validation_loss=float(np.mean(old_loss[~train])),
                                 new_validation_loss=float(np.mean(new_loss[~train])))
            improved = (np.mean(candidate['good']) > np.mean(good)+.003 or
                        (np.mean(candidate['good']) >= np.mean(good)-.005
                         and np.mean(new_loss[train]) < np.mean(old_loss[train])
                         # Forward/inverse polynomial approximation can differ
                         # below a tenth of a pixel at typical dot spacing.
                         and np.mean(new_loss[~train]) <= np.mean(old_loss[~train])+1e-5))
            if improved and candidate['held_out_accepted_fraction'] >= held_out-.005:
                local = candidate
                nx,c,ny,r = (candidate[k] for k in ('ci','col','li','row'))
                ex,ey,good = (candidate[k] for k in ('ex','ey','good'))
                held_out = candidate['held_out_accepted_fraction']
    minimum = config.min_accepted_fraction if config else .90
    if np.mean(good)<minimum or held_out<minimum:
        raise ValueError(f'Curved-page grid remains unreliable (all dots {np.mean(good):.1%}, held-out {held_out:.1%})')
    meta = {'center':center.tolist(),'span':span.tolist(),'coefficients':coefficients.tolist(),
            'periods_in_dot_steps':ratios.tolist(),'local_spacing_px':steps,
            'held_out_accepted_fraction':held_out,'held_out_count':int(np.sum(~train))}
    if local is not None:
        meta['line_models'] = local['models']
        meta['locally_reassigned_dots'] = local['changed_assignments']
    meta['line_refinement_candidate'] = local_quality
    return nx,c,ex,ny,r,ey,good,meta


def _warp_sites(targets, warp):
    """Invert the smooth coordinate map for diagnostic site overlays."""
    coeff = np.asarray(warp['coefficients'])
    center,span = np.asarray(warp['center']),np.asarray(warp['span'])
    uv = (targets-coeff[0])@np.linalg.inv(coeff[1:3])
    points = center+uv*span
    for _ in range(15):
        error = _features(points,center,span)@coeff-targets
        if np.max(np.abs(error))<1e-7:
            break
        fx,fy = _feature_derivatives(points,center,span)
        jx,jy = fx@coeff,fy@coeff
        matrices = np.stack([jx,jy],axis=2)
        try:
            change = np.linalg.solve(matrices,error[...,None])[...,0]
        except np.linalg.LinAlgError:
            raise ValueError('Could not invert fitted grid for the diagnostic overlay') from None
        points -= change
    if not np.all(np.isfinite(points)) or np.max(np.abs(_features(points,center,span)@coeff-targets))>.01:
        raise ValueError('Could not locate fitted cell sites reliably')
    return points


def group_dots_detailed(yolo_outputs, img_width, img_height, *, config=None):
    cfg = config or GridConfig(front_class_id=int(os.getenv('FRONT_CLASS_ID', '2')))
    if img_width <= 0 or img_height <= 0:
        raise ValueError('Image dimensions must be positive')
    if not 0 < cfg.tolerance < .5:
        raise ValueError('Grid tolerance must lie between 0 and 0.5')
    for slots, bounds in ((2, cfg.cell_pitch_bounds), (3, cfg.line_pitch_bounds)):
        if len(bounds) != 2 or not np.all(np.isfinite(bounds)) or not slots-1 < bounds[0] < bounds[1]:
            raise ValueError('Pitch bounds must be finite, ordered and exceed the dot-slot span')
    if not np.isfinite(cfg.max_spacing_to_diameter) or cfg.max_spacing_to_diameter <= 0:
        raise ValueError('Maximum spacing-to-diameter ratio must be positive and finite')
    if not .5 < cfg.min_accepted_fraction <= 1:
        raise ValueError('Minimum accepted fraction must lie above 0.5 and at most 1')
    if cfg.recover_back_dots and cfg.back_class_id == cfg.front_class_id:
        raise ValueError('Front and back class IDs must differ for classification recovery')
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
    if cfg.fit_mode not in ('auto','regular','warped'):
        raise ValueError('fit_mode must be auto, regular or warped')
    warp = None
    regular_error = None
    calibrated = any(getattr(cfg,k) is not None for k in (
        'column_spacing','row_spacing','cell_pitch','line_pitch','x_origin','y_origin'))
    try:
        if cfg.fit_mode == 'warped':
            raise ValueError('Smooth page fitting explicitly selected')
        x0, dx, px, xs = _fit_axis(flat[:,0], 2, diameter, cfg.column_spacing, cfg.cell_pitch, cfg.x_origin,
                                  cfg.cell_pitch_bounds, cfg.max_spacing_to_diameter)
        y0, dy, py, ys = _fit_axis(flat[:,1], 3, diameter, cfg.row_spacing, cfg.line_pitch, cfg.y_origin,
                                  cfg.line_pitch_bounds, cfg.max_spacing_to_diameter)
        ci, col, ex = _assign(flat[:,0], x0, dx, px, 2)
        li, row, ey = _assign(flat[:,1], y0, dy, py, 3)
        good = (np.abs(ex) <= dx*cfg.tolerance) & (np.abs(ey) <= dy*cfg.tolerance)
        if np.mean(good)<cfg.min_accepted_fraction:
            raise ValueError(f'Poor regular-grid fit ({np.mean(good):.1%} accepted; requires {cfg.min_accepted_fraction:.0%})')
    except ValueError as error:
        if cfg.fit_mode == 'regular' or calibrated:
            raise
        regular_error = str(error)
        ci,col,ex,li,row,ey,good,warp = _fit_warp(flat,diameter,cfg.tolerance,cfg)
        x0=y0=0.;dx=dy=1.
        px,py=warp['periods_in_dot_steps']
        xs,ys=float(np.mean(np.minimum(ex**2,.25))),float(np.mean(np.minimum(ey**2,.25)))
        warnings.append('Used a smooth page warp after the regular grid failed; inspect cell boundaries')
    if cfg.x_origin is None or cfg.y_origin is None:
        warnings.append('Automatically inferred lattice; verify its overlay before trusting sparse text')
    if warp is None and (np.ptp(flat[:,0]) <= 1.3*dx or np.ptp(flat[:,1]) <= 2.3*dy):
        warnings.append('Isolated cell or line: repetition pitch is provisional; verify sparse text')
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
                    sites = np.array([[x0+c*px+column*dx, y0+line*py+r*dy] for column in range(2) for r in range(3)])
                    reference_sites = None
                    if warp is not None and str(line) in warp.get('line_models',{}):
                        reference_sites = (_warp_sites(sites,warp) @ rotation.T).tolist()
                        from services.line_refinement import line_sites
                        model = warp['line_models'][str(line)]
                        sites = line_sites(np.array([c*px+column for column in range(2) for _ in range(3)]),
                                           np.array([r for _ in range(2) for r in range(3)]),model)
                    elif warp is not None:
                        sites = _warp_sites(sites,warp)
                    sites = sites @ rotation.T
                    output_cells.append({'line': line-min_line, 'column': c-lo, 'grid_column': c,
                        'code': code, 'token_index': len(codes), 'sites': sites.tolist(),
                        'coarse_sites': reference_sites,
                        'detections': entry['detections'] if entry else [],
                        'min_score': min(entry['scores']) if entry else None,
                        'residuals': entry['residuals'] if entry else []})
                    codes.append(code)
            codes.append('\n')
    result = {'version': GROUPING_VERSION, 'codes': codes, 'cells': output_cells, 'warnings': warnings, 'rejected': rejected,
            'grid': {'fit_type': 'warped' if warp is not None else 'regular',
                     'coordinate_units': 'dot steps' if warp is not None else 'pixels',
                     'warp': warp, 'regular_fit_failure': regular_error,
                     'angle_degrees': float(angle), 'x_origin': x0, 'y_origin': y0,
                     'column_spacing': dx, 'row_spacing': dy, 'cell_pitch': px, 'line_pitch': py,
                     'x_fit_error': xs, 'y_fit_error': ys, 'accepted_fraction': float(np.mean(good))},
            'config': asdict(cfg)}
    if cfg.recover_back_dots:
        from services.dot_recovery import recover_back_dots
        result = recover_back_dots(result,yolo_outputs,img_width,img_height,back_class_id=cfg.back_class_id)
    if cfg.refine_segments:
        result['requires_review'] = True
        result['warnings'].append('Experimental within-line bend refinement requested; review text before use')
    return result


def group_dots(yolo_outputs: list, img_width: int, img_height: int) -> list:
    result = group_dots_detailed(yolo_outputs, img_width, img_height)
    grid = result.get('grid')
    if grid is not None:
        _logger.info('Grouping %s: %s fit, accepted=%.1f%%, excluded=%d, lines=%d',
                     GROUPING_VERSION, grid['fit_type'], 100*grid['accepted_fraction'],
                     len(result['rejected']), result['codes'].count('\n'))
    for warning in result['warnings']:
        _logger.warning('Grouping: %s', warning)
    return result['codes']

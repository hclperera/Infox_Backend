"""Refine a coarse Braille grid with independently curved text lines.

Fits use dot geometry only. Held-out dots never enter the least-squares fit.
The coarse grid supplies cell identities; this stage does not invent dots.
"""
import numpy as np
from scipy.spatial import cKDTree


def _basis(q, row, center, scale):
    u = (np.asarray(q)-center)/scale
    v = np.asarray(row)-1.
    return np.column_stack([np.ones(len(u)), u, u*u, u*u*u, v, u*v])


def line_sites(q, row, model):
    sites = _basis(q, row, model['center'], model['scale']) @ np.asarray(model['coefficients'])
    if 'bend_knots' in model:
        offsets = np.asarray(model['bend_offsets'])
        sites += np.column_stack([np.interp(q,model['bend_knots'],offsets[:,axis]) for axis in (0,1)])
    return sites


def _segmented_candidate(points, q, rows, model, steps, ratio):
    """Small, regularized local bends; fitting data only, no word evidence."""
    if len(q) < 30 or np.ptp(q) < 8*ratio:
        return None
    knots = np.linspace(q.min(),q.max(),min(8,int(np.ptp(q)/(4*ratio))+2))
    design = np.column_stack([np.interp(q,knots,np.eye(len(knots))[i]) for i in range(len(knots))])
    # Every local segment needs several spatial anchors, not a single outlier.
    if np.min(np.sum(design,axis=0)) < 5:
        return None
    residual = points-line_sites(q,rows,model)
    weights = np.ones(len(q))
    penalty = np.vstack([np.eye(len(knots))*.5,np.diff(np.eye(len(knots)),n=2,axis=0)*2.])
    for _ in range(4):
        offsets = np.linalg.lstsq(np.vstack([design*np.sqrt(weights[:,None]),penalty]),
                                 np.vstack([residual*np.sqrt(weights[:,None]),np.zeros((len(penalty),2))]),rcond=None)[0]
        error = np.linalg.norm((design@offsets-residual)/steps,axis=1)
        weights = np.minimum(1.,.12/np.maximum(error,1e-8))
    if np.max(np.abs(offsets/steps)) > .22:
        return None
    return dict(model,bend_knots=knots.tolist(),bend_offsets=offsets.tolist())


def _valid_model(model, steps, lo, hi):
    if 'bend_knots' in model:
        # Probe both sides of each linear-spline join as well as the full span.
        qs = np.unique(np.r_[np.linspace(lo,hi,100),np.asarray(model['bend_knots'])-.001,np.asarray(model['bend_knots'])+.001])
        for row in (0.,1.,2.):
            rows = np.full(len(qs),row)
            dq = (line_sites(qs+.0001,rows,model)-line_sites(qs-.0001,rows,model))/.0002
            dr = line_sites(qs,rows+.5,model)-line_sites(qs,rows-.5,model)
            if (np.min(dq[:,0]) < .55*steps[0] or np.max(dq[:,0]) > 1.6*steps[0]
                    or np.min(dr[:,1]) < .55*steps[1] or np.max(dr[:,1]) > 1.6*steps[1]
                    or np.min(dq[:,0]*dr[:,1]-dq[:,1]*dr[:,0]) <= 0):
                return False
        return True
    u = (np.linspace(lo,hi,24)-model['center'])/model['scale']
    c = np.asarray(model['coefficients'])
    for row in (-1.,0.,1.):
        dq = (c[1]+2*u[:,None]*c[2]+3*u[:,None]**2*c[3]+row*c[5])/model['scale']
        dr = c[4]+u[:,None]*c[5]
        if (np.min(dq[:,0]) < .55*steps[0] or np.max(dq[:,0]) > 1.6*steps[0]
                or np.min(dr[:,1]) < .55*steps[1] or np.max(dr[:,1]) > 1.6*steps[1]
                or np.min(dq[:,0]*dr[:,1]-dq[:,1]*dr[:,0]) <= 0):
            return False
    return True


def _evidence(points, model, ratio, steps, tolerance):
    ids = np.array([(cell,column,r) for cell in range(model['min_cell'],model['max_cell']+1)
                    for column in range(2) for r in range(3)])
    sites = line_sites(ids[:,0]*ratio+ids[:,1],ids[:,2],model)
    _, nearest = cKDTree(sites/steps).query(points/steps)
    residual = (points-sites[nearest])/steps
    loss = np.minimum(np.sum(residual**2,axis=1),.5)
    good = np.all(np.abs(residual)<=tolerance,axis=1)
    return loss,good


def refine_lines(points, ci, col, li, row, good, train, ratios, steps, tolerance, coarse_sites, *, refine_segments=False):
    """Return local models and reassigned dots, or None if evidence is too weak."""
    points = np.asarray(points)
    models = {}
    original = (ci.copy(),col.copy(),li.copy(),row.copy())
    original_good = good.copy()
    steps = np.asarray(steps)
    for line in np.unique(li[good]):
        mask = (li == line)&good
        lower,upper = int(ci[mask].min())-1,int(ci[mask].max())+1
        if upper-lower > 300:
            return None
        q,r = np.meshgrid(np.linspace(lower*ratios[0],upper*ratios[0]+1,12),np.arange(3))
        q,r = q.ravel(),r.ravel()
        center,scale = float(np.median(q)),max(float(np.ptp(q)),1.)
        coeff = np.linalg.lstsq(_basis(q,r,center,scale),coarse_sites(q,r,int(line)),rcond=None)[0]
        models[int(line)] = {'center':center,'scale':scale,'coefficients':coeff.tolist(),
                             'min_cell':lower,'max_cell':upper,'training_dots':0}
    for iteration in range(5):
        fitted = dict(models)
        for line in models:
            mask = (li == line)&good&train
            if np.sum(mask) < 12 or len(np.unique(ci[mask])) < 4 or len(np.unique(row[mask])) < 2:
                continue
            q = ci[mask]*ratios[0]+col[mask]
            center, scale = float(np.median(q)), max(float(np.ptp(q)),1.)
            design = _basis(q,row[mask],center,scale)
            if np.linalg.matrix_rank(design) < 6:
                continue
            target = points[mask]
            weights = np.ones(len(q))
            coeff = None
            # Limit the influence of isolated wrong-class/off-grid detections.
            for _ in range(5):
                weighted = design*np.sqrt(weights[:,None])
                # Stabilize cubic extrapolation at short/sparse line ends.
                prior = np.linalg.lstsq(design,line_sites(q,row[mask],models[line]),rcond=None)[0]
                penalty = np.diag([0.,0.,.02,.04,0.,.02])
                coeff = np.linalg.lstsq(np.vstack([weighted,penalty]),
                    np.vstack([target*np.sqrt(weights[:,None]),penalty@prior]),rcond=None)[0]
                residual = np.linalg.norm((design@coeff-target)/steps,axis=1)
                weights = np.minimum(1., .15/np.maximum(residual,1e-8))
            # Only modest extrapolation beyond the supported text extent.
            lower, upper = int(ci[mask].min())-1,int(ci[mask].max())+1
            if upper-lower > 300:
                continue
            model = {'center':center,'scale':scale,'coefficients':coeff.tolist(),
                     'min_cell':lower,'max_cell':upper,'training_dots':int(np.sum(mask))}
            candidates = [model]
            if refine_segments:
                segmented = _segmented_candidate(target,q,row[mask],model,steps,ratios[0])
                if segmented is not None:
                    candidates.append(segmented)
            for model in candidates:
                if not _valid_model(model,steps,lower*ratios[0],upper*ratios[0]+1):
                    continue
                check = li == line
                held = ~train[check]
                if np.sum(held) < 3:
                    continue
                before,old_good = _evidence(points[check],fitted[line],ratios[0],steps,tolerance)
                after,new_good = _evidence(points[check],model,ratios[0],steps,tolerance)
                if (np.mean(after[~held]) < .95*np.mean(before[~held])
                        and np.mean(after[held]) <= np.mean(before[held])*(.95 if 'bend_knots' in model else 1.)
                        and np.sum(new_good[held]) >= np.sum(old_good[held])):
                    fitted[int(line)] = model
        if not fitted:
            return None
        sites, identities = [], []
        for line, model in fitted.items():
            ids = np.array([(cell,column,r) for cell in range(model['min_cell'],model['max_cell']+1)
                            for column in range(2) for r in range(3)])
            sites.append(line_sites(ids[:,0]*ratios[0]+ids[:,1],ids[:,2],model))
            identities.extend((cell,column,line,r) for cell,column,r in ids)
        sites = np.vstack(sites)
        identities = np.asarray(identities)
        _, nearest = cKDTree(sites/steps).query(points/steps)
        ci,col,li,row = identities[nearest].T
        residual = (points-sites[nearest])/steps
        good = np.all(np.abs(residual)<=tolerance,axis=1)
        models = fitted
    # Avoid flipping a previously accepted dot merely because the new curve
    # puts it just across the tolerance boundary. Compare both fits in the
    # same physical units; the coarse inverse-map residual uses another scale.
    old_residual = np.zeros_like(points)
    for line in np.unique(original[2]):
        mask = original[2] == line
        old_residual[mask] = (points[mask]-coarse_sites(
            original[0][mask]*ratios[0]+original[1][mask],original[3][mask],int(line)))/steps
    same = np.all(np.column_stack(original)==np.column_stack([ci,col,li,row]),axis=1)
    retain = (original_good & same & (np.max(np.abs(old_residual),axis=1)<=tolerance)
              & (np.max(np.abs(residual),axis=1)<=tolerance+.03))
    good |= retain
    # Reject fits that map several non-duplicate dots to the same physical site.
    occupied = np.column_stack([ci,col,li,row])[good]
    collisions = len(occupied)-len(np.unique(occupied,axis=0))
    if collisions > max(2, .01*np.sum(good)):
        return None
    # Local correction must not rewrite the confident interior grid wholesale.
    changed = np.any(np.column_stack(original) != np.column_stack([ci,col,li,row]),axis=1)
    if np.mean(changed[good]) > .20:
        return None
    return {'models':{str(k):v for k,v in models.items()},'ci':ci,'col':col,'li':li,'row':row,
            'ex':residual[:,0],'ey':residual[:,1],'good':good,
            'held_out_accepted_fraction':float(np.mean(good[~train])),
            'changed_assignments':int(np.sum(changed&good)),
            'coarse_physical_residual':old_residual}

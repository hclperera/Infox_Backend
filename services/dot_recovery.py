"""Optional, auditable recovery of back-labelled detections on front dot sites.

No text or dictionary is used. Only partially occupied cells with nearby front
anchors are eligible; empty cells and unmatched image features remain untouched.
"""
import numpy as np
from scipy.spatial import cKDTree


def recover_back_dots(result, detections, width, height, *, back_class_id=1, tolerance=.18):
    candidates=[]
    for index,values in enumerate(detections):
        a=np.asarray(values,dtype=float)
        if len(a) not in (5,6) or not np.all(np.isfinite(a)):
            continue
        if a[0]!=back_class_id or not (0<=a[1]<=1 and 0<=a[2]<=1):
            continue
        if not (0<a[3]<=1 and 0<a[4]<=1):
            continue
        size=a[3:5]*[width,height]
        if max(size)/min(size)>2.2:
            continue
        candidates.append((index,a[1]*width,a[2]*height))
    result['recovered_dots']=[]
    result['raw_codes']=list(result['codes'])
    result['requires_review']=True
    if not candidates or not result.get('cells'):
        return result
    candidates=np.asarray(candidates)
    tree=cKDTree(candidates[:,1:])
    used=set()
    original={c['token_index']:c['code'] for c in result['cells']}
    for cell in result['cells']:
        if original[cell['token_index']]=='000000':
            continue
        neighbors=[c for c in result['cells'] if c['line']==cell['line']
                   and abs(c['grid_column']-cell['grid_column'])<=2]
        anchors=[r for c in neighbors for r in c['residuals']]
        if len(anchors)<8:
            continue
        # Residuals in regular fits use pixels; warped fits use dot steps.
        scale=np.array([result['grid']['column_spacing'],result['grid']['row_spacing']])
        if np.median(np.max(np.abs(np.asarray(anchors)/scale),axis=1))>.15:
            continue
        sites=np.asarray(cell['sites'])
        frame=np.column_stack([np.mean(sites[3:]-sites[:3],axis=0),
                               np.mean([sites[2]-sites[0],sites[5]-sites[3]],axis=0)/2])
        if abs(np.linalg.det(frame))<1e-8:
            continue
        reference=cell.get('coarse_sites')
        reference_frame=None
        if reference is not None:
            reference=np.asarray(reference)
            reference_frame=np.column_stack([np.mean(reference[3:]-reference[:3],axis=0),
                np.mean([reference[2]-reference[0],reference[5]-reference[3]],axis=0)/2])
        radius=.28*np.linalg.norm(frame,axis=0).sum()
        bits=list(cell['code'])
        for bit,present in enumerate(bits):
            if present=='1':
                continue
            found=[]
            for i in tree.query_ball_point(sites[bit],radius):
                if int(candidates[i,0]) in used:
                    continue
                residual=np.linalg.solve(frame,candidates[i,1:]-sites[bit])
                supported=np.max(np.abs(residual))<=tolerance
                if reference_frame is not None and np.max(np.abs(residual))<=.28:
                    coarse_residual=np.linalg.solve(reference_frame,candidates[i,1:]-reference[bit])
                    supported |= np.max(np.abs(coarse_residual))<=tolerance
                if supported:
                    found.append((i,residual))
            if len(found)!=1:
                continue
            i,residual=found[0]
            index=int(candidates[i,0]);used.add(index)
            bits[bit]='1'
            result['recovered_dots'].append({'detection':index,'line':cell['line'],
                'column':cell['column'],'token_index':cell['token_index'],'dot':bit+1,
                'original_class':back_class_id,'residual':residual.tolist(),
                'support':'local' if np.max(np.abs(residual))<=tolerance else 'coarse_and_local'})
        if ''.join(bits)!=cell['code']:
            cell['original_code']=cell['code']
            cell['code']=''.join(bits)
            result['codes'][cell['token_index']]=cell['code']
            cell['requires_review']=True
    if result['recovered_dots']:
        result['warnings'].append(f"Recovered {len(result['recovered_dots'])} back-labelled dots on front sites; classification recovery requires review")
    return result

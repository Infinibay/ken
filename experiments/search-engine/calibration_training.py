"""Whole-query exclusion and type-balanced weights for development calibration."""
import numpy as np

def training_selection(qids,repos,kinds,labels,*,held_out):
    arrays=[np.asarray(a) for a in (qids,repos,kinds,labels)]
    if any(a.ndim!=1 or a.shape!=arrays[0].shape for a in arrays) or not np.isin(labels,[0,1]).all():
        raise ValueError('aligned binary query rows required')
    qids,repos,kinds,labels=arrays
    if held_out is not None and held_out not in set(repos):raise ValueError('unknown held-out repository')
    selected=[]
    for qid in dict.fromkeys(qids):
        ix=np.flatnonzero(qids==qid)
        if len(set(repos[ix]))!=1 or len(set(kinds[ix]))!=1:raise ValueError('query has mixed repository or piece kind')
        if repos[ix[0]]==held_out or not (labels[ix].any() and (labels[ix]==0).any()):continue
        selected.append(ix)
    mask=np.zeros(len(qids),dtype=bool)
    weights=np.zeros(len(qids))
    counts={kind:sum(kinds[ix[0]]==kind for ix in selected) for kind in set(kinds)}
    for ix in selected:
        mask[ix]=True;weights[ix]=1./(counts[kinds[ix[0]]]*len(ix))
    if not mask.any():raise ValueError('no positive-containing training groups')
    weights=weights[mask];weights/=weights.mean()
    return mask,weights

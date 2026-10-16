"""Candidate-aligned numerical evidence for calibrating existing search scorers.

This module never reads labels, query text or repository identities. It retains
score margins that ordinal rank fusion discards. Every row is one native unit.
"""
from collections.abc import Sequence
import numpy as np
from ken.retrieval.piece_ranking import PIECE_FEATURES
from ken.retrieval.reranker_fusion import fused_reranker_order

_STATS=('raw','to_max','mean_delta','z','reciprocal_rank','gap_top2','winning_margin')
_SOURCE=('request_class','request_module','request_symbol','request_file',
         'request_tests','request_documentation','test_path','data_file')
CALIBRATION_FEATURES=(*(f'{scorer}_{stat}' for scorer in ('native','piece','neural') for stat in _STATS),
    'fusion_reciprocal_rank','native_piece_agreement','native_neural_agreement',
    'piece_neural_agreement','exact',*_SOURCE)
FULL_FEATURES=(*PIECE_FEATURES,*(f'calibration_{f}' for f in CALIBRATION_FEATURES))

def calibration_features(piece_values:np.ndarray,*,piece_order:Sequence[int],
        piece_scores:Sequence[float],neural_scores:Sequence[float],exact:Sequence[float],
        include_source:bool=False)->np.ndarray:
    """Accept model scores in actual piece order; return rows in native order."""
    source=np.asarray(piece_values,dtype=np.float64)
    if source.ndim!=2 or source.shape[1]!=len(PIECE_FEATURES) or not np.isfinite(source).all():
        raise ValueError('finite requested-piece feature matrix required')
    n=len(source)
    if n>10 or len(piece_order)!=n or sorted(piece_order)!=list(range(n)) or any(isinstance(i,(bool,np.bool_)) or not isinstance(i,(int,np.integer)) for i in piece_order):
        raise ValueError('piece order must permute the native top10')
    arrays=[np.asarray(v,dtype=np.float64) for v in (piece_scores,neural_scores,exact)]
    if any(v.shape!=(n,) or not np.isfinite(v).all() for v in arrays):
        raise ValueError('finite candidate-aligned score vectors required')
    if not np.isin(arrays[2],[0.,1.]).all():
        raise ValueError('exact identity flags must be binary')
    if not n:return np.empty((0,len(FULL_FEATURES) if include_source else len(CALIBRATION_FEATURES)))
    order=np.asarray(piece_order,dtype=np.int64)
    scores=[source[:,PIECE_FEATURES.index('native_score')],np.empty(n),np.empty(n)]
    scores[1][order]=arrays[0];scores[2][order]=arrays[1]
    neural_order=order[np.argsort(-arrays[1],kind='stable')]
    orders=[np.arange(n),order,neural_order]
    columns=[];ranks=[]
    for values,positions in zip(scores,orders,strict=True):
        rank=np.empty(n);rank[positions]=np.arange(1,n+1);ranks.append(rank)
        top=np.sort(values)[::-1];best=top[0];second=top[1] if n>1 else best
        competitor=np.where(values==best,second,best)
        std=float(values.std())
        columns.extend((values,values-best,values-values.mean(),
            (values-values.mean())/max(1e-9,std),1/rank,np.full(n,best-second),values-competitor))
    fusion=order[fused_reranker_order(arrays[1])]
    fusion_rank=np.empty(n);fusion_rank[fusion]=np.arange(1,n+1)
    columns.extend((1/fusion_rank,(ranks[0]==ranks[1]).astype(float),
        (ranks[0]==ranks[2]).astype(float),(ranks[1]==ranks[2]).astype(float),arrays[2]))
    columns.extend(source[:,PIECE_FEATURES.index(f)] for f in _SOURCE)
    result=np.column_stack(columns)
    return np.column_stack((source,result)) if include_source else result

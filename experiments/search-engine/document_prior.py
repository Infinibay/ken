"""Query-free controls over precisely the document tokens the scorer saw."""
import numpy as np

def control_tokens(encoded):
    if not (len(encoded.ids)==len(encoded.sequence_ids)==len(encoded.attention_mask)):
        raise ValueError('aligned query/document token provenance required')
    if not any(s==1 and a for s,a in zip(encoded.sequence_ids,encoded.attention_mask)):
        raise ValueError('visible document sequence required')
    return [i for i,s,a in zip(encoded.ids,encoded.sequence_ids,encoded.attention_mask) if a and s!=0]

def conditional_scores(actual,control):
    a=np.asarray(actual,dtype=np.float64);b=np.asarray(control,dtype=np.float64)
    if a.ndim!=1 or a.shape!=b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('finite candidate-aligned scorer values required')
    try:
        with np.errstate(over='raise',invalid='raise'):return a-b
    except FloatingPointError as exc:raise ValueError('finite conditional scores required') from exc

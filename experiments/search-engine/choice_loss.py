"""One probability distribution per query, with exact score derivatives."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class QueryChoiceLoss:
    targets: np.ndarray
    starts: np.ndarray

    def __post_init__(self) -> None:
        y,s=np.asarray(self.targets),np.asarray(self.starts)
        if (y.ndim!=1 or y.dtype.kind not in 'fiu' or not np.isfinite(y).all()
                or np.any(y<0) or s.ndim!=1 or s.dtype.kind not in 'iu' or not len(s)
                or s[0]!=0 or s[-1]>=len(y) or np.any(s[1:]<=s[:-1])):
            raise ValueError('finite query targets and bounded integer group starts required')
        y=np.array(y,dtype=np.float64,copy=True);s=np.array(s,dtype=np.intp,copy=True)
        if not np.isfinite(y).all() or not np.allclose(np.add.reduceat(y,s),1.,rtol=0,atol=1e-12):
            raise ValueError('unit target mass per query required')
        y.setflags(write=False);s.setflags(write=False)
        object.__setattr__(self,'targets',y);object.__setattr__(self,'starts',s)

    def _distribution(self, predictions: np.ndarray) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
        scores=np.asarray(predictions)
        if (scores.shape!=self.targets.shape or scores.dtype.kind not in 'fiu'
                or not np.isfinite(scores).all()):
            raise ValueError('aligned finite real query scores required')
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            try:
                scores=scores.astype(np.float64)
                membership=np.repeat(np.arange(len(self.starts)),np.diff(np.r_[self.starts,len(scores)]))
                shifted=scores-np.maximum.reduceat(scores,self.starts)[membership]
                exponents=np.exp(shifted)
                totals=np.add.reduceat(exponents,self.starts)
                probabilities=exponents/totals[membership]
            except FloatingPointError as exc:
                raise ValueError('finite query score distribution required') from exc
        return probabilities,shifted,totals

    def value(self, predictions: np.ndarray) -> float:
        _,shifted,totals=self._distribution(predictions)
        value=float(np.log(totals).sum()-self.targets@shifted)
        if not np.isfinite(value):
            raise ValueError('finite query loss required')
        return value

    def derivatives(self, predictions: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
        probabilities,_,_=self._distribution(predictions)
        return probabilities-self.targets,probabilities*(1.-probabilities)

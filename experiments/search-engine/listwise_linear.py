"""Equal-query convex ranking, with normalization owned by the training fold."""
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
import numpy as np


def _real(value: object) -> np.ndarray:
    array=np.asarray(value)
    if array.dtype.kind not in 'fiu' or not np.isfinite(array).all():
        raise ValueError('finite real numeric arrays required')
    with np.errstate(over='raise',invalid='raise'):
        try:
            converted=np.asarray(array,dtype=np.float64)
        except FloatingPointError as exc:
            raise ValueError('finite float64 arrays required') from exc
    if not np.isfinite(converted).all():
        raise ValueError('finite float64 arrays required')
    return converted


@dataclass(frozen=True)
class RankGroup:
    repository: str
    query_id: str
    values: np.ndarray
    positive: np.ndarray


class ListwiseFitError(ValueError):
    """Retain the optimizer evidence when a head must not be used."""
    def __init__(self, message: str, diagnostics: dict) -> None:
        super().__init__(message)
        self.diagnostics=diagnostics


@dataclass(frozen=True)
class TrainingLists:
    """One excluded-repository fold's immutable inputs, available for pre-fit audit."""
    values: np.ndarray
    targets: np.ndarray
    starts: np.ndarray
    membership: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    repositories: tuple[str,...]
    query_ids: tuple[str,...]


@dataclass(frozen=True)
class LinearListRanker:
    means: np.ndarray
    scales: np.ndarray
    weights: np.ndarray

    def __post_init__(self) -> None:
        arrays=[_real(v).copy() for v in (self.means,self.scales,self.weights)]
        if (not arrays[0].size or any(v.ndim!=1 or v.shape!=arrays[0].shape for v in arrays)
                or np.any(arrays[1]<=0)):
            raise ValueError('aligned vectors and positive scales required')
        for name,value in zip(('means','scales','weights'),arrays,strict=True):
            value.setflags(write=False)
            object.__setattr__(self,name,value)

    def score(self, values: object) -> np.ndarray:
        x=_real(values)
        if x.ndim!=2 or x.shape[1]!=len(self.weights):
            raise ValueError('matching feature matrix required')
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            try:
                scores=((x-self.means)/self.scales)@self.weights
            except FloatingPointError as exc:
                raise ValueError('finite ranker scores required') from exc
        if not np.isfinite(scores).all():
            raise ValueError('finite ranker scores required')
        return scores

    def to_dict(self) -> dict:
        return {'schema':'linear-list-ranker-v1',**{name:getattr(self,name).tolist()
                for name in ('means','scales','weights')}}

    @classmethod
    def from_dict(cls, value: dict) -> LinearListRanker:
        if set(value)!={'schema','means','scales','weights'} or value['schema']!='linear-list-ranker-v1':
            raise ValueError('registered linear list ranker schema required')
        return cls(*(np.asarray(value[name]) for name in ('means','scales','weights')))


def _objective(w: np.ndarray, x: np.ndarray, targets: np.ndarray, starts: np.ndarray,
               groups: np.ndarray, regularization: float) -> tuple[float,np.ndarray]:
    scores=x@w
    shifted=scores-np.maximum.reduceat(scores,starts)[groups]
    exp=np.exp(shifted)
    totals=np.add.reduceat(exp,starts)
    errors=exp/totals[groups]-targets
    loss=float(np.log(totals).sum()-targets@shifted+regularization*(w@w)/2)
    gradient=x.T@errors+regularization*w
    if not np.isfinite(loss) or not np.isfinite(gradient).all():
        raise ValueError('finite objective and gradient required')
    return loss,gradient


def listwise_objective(weights: object, values: object, targets: object, starts: object,
                       regularization: float=1.) -> tuple[float,np.ndarray]:
    w,x,y=_real(weights),_real(values),_real(targets)
    offsets=np.asarray(starts)
    if (w.ndim!=1 or x.ndim!=2 or x.shape[1]!=len(w) or not len(w)
            or y.shape!=(len(x),) or offsets.ndim!=1 or offsets.dtype.kind not in 'iu'
            or not len(offsets) or offsets[0]!=0 or offsets[-1]>=len(x)
            or np.any(offsets[1:]<=offsets[:-1]) or np.any(y<0)
            or not np.isfinite(regularization) or regularization<=0):
        raise ValueError('aligned nonempty groups, unit query targets and positive ridge required')
    # Bounds were checked before casting, so unsigned values cannot wrap.
    offsets=offsets.astype(np.intp)
    if not np.allclose(np.add.reduceat(y,offsets),1.,rtol=0,atol=1e-12):
        raise ValueError('unit query targets required')
    counts=np.diff(np.r_[offsets,len(x)])
    return _objective(w,x,y,offsets,np.repeat(np.arange(len(offsets)),counts),regularization)


def prepare_listwise(groups: Sequence[RankGroup], *, excluded_repositories: set[str]
                     ) -> TrainingLists:
    selected=[g for g in groups if g.repository not in excluded_repositories]
    if not selected or len({g.query_id for g in selected})!=len(selected):
        raise ValueError('unique nonempty training groups required')
    arrays,targets=[],[]
    width=None
    for group in selected:
        x,y=_real(group.values),np.asarray(group.positive)
        if (not group.repository or not group.query_id or x.ndim!=2 or not x.shape[1]
                or (width is not None and x.shape[1]!=width) or y.shape!=(len(x),)
                or not np.isin(y,(0,1)).all() or not 0<np.count_nonzero(y)<len(y)):
            raise ValueError('training groups require aligned positive and negative candidates')
        width=x.shape[1]
        arrays.append(x)
        targets.append(y.astype(np.float64)/np.count_nonzero(y))
    with np.errstate(over='raise',invalid='raise',divide='raise'):
        try:
            means=np.mean([x.mean(axis=0) for x in arrays],axis=0)
            variance=np.mean([np.mean((x-means)**2,axis=0) for x in arrays],axis=0)
            scales=np.sqrt(np.where(variance>1e-16,variance,1.))
            x=np.concatenate([(a-means)/scales for a in arrays])
        except FloatingPointError as exc:
            raise ValueError('finite training normalization required') from exc
    if any(not np.isfinite(v).all() for v in (means,variance,scales)):
        raise ValueError('finite training normalization required')
    targets_array=np.concatenate(targets)
    counts=np.array([len(a) for a in arrays])
    starts=np.r_[0,np.cumsum(counts)[:-1]]
    membership=np.repeat(np.arange(len(counts)),counts)
    if not np.isfinite(x).all():
        raise ValueError('finite training normalization required')
    for array in (x,targets_array,starts,membership,means,scales):
        array.setflags(write=False)
    return TrainingLists(x,targets_array,starts,membership,means,scales,
        tuple(sorted({g.repository for g in selected})),tuple(g.query_id for g in selected))


def fit_listwise(groups: Sequence[RankGroup], *, excluded_repositories: set[str]
                 ) -> tuple[LinearListRanker,dict]:
    from scipy.optimize import minimize
    training=prepare_listwise(groups,excluded_repositories=excluded_repositories)
    x,targets_array,starts,membership=training.values,training.targets,training.starts,training.membership
    trace=[]

    def objective(w: np.ndarray) -> tuple[float,np.ndarray]:
        value,gradient=_objective(w,x,targets_array,starts,membership,1.)
        trace.append({'loss':value,'max_abs_gradient':float(np.max(np.abs(gradient)))})
        return value,gradient

    result=minimize(objective,np.zeros(x.shape[1]),jac=True,method='L-BFGS-B',
                    options={'maxiter':1000,'maxls':50,'ftol':1e-15,'gtol':1e-7})
    value,gradient=objective(result.x)
    maximum=float(np.max(np.abs(gradient)))
    information={'training_repositories':list(training.repositories),
        'training_queries':len(training.query_ids),'training_rows':len(x),'query_ids':list(training.query_ids),
        'iterations':int(result.nit),'evaluations':int(result.nfev),'message':str(result.message),
        'loss':value,'max_abs_gradient':maximum,'trace':trace}
    if not result.success or maximum>1e-4:
        raise ListwiseFitError(
            f'listwise optimizer did not converge: {result.message}; gradient={maximum}',information)
    return LinearListRanker(training.means,training.scales,result.x),information

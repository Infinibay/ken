"""Training-only convex pairwise linear heads; no engine or reference IO."""
import numpy as np

def pairwise_examples(x,y,qids,repos,logits,*,held_out):
    x=np.asarray(x,dtype=np.float64);y=np.asarray(y);qids=np.asarray(qids);repos=np.asarray(repos);logits=np.asarray(logits,dtype=np.float64)
    if x.ndim!=2 or any(v.shape!=(len(x),) for v in [y,qids,repos,logits]) or not np.isfinite(x).all() or not np.isfinite(logits).all() or not np.isin(y,[0,1]).all():raise ValueError('finite aligned candidate data and binary labels required')
    differences=[];offsets=[];weights=[];queries=[]
    for q in dict.fromkeys(qids):
        ix=np.flatnonzero(qids==q)
        if len(set(repos[ix]))!=1:raise ValueError('one repository per complete query group required')
        if held_out is not None and repos[ix[0]]==held_out:continue
        pos=ix[y[ix]==1];neg=ix[y[ix]==0]
        if not len(pos) or not len(neg):continue
        a=np.repeat(pos,len(neg));b=np.tile(neg,len(pos));differences.append(x[a]-x[b]);offsets.append(logits[a]-logits[b]);weights.append(np.full(len(a),1./len(a)));queries.append(str(q))
    if not queries:raise ValueError('positive and negative containing training queries required')
    return {'differences':np.concatenate(differences),'offsets':np.concatenate(offsets),'weights':np.concatenate(weights)/len(queries),'queries':queries}

def logistic_loss(theta,x,offset,weights,regularization=1.):
    margin=x@theta+offset
    loss=float(np.dot(weights,np.logaddexp(0.,-margin))+.5*regularization*np.dot(theta,theta))
    gradient=x.T@(-weights*np.exp(-np.logaddexp(0.,margin)))+regularization*theta
    return loss,gradient

def fit_head(batch,*,residual,regularization=1.):
    from scipy.optimize import minimize
    x=batch['differences'];offset=batch['offsets'] if residual else np.zeros(len(x));weight=batch['weights']
    result=minimize(logistic_loss,np.zeros(x.shape[1]),args=(x,offset,weight,regularization),jac=True,method='L-BFGS-B',options={'maxiter':1000,'ftol':1e-12,'gtol':1e-8})
    if not result.success or not np.isfinite(result.x).all():raise ValueError('decision head optimizer did not converge: '+str(result.message))
    return result.x,{'iterations':int(result.nit),'loss':float(result.fun),'norm':float(np.linalg.norm(result.x)),'training_queries':len(batch['queries']),'training_pairs':len(x),'optimizer':str(result.message)}

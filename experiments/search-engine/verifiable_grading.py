"""Explicit identity and visible-evidence gates for the new utility metric."""
from __future__ import annotations
import json
import math
from collections import defaultdict

import numpy as np


def identity_hit(card,acceptable):
    if card is None:return False
    unit=card['unit']
    for gold in acceptable:
        if (unit['target_kind'],unit['path'])!=(gold['target_kind'],gold['path']):continue
        if unit['target_kind'] in {'module','file'}:return True
        if unit['entity']==gold['entity']:return True
    return False


def blind_pass(card,facets,judgment):
    if (not card or not facets or judgment.get('abstain',False) or
            judgment.get('relevance')!=2 or judgment.get('sufficiency')!=2):return False
    rows=judgment.get('requirements',[])
    expected={f['id'] for f in facets}
    if len(rows)!=len(expected) or {r['facet_id'] for r in rows}!=expected:return False
    for row in rows:
        if row.get('state')!='supported' or not row.get('evidence'):return False
        for evidence in row['evidence']:
            which=evidence.get('excerpt');quote=evidence.get('quote','')
            if which=='unit':visible=json.dumps(card['unit'],ensure_ascii=False,sort_keys=True)
            elif isinstance(which,int) and 0<=which<len(card['excerpts']):
                visible=card['excerpts'][which]['content']
            else:return False
            if not quote.strip() or quote not in visible:return False
    return True


def wilson(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;den=1+z*z/total
    mid=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [mid-half,mid+half]


def summarize(rows):
    n=len(rows)
    result={'queries':n}
    for key in ('recall10','recall20','identity','blind_verifiable','joint','abstain'):
        count=sum(bool(r[key]) for r in rows)
        result[key]={'count':count,'rate':count/n if n else None,'wilson_descriptive95':wilson(count,n)}
    available=[r for r in rows if r['recall10']]
    result['conditional_joint_given_recall10']={'count':sum(r['joint'] for r in available),
        'denominator':len(available),'rate':sum(r['joint'] for r in available)/len(available) if available else None}
    return result


def cluster_difference(rows,baseline,key='joint',seed=20261015):
    byrepo=defaultdict(list)
    before={r['id']:r for r in baseline}
    for row in rows:byrepo[row['repo_id']].append(int(row[key])-int(before[row['id']][key]))
    names=sorted(byrepo);rng=np.random.default_rng(seed);samples=[]
    for _ in range(10000):
        selected=rng.choice(names,size=len(names),replace=True)
        values=[v for name in selected for v in byrepo[name]]
        samples.append(float(np.mean(values)))
    return {'paired_gained':sum(r[key] and not before[r['id']][key] for r in rows),
        'paired_lost':sum(before[r['id']][key] and not r[key] for r in rows),
        'repo_cluster_bootstrap95':np.quantile(samples,[.025,.975]).tolist(),
        'clusters':len(names),'draws':10000,'seed':seed}

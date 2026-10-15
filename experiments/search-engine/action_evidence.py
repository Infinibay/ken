"""Measure requested actions against executed, called and returned source words."""
from __future__ import annotations
import math
from collections.abc import Callable
import numpy as np
from query_actions import QueryActions

FIELDS=('executable','calls','returns')
STATS=('exact','stem','mean','min','p25','above50','above70','weighted','mean_cosine','log_words')
FEATURES=(*(f'action_{field}_{stat}'for field in FIELDS for stat in STATS),
          'action_present','log_action_tokens','action_token_fraction')
Coverage=Callable[[str,list[dict[str,list[str]]],tuple[str,...]],list[dict[str,float]]]


def action_evidence(actions: QueryActions, documents: list[dict[str,list[str]]], *,
                    coverage: Coverage) -> np.ndarray:
    values=np.zeros((len(documents),len(FEATURES)),dtype=np.float64)
    if not documents or not actions.actions:
        return values
    rows=coverage(' '.join(actions.actions),documents,FIELDS)
    if len(rows)!=len(documents):
        raise ValueError('one action coverage row per source owner required')
    values[:,:-3]=[[row[field+'_'+stat]for field in FIELDS for stat in STATS]for row in rows]
    values[:,-3:]=(1.,math.log1p(len(actions.actions)),len(actions.actions)/max(1,len(actions.tokens)))
    if not np.isfinite(values).all():
        raise ValueError('finite action evidence required')
    return values

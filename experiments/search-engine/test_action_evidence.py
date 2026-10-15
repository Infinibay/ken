import hashlib
from functools import partial
import numpy as np
import pytest
from action_evidence import FEATURES, action_evidence
from query_actions import QueryActions
from ken.retrieval.evidence_features import _coverage


class Encoder:
    def embed_passages(self,texts):
        values=[]
        for text in texts:
            v=np.frombuffer(hashlib.sha256(text.encode()).digest()[:16],dtype=np.uint8).astype(np.float32)-128
            values.append(v/max(1e-9,np.linalg.norm(v)))
        return values
    def embed_query(self,text):return self.embed_passages([text])[0]


def docs():
    return [{'executable':['sort','items'],'calls':['sort'],'returns':['items'],'all':['sort','items']},
            {'executable':['build','items'],'calls':['build'],'returns':['items'],'all':['build','items']}]


def test_action_roles_reuse_coverage_without_turning_shared_topic_into_a_verb():
    coverage=partial(_coverage,encoder=Encoder(),stem_words=lambda ws:ws)
    rows=action_evidence(QueryActions(('sort','items'),('sort',)),docs(),coverage=coverage)
    assert rows.shape==(2,33)and len(FEATURES)==len(set(FEATURES))==33
    assert rows[0,FEATURES.index('action_calls_exact')]==1.
    assert rows[1,FEATURES.index('action_calls_exact')]==0.
    assert rows[0,FEATURES.index('action_returns_exact')]==0.
    assert rows[0,FEATURES.index('action_token_fraction')]==.5
    assert np.isfinite(rows).all()


def test_missing_actions_or_empty_pool_cannot_invoke_an_encoder():
    def forbidden(*args):raise AssertionError('empty action/pool must not score')
    np.testing.assert_array_equal(action_evidence(QueryActions(('items',),()),docs(),coverage=forbidden),np.zeros((2,33)))
    assert action_evidence(QueryActions(('sort',),('sort',)),[],coverage=forbidden).shape==(0,33)


def test_wrong_row_count_or_nonfinite_coverage_fails_explicitly():
    with pytest.raises(ValueError):action_evidence(QueryActions(('sort',),('sort',)),docs(),coverage=lambda *args:[])
    coverage=partial(_coverage,encoder=Encoder(),stem_words=lambda ws:ws)
    def invalid(*args):
        values=coverage(*args);values[0]['calls_mean']=float('nan');return values
    with pytest.raises(ValueError):action_evidence(QueryActions(('sort',),('sort',)),docs(),coverage=invalid)

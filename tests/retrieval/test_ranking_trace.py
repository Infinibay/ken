"""Explain real forest decisions without changing the decision itself."""
from copy import deepcopy
import numpy as np
import pytest

from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.ranking_trace import RankingTrace


def test_pair_trace_reconstructs_interacting_forest_margin_and_threshold_equality():
    model=NumericRanker.from_dict({'schema':1,'features':['coverage','path'], 'trees':[
        {'feature':0,'threshold':.5,'left':{'value':-2.},'right':{
            'feature':1,'threshold':.4,'left':{'value':3.},'right':{'value':7.}}},
        {'feature':1,'threshold':.4,'left':{'value':1.},'right':{'value':-1.}},
        {'value':.25}]})
    explanation=model.explain_pair(np.array([.7,.8]),np.array([.5,.2]))
    assert explanation['left_score']==6.25
    assert explanation['right_score']==-.75
    assert explanation['margin']==7.
    assert sum(t['delta'] for t in explanation['trees'])==explanation['margin']
    assert explanation['branch_margin_by_feature']=={'coverage':9.,'path':-2.}
    first=explanation['trees'][0]
    assert first['first_divergence']['feature']=='coverage'
    assert first['right_path'][0]['branch']=='left'
    assert first['right_path'][0]['value']==.5
    assert first['left_leaf']==7. and first['right_leaf']==-2.
    # Tree interactions are exposed as paths, not fictional fixed feature weights.
    assert [p['feature'] for p in first['left_path']]==['coverage','path']
    with pytest.raises(ValueError,match='finite'):
        model.explain_pair(np.array([float('nan'),0.]),np.array([0.,0.]))


def test_observed_ranking_keeps_scores_and_reports_tie_policy_without_source_bodies():
    from tests.retrieval.test_owner_ranking import candidate,WORD_MODEL
    from tests.retrieval.test_evidence_features import Encoder
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.description import describe_owner
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.owner_ranking import EvidenceReranker
    model=NumericRanker.from_dict({'schema':1,'features':FEATURES,'trees':[{'value':1.}]})
    encoder=Encoder();encoder.spec=WORD_MODEL
    ranker=EvidenceReranker(model,encoder)
    candidates=[candidate('first',.3,'PRIVATE_SOURCE_SENTINEL()'),candidate('second',.7,'store(value)')]
    before=deepcopy(candidates)
    descriptions={c.entity:describe_owner(c.passages) for c in candidates}
    request=SearchRequest('find stored values')
    plain=ranker.rank(request,candidates,descriptions)
    trace=RankingTrace()
    observed=ranker.rank(request,candidates,descriptions,trace=trace)
    assert observed==plain and candidates==before
    data=trace.to_dict()
    assert data['model_fingerprint']==model.fingerprint
    assert data['feature_names']==list(FEATURES)
    assert 'query' not in data and 'expanded_query' not in data
    assert 'PRIVATE_SOURCE_SENTINEL' not in str(data)
    assert trace.to_dict(include_query=True)['query']=='find stored values'
    assert data['owners'][0]['signals']['rrf']==.3
    pair=trace.compare(observed[0].entity,observed[1].entity)
    assert pair['ordering_reason']=='stable_proposal_order'
    assert pair['numeric']['margin']==0.
    # Export is a detached observation, not mutable ranking state.
    data['owners'][0]['signals']['rrf']=100.
    assert trace.to_dict()['owners'][0]['signals']['rrf']==.3
    ranker.rank(SearchRequest('second request'),candidates,descriptions,trace=trace)
    assert trace.to_dict()['attempt']==2
    assert trace.to_dict(include_query=True)['query']=='second request'


def test_trace_pairs_follow_actual_ranked_owner_and_reconstruct_recorded_scores():
    from tests.retrieval.test_owner_ranking import candidate,WORD_MODEL
    from tests.retrieval.test_evidence_features import Encoder
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.description import describe_owner
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.owner_ranking import EvidenceReranker
    feature=FEATURES.index('expanded_implementation_exact')
    model=NumericRanker.from_dict({'schema':1,'features':FEATURES,'trees':[{
        'feature':feature,'threshold':.8,'left':{'value':0.},'right':{'value':1.}}]})
    encoder=Encoder();encoder.spec=WORD_MODEL
    candidates=[candidate('mentions',.9,'unrelated(values)'),candidate('stores',.1,'persist(durable, cookie)')]
    trace=RankingTrace()
    ranked=EvidenceReranker(model,encoder).rank(SearchRequest('persist durable cookie'),candidates,
        {c.entity:describe_owner(c.passages) for c in candidates},trace=trace)
    pair=trace.compare(ranked[0].entity,ranked[1].entity)
    assert pair['ordering_reason']=='numeric_model_score'
    assert pair['left']['proposal_index']==1
    assert pair['left']['feature_values'][feature]==1.
    assert pair['right']['feature_values'][feature]==0.
    assert pair['numeric']['left_score']==ranked[0].score
    assert pair['numeric']['right_score']==ranked[1].score
    assert pair['numeric']['margin']==1.
    restored=RankingTrace.from_dict(trace.to_dict(),model)
    assert restored.compare(ranked[0].entity,ranked[1].entity)==pair
    corrupted=trace.to_dict();corrupted['owners'][0]['score']+=1.
    with pytest.raises(ValueError,match='scores'):
        RankingTrace.from_dict(corrupted,model)
    corrupted=trace.to_dict();corrupted['owners'][0]['rank']=1
    with pytest.raises(ValueError,match='order'):
        RankingTrace.from_dict(corrupted,model)


def test_exact_bypass_is_explicit_and_does_not_compute_features():
    from tests.retrieval.test_owner_ranking import candidate,WORD_MODEL
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.owner_ranking import EvidenceReranker
    class Forbidden:
        spec=WORD_MODEL
        def embed_passages(self,text):raise AssertionError('no encoding on exact bypass')
        embed_query=embed_passages
    exact=candidate('store',1.,'store(value)');exact.signals['exact']=1.
    model=NumericRanker.from_dict({'schema':1,'features':FEATURES,'trees':[{'value':0.}]})
    trace=RankingTrace()
    ranker=EvidenceReranker(model,Forbidden())
    result=ranker.rank(SearchRequest('store'),[exact],{},trace=trace)
    data=trace.to_dict()
    assert result[0].entity==exact.entity
    assert data['policy']=='unique_exact'
    assert data['owners'][0]['feature_values'] is None

import hashlib
from dataclasses import replace
import pytest
from tests.retrieval.test_piece_catalog import source_owners
from tests.retrieval.test_neural_reranker import registered_reranker
from ken.retrieval.model import CodeMatch, SearchRequest


def test_piece_search_returns_primary_class_and_preserves_native_top10(source_owners,registered_reranker):
    from ken.embedder.static_head import StaticHeadEmbedder
    from ken.retrieval.profile import default_profile
    from ken.retrieval.numeric_ranker import NumericRanker
    from ken.retrieval.piece_ranking import PieceReranker,PIECE_FEATURES
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_search import PieceSearch
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    words=StaticHeadEmbedder(default_profile().behavior.model_id)
    forest=NumericRanker.from_dict({'schema':1,'features':PIECE_FEATURES,'trees':[{'value':0.}]})
    ranker=PieceReranker(forest,words,stem_words=EvidenceReranker.stem_words)
    neural=ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker))
    runtime=PieceSearch(catalog,ranker,neural)
    keys=[k['Outer.Inner.run'],k['Outer.read'],k['helper']]
    matches=[CodeMatch(key,3-i,list(owners[key]),owners[key][0].source_hash) for i,key in enumerate(keys)]
    response=runtime.search(SearchRequest('Which class reads values?',piece_kind='class'),matches,
                            expanded_query='Which class reads values?',profile_version='test')
    assert {r['entity']['qualname'] for r in response.results}=={'Outer','Outer.Inner'}
    assert all(r['piece_kind']=='class' and r['evidence'] and not r['stale'] for r in response.results)
    for result in response.results:
        for excerpt in result['evidence']:
            assert excerpt['content']=='\n'.join(catalog.lines[result['path']][excerpt['start_line']-1:excerpt['end_line']])
    assert 'neural_scores' not in response.to_dict()
    # User display limits apply after top10 reranking and never change first identity.
    smaller=runtime.search(SearchRequest('Which class reads values?',piece_kind='class',limit=1),matches,
                           expanded_query='Which class reads values?',profile_version='test')
    assert smaller.results[0]['entity']==response.results[0]['entity']


def test_file_response_identity_is_the_physical_file_and_source_changes_are_detected(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_cards import build_piece_cards
    from ken.retrieval.piece_search import present_cards
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners);key=k['helper']
    cards=build_piece_cards([CodeMatch(key,1.,list(owners[key]),owners[key][0].source_hash)],'file','read',catalog)
    result=present_cards(cards,SearchRequest('read',piece_kind='file'),catalog,profile_version='test').results[0]
    assert result['piece_kind']=='file' and result['entity']['kind']=='file'
    assert result['entity']['qualname'] is None
    (root/key.path).write_text('changed\n')
    changed=present_cards(cards,SearchRequest('read',piece_kind='file'),catalog,profile_version='test')
    assert changed.results[0]['stale'] is True and not changed.results[0]['evidence']
    assert changed.warnings

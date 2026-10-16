import numpy as np
import pytest

from ken.retrieval.description import describe_owner
from ken.retrieval.model import CodeMatch, EntityKey, Passage, SearchRequest, Span


def owner(name, kind, text, path='engine.py'):
    key = EntityKey(path, kind, name, name.rpartition('.')[0] or None)
    passage = Passage(key, Span(1, 1), {'identity': name, 'signature': text,
        'documentation': '', 'body': text, 'path': key.path}, 'source-sha', Span(1, 1))
    return describe_owner([passage])


def piece(name, score):
    from ken.retrieval.piece_ranking import PieceCandidate
    declaration = owner(name, 'class', 'class ' + name)
    method = owner(name + '.run', 'method', 'return emit(value)')
    match = CodeMatch(method.entity, score, list(method.passages), method.source_hash)
    return PieceCandidate('class', 'engine.py', declaration.entity,
                          (declaration, method), (match,))


def test_piece_features_keep_declaration_and_member_evidence_distinct():
    from ken.retrieval.piece_ranking import piece_features
    from tests.retrieval.test_evidence_features import Encoder
    pieces = [piece('Factory', 3.), piece('Try', 2.)]
    matrix = piece_features(SearchRequest('Which class is Try?', piece_kind='class'), pieces,
                            encoder=Encoder(), stem_words=lambda words: words)
    column = matrix.names.index('declaration_identity_exact')
    assert matrix.values[1, column] > matrix.values[0, column]
    assert matrix.values[:, matrix.names.index('request_class')].tolist() == [1., 1.]
    assert matrix.values[:, matrix.names.index('native_rank')].tolist() == [1., .5]
    assert matrix.values[:, matrix.names.index('declaration_in_matches')].tolist() == [0., 0.]
    assert np.isfinite(matrix.values).all()


def test_piece_forest_can_promote_the_requested_class_without_changing_membership():
    from ken.retrieval.piece_ranking import PIECE_FEATURES, PieceReranker
    from ken.retrieval.numeric_ranker import NumericRanker
    from tests.retrieval.test_evidence_features import Encoder
    column = PIECE_FEATURES.index('declaration_identity_exact')
    model = NumericRanker.from_dict({'schema': 1, 'features': PIECE_FEATURES, 'trees': [
        {'feature': column, 'threshold': .1, 'left': {'value': 0.}, 'right': {'value': 1.}}]})
    candidates = [piece('Factory', 3.), piece('Try', 2.)]
    ranked = PieceReranker(model, Encoder(), stem_words=lambda words: words).rank(
        SearchRequest('Try', piece_kind='class'), candidates)
    assert [m.piece.entity.qualname for m in ranked] == ['Try', 'Factory']
    assert [m.score for m in ranked] == [1., 0.]
    assert {id(m.piece) for m in ranked} == {id(p) for p in candidates}
    assert [p.matches[0].score for p in candidates] == [3., 2.]


def test_piece_refuses_mixed_sources_and_wrong_requested_kind():
    from ken.retrieval.piece_ranking import PieceCandidate, piece_features
    from tests.retrieval.test_evidence_features import Encoder
    candidate = piece('Try', 1.)
    wrong = owner('Other', 'class', 'class Other')
    with pytest.raises(ValueError, match='member'):
        PieceCandidate('class', candidate.path, candidate.entity, (*candidate.members, wrong), candidate.matches)
    with pytest.raises(ValueError, match='requested'):
        piece_features(SearchRequest('module', piece_kind='module'), [candidate],
                       encoder=Encoder(), stem_words=lambda words: words)


def test_piece_stage_leaves_symbol_order_unchanged():
    from ken.retrieval.piece_ranking import PIECE_FEATURES, PieceCandidate, PieceReranker
    from ken.retrieval.numeric_ranker import NumericRanker
    from tests.retrieval.test_evidence_features import Encoder
    candidates = []
    for name, score in [('Factory', 3.), ('Try', 2.)]:
        member = owner(name, 'function', 'return value')
        match = CodeMatch(member.entity, score, list(member.passages), member.source_hash)
        candidates.append(PieceCandidate('symbol', 'engine.py', member.entity, (member,), (match,)))
    column = PIECE_FEATURES.index('declaration_identity_exact')
    model = NumericRanker.from_dict({'schema': 1, 'features': PIECE_FEATURES, 'trees': [
        {'feature': column, 'threshold': .1, 'left': {'value': 0.}, 'right': {'value': 1.}}]})
    ranked = PieceReranker(model, Encoder(), stem_words=lambda words: words).rank(
        SearchRequest('Try', piece_kind='symbol'), candidates)
    assert [m.piece.entity.qualname for m in ranked] == ['Factory', 'Try']


def test_named_file_keeps_identity_priority_over_piece_forest_score():
    from ken.retrieval.piece_ranking import PIECE_FEATURES, PieceCandidate, PieceReranker
    from ken.retrieval.numeric_ranker import NumericRanker
    from tests.retrieval.test_evidence_features import Encoder
    candidates=[]
    for path, name in [('api/Rules.java', 'Rules'), ('engine/Consumer.java', 'Consumer')]:
        member=owner(name, 'class', 'class '+name, path=path)
        match=CodeMatch(member.entity, 1., list(member.passages), member.source_hash)
        candidates.append(PieceCandidate('file', path, None, (member,), (match,)))
    model=NumericRanker.from_dict({'schema':1,'features':PIECE_FEATURES,'trees':[{
        'feature':PIECE_FEATURES.index('native_rank'),'threshold':.75,
        'left':{'value':1.},'right':{'value':0.}}]})
    ranked=PieceReranker(model, Encoder(), stem_words=lambda words:words).rank(
        SearchRequest('Find api/Rules.java and show its declaration.',piece_kind='file'), candidates)
    assert ranked[0].piece.path=='api/Rules.java'

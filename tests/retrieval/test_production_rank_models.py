from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES,SOURCE_VIEW_FEATURES
from ken.retrieval.evidence_features import FEATURES
from ken.retrieval.piece_ranking import PIECE_FEATURES


def test_production_models_have_generic_bound_feature_schemas_and_fixed_fingerprints():
    from ken.retrieval.best_resources import load_rank_models
    native,piece=load_rank_models()
    assert native.features==(*FEATURES,*CONTEXTUAL_FEATURES,*SOURCE_VIEW_FEATURES)
    assert piece.features==PIECE_FEATURES
    assert native.fingerprint=='6b563fed14ed276e1b310beba84006078ef65ab5d7d3cb5622d759f6a671e3a0'
    assert piece.fingerprint=='62846d51f58e5da1cf27ad444073d14341bdc6368f8552a7bb1c30e8d6e7d9b9'

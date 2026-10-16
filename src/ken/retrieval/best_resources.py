"""Share the fixed search models across projects, loading heavyweight sessions lazily."""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from ken.embedder.contextual_onnx import ContextEncoder, code_context_model
from ken.embedder.model2vec_backend import Model2VecEmbedder, RegisteredStaticEncoder, potion_assets
from ken.retrieval.neural_assets import default_reranker
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.piece_ranking import PieceReranker
from ken.retrieval.profile import ContextualRetrieval, EvidenceRanking, RetrievalProfile, potion_profile
from ken.retrieval.source_views import SOURCE_VIEW_PROJECTION
from ken.retrieval.translation_preparation import default_query_expansion
from dataclasses import replace


@dataclass(frozen=True)
class SearchResources:
    words: RegisteredStaticEncoder
    context: ContextEncoder
    owner_ranker: EvidenceReranker
    piece_ranker: PieceReranker
    neural: ONNXReranker
    profile: RetrievalProfile


def load_rank_models() -> tuple[NumericRanker, NumericRanker]:
    """Portable generic models; no validation-fold or repository-name selection."""
    directory = resources.files('ken.retrieval').joinpath('data')
    registry = json.loads(directory.joinpath('production-rank-models.json').read_text())
    models = []
    for role in ('native','piece'):
        record = registry[role]
        data = gzip.decompress(directory.joinpath(record['file']).read_bytes())
        model = NumericRanker.from_dict(json.loads(data))
        if model.fingerprint != record['fingerprint']:
            raise ValueError('bundled production ranking model identity mismatch')
        models.append(model)
    return models[0], models[1]


@lru_cache(maxsize=1)
def default_resources() -> SearchResources:
    static = Model2VecEmbedder(potion_assets())
    words = static.registered
    context = ContextEncoder(code_context_model())
    native, piece = load_rank_models()
    expansion = default_query_expansion()
    owner_ranker = EvidenceReranker(native, words, expand_query=expansion,
                                    expansion_revision=expansion.revision)
    view_model = replace(context.model, document_projection=SOURCE_VIEW_PROJECTION).spec
    profile = replace(potion_profile(),
        contextual=ContextualRetrieval(context.spec, view_model=view_model),
        evidence=EvidenceRanking(native.fingerprint, words.spec, expansion.revision,
                                 feature_version=3, evidence_version=3))
    return SearchResources(words, context, owner_ranker,
        PieceReranker(piece, words, stem_words=owner_ranker.stem_words), default_reranker(), profile)

"""CPU development control for compact pairwise relevance models."""
from __future__ import annotations

from typing import Any

import numpy as np


class PairRelevance:
    """Preserve the complete query and batch bounded document pairs as raw logits."""
    def __init__(self, session: Any, tokenizer: Any, *, max_tokens: int, batch_size: int):
        if max_tokens <= 0 or batch_size <= 0:
            raise ValueError('positive pair budgets required')
        self.session, self.tokenizer = session, tokenizer
        self.batch_size = batch_size
        self.inputs = {i.name for i in session.get_inputs()}
        self.tokenizer.enable_truncation(max_length=max_tokens, strategy='only_second')

    def score(self, query: str, documents: list[str], *, purpose: str) -> list[float]:
        result: list[float] = []
        for start in range(0, len(documents), self.batch_size):
            batch = self.tokenizer.encode_batch([(query, d) for d in documents[start:start+self.batch_size]])
            features = {name:np.asarray([getattr(e, {'input_ids':'ids',
                'attention_mask':'attention_mask', 'token_type_ids':'type_ids'}[name]) for e in batch],
                dtype=np.int64) for name in self.inputs}
            scores = np.asarray(self.session.run(None, features)[0]).reshape(-1)
            if scores.size != len(batch) or not np.isfinite(scores).all():
                raise ValueError('one finite relevance logit required per document')
            result.extend(float(s) for s in scores)
        return result

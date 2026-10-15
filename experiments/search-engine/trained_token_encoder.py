"""CPU-only adapter for the official small trained ColBERT int8 token head."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from ken.retrieval.profile import EncoderSpec

TOKEN_POLICY = 'normalized-head96-doc300-query128-explicit-marker-no-padding-no-query-augmentation-v1'


def bert_marker_input(encoding: Any, *, marker: int, max_length: int
                      ) -> tuple[dict[str, np.ndarray], np.ndarray, tuple[tuple[int, int], ...]]:
    ids, attention, types, offsets = (list(encoding.ids), list(encoding.attention_mask),
                                      list(encoding.type_ids), list(encoding.offsets))
    if (marker not in (1, 2) or len(ids)+1 > max_length or len(ids) < 2
            or ids[0] != 101 or ids[-1] != 102
            or not len(ids) == len(attention) == len(types) == len(offsets)
            or any(value != 1 for value in attention)):
        raise ValueError('unpadded aligned BERT input within its explicit marker budget required')
    ids.insert(1, marker)
    attention.insert(1, 1)
    types.insert(1, 0)
    offsets.insert(1, (0, 0))
    inputs = {name: np.array([values], dtype=np.int64) for name, values in (
        ('input_ids', ids), ('attention_mask', attention), ('token_type_ids', types))}
    return inputs, np.asarray(ids, dtype=np.int32), tuple(offsets)


def retained_tokens(ids: np.ndarray, punctuation: set[int], *, is_query: bool) -> np.ndarray:
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or np.any(ids < 0):
        raise ValueError('one nonnegative integer token ID vector required')
    return (ids != 0) & (np.ones(len(ids), dtype=bool) if is_query
                         else ~np.isin(ids, list(punctuation)))


def validated_token_vectors(output: np.ndarray, *, length: int) -> np.ndarray:
    if (output.shape != (1, length, 96) or output.dtype != np.float32
            or not np.isfinite(output).all()
            or not np.allclose(np.linalg.norm(output, axis=2), 1., atol=1e-5)):
        raise ValueError('finite already-normalized96-dimensional token head required')
    return output[0]


@dataclass(frozen=True)
class TokenEmbedding:
    ids: np.ndarray
    offsets: tuple[tuple[int, int], ...]
    vectors: np.ndarray


class TrainedTokenEncoder:
    def __init__(self, registration: dict):
        if (not registration.get('complete') or registration['license'] != 'apache-2.0'
                or registration['hf_revision'] != '934fa8bb4ce2284f4c2baa232d81aca4d076fa5e'):
            raise ValueError('the pinned official small-model registration is required')
        root = Path(registration['root'])
        for name, record in registration['artifacts'].items():
            with (root/name).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                    raise ValueError('small-model artifact changed')
        runtime = import_module('onnxruntime')
        tokenizers = import_module('tokenizers')
        config = json.loads((root/'onnx_config.json').read_text())
        if (config['query_prefix_id'] != 1 or config['document_prefix_id'] != 2
                or config['embedding_dim'] != 96 or config['document_length'] != 300
                or config['do_query_expansion'] or config['attend_to_expansion_tokens']):
            raise ValueError('unsupported official token model policy')
        self.tokenizers = {}
        for is_query, limit in ((False, 300), (True, 128)):
            tokenizer = tokenizers.Tokenizer.from_file(str(root/'tokenizer.json'))
            tokenizer.no_padding()
            tokenizer.enable_truncation(max_length=limit-1)
            if tokenizer.token_to_id('[unused0]') != 1 or tokenizer.token_to_id('[unused1]') != 2:
                raise ValueError('registered BERT marker vocabulary required')
            self.tokenizers[is_query] = tokenizer
        self.punctuation = {self.tokenizers[False].encode(word, add_special_tokens=False).ids[0]
                            for word in config['skiplist_words']}
        identity = {'model_id': registration['model_id'], 'hf_revision': registration['hf_revision'],
            'artifacts': registration['artifacts'], 'token_policy': TOKEN_POLICY,
            'runtime': {'numpy': np.__version__, 'onnxruntime': runtime.__version__,
                        'tokenizers': version('tokenizers')}}
        # Download timing is provenance, not part of the mathematical model identity.
        identity['artifacts'] = {name: {key: row[key] for key in ('bytes', 'sha256')}
                                 for name, row in registration['artifacts'].items()}
        self.spec = EncoderSpec(registration['model_id'],
            hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            'provided', sequence_length=300, batch_size=1)
        self.identity = {**identity, 'spec': asdict(self.spec)}
        options = runtime.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = runtime.InferenceSession(str(root/'model_int8.onnx'), sess_options=options,
                                                providers=['CPUExecutionProvider'])
        if self.session.get_providers() != ['CPUExecutionProvider']:
            raise ValueError('CPU-only token inference required')
        if ({item.name for item in self.session.get_inputs()}
                != {'input_ids', 'attention_mask', 'token_type_ids'}
                or [item.name for item in self.session.get_outputs()] != ['output']):
            raise ValueError('registered normalized token head interface required')
        self.calls: list[dict] = []

    def encode(self, text: str, *, is_query: bool) -> TokenEmbedding:
        started = time.perf_counter()
        encoding = self.tokenizers[is_query].encode(text)
        inputs, ids, offsets = bert_marker_input(encoding, marker=1 if is_query else 2,
                                                max_length=128 if is_query else 300)
        vectors = validated_token_vectors(self.session.run(['output'], inputs)[0], length=len(ids))
        keep = retained_tokens(ids, self.punctuation, is_query=is_query)
        self.calls.append({'is_query': is_query, 'input_tokens': len(ids),
                           'selected_tokens': int(keep.sum()), 'ms': (time.perf_counter()-started)*1000})
        return TokenEmbedding(ids[keep], tuple(offset for offset, active in zip(offsets, keep, strict=True)
                                               if active), vectors[keep])

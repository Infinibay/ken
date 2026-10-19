"""Build tiny NPZ data; expected vectors come only from the frozen Python port."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer, models, pre_tokenizers

from .reference import Reference
from .table_reference import capture


def generate(reference: Reference, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    tok = Tokenizer(models.WordLevel({'alfa': 0, 'beta': 1, 'gamma': 2,
                                      'delta': 3, '[UNK]': 4}, unk_token='[UNK]'))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    base_a = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [0, 0, 2]], dtype='f4')
    base_b = np.array([[1, 0, .3, -.2], [0, 1, -.4, .5], [.2, -.1, 1, 0]], dtype='f4')
    base = dict(lut=np.arange(5, dtype='i4'), A=base_a, B=base_b,
                tokenizer=np.frombuffer(tok.to_str().encode(), dtype='u1'),
                meta=np.frombuffer(b'{"name":"test/table","dim":4}', dtype='u1'))
    variants = {'f32': {}, 'f16': {'A': (base_a * .12345).astype('f2')},
                'f64': {'A': (base_a.astype('f8') * .123456789), 'B': base_b.astype('f8')},
                'int8': {'A': (base_a * 25).astype('i1'),
                         'A_scale': np.array([.1, .2, .3, .4, .5], dtype='f4')},
                'fortran-be': {'A': np.asfortranarray((base_a + .123).astype('>f4')),
                               'B': np.asfortranarray(base_b.astype('>f8')),
                               'lut': np.arange(5, dtype='>i8')},
                'negative-lut': {'lut': np.array([-5, -4, -3, -2, -1], dtype='i8')},
                'cancellation': {'A': np.array([[1e8, 1, .25], [-1e8, -1, .125],
                                               [3, 4, 1e-4], [1, 0, -1], [0, 2, 0]], dtype='f4')}}
    tok.enable_padding(length=4, pad_id=3, pad_token='delta')
    tok.enable_truncation(max_length=2)
    variants['serialized-policy'] = {'tokenizer': np.frombuffer(tok.to_str().encode(), dtype='u1')}
    valid = []
    for name, changes in variants.items():
        artifact = output / f'{name}.npz'
        np.savez_compressed(artifact, **(base | changes))
        capture(reference, artifact, output / f'{name}.json')
        valid.append(name)
    invalid = {'bad-scale': {'A': base_a.astype('i1'), 'A_scale': np.ones(4, dtype='f4')},
               'bad-positive-lut': {'lut': np.array([0, 1, 2, 3, 5], dtype='i4')},
               'bad-negative-lut': {'lut': np.array([0, 1, 2, 3, -6], dtype='i4')},
               'bad-shape': {'B': np.ones((2, 4), dtype='f4')},
               'nonfinite': {'B': np.full((3, 4), np.nan, dtype='f4')},
               'object': {'A': np.array([{'payload': 'never execute pickle'}], dtype=object)},
               'bad-tokenizer': {'tokenizer': np.frombuffer(b'{}', dtype='u1')}}
    for name, changes in invalid.items():
        np.savez_compressed(output / f'{name}.npz', **(base | changes))
    for name, removed, changes in [('missing-B', 'B', {}),
                                   ('missing-scale', 'A_scale', {'A': base_a.astype('i1')})]:
        arrays = base | changes
        arrays.pop(removed, None)
        np.savez_compressed(output / f'{name}.npz', **arrays)
        invalid[name] = {}
    (output / 'not-zip.npz').write_bytes(b'not a table')
    (output / 'manifest.json').write_text(json.dumps({'valid': valid,
        'invalid': [*invalid, 'not-zip']}, indent=2) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    generate(Reference.load(args.reference), args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

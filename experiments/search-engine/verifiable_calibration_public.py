"""Validate public calibration evidence before any model scores or Gold exist."""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from ken.retrieval.candidates import owner_passages
from ettin_cpu import sha
from verifiable_guard import verify_source_preparation
from verifiable_pieces import SourceCatalog
from verifiable_source_auth import authenticate_card


def load_rows(paths):
    return [json.loads(line) for path in paths for line in Path(path).read_text().splitlines()]


def validate_inputs(workspace, source_metadata, case_paths, card_paths):
    roots, preparation = verify_source_preparation(workspace, source_metadata)
    cases, cards = load_rows(case_paths), load_rows(card_paths)
    bycase = {row['id']: row for row in cases}
    if (len(cases) != 20 or len(bycase) != 20 or len(cards) != 60
            or len({r['card_id'] for r in cards}) != 60):
        raise ValueError('twenty unique families / sixty unique cards required')
    if Counter(r['target_kind'] for r in cases) != dict.fromkeys(('class', 'symbol', 'module', 'file'), 5):
        raise ValueError('five calibration families per piece kind required')
    if Counter(r['case_id'] for r in cards) != dict.fromkeys(bycase, 3):
        raise ValueError('three cards per public family required')
    for repo in sorted({r['repo_id'] for r in cases}):
        index = workspace / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db')
        with sqlite3.connect(f'file:{index}?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            catalog = SourceCatalog(roots[repo], owner_passages(conn))
            for row in cards:
                case = bycase[row['case_id']]
                if case['repo_id'] == repo:
                    authenticate_card(row['card'], catalog)
                    if row['card']['unit']['target_kind'] != case['target_kind']:
                        raise ValueError('card type differs from request')
    return {'scope': 'ALL60 public calibration cards source-authenticated; no scores or Gold',
        'selection_policy': 'attributed source owners; semantic relevance/sufficiency judged separately',
        'preparation': preparation, 'public_inputs': {str(p): sha(p) for p in case_paths + card_paths},
        'families': len(cases), 'cards': len(cards),
        'authenticator_sha256': sha(Path(__file__).with_name('verifiable_source_auth.py')),
        'script_sha256': sha(__file__)}


def main():
    parser = argparse.ArgumentParser()
    for name in ('workspace', 'source-metadata', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cases', type=Path, nargs='+', required=True)
    parser.add_argument('--cards', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    receipt = validate_inputs(args.workspace, args.source_metadata, args.cases, args.cards)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'registration.json').write_text(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()

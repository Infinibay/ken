"""Check immutable diagnostics and every v116 card without acceptance data."""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys

sys.path[:0] = ['output/frozen/ranking-diagnostics-owned-v120/src',
                'output/frozen/verifiable-scope-composition-v116/experiments/search-engine']
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.candidates import owner_passages
from verifiable_pieces import SourceCatalog, validate_card
from verifiable_dependencies import LocalCallEvidence


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


root = Path.cwd()
snapshot = root / 'output/frozen/ranking-diagnostics-owned-v120'
receipt = verify_frozen_source(snapshot)
current = root / 'output/development/verifiable-scope-composition-v116'
previous = root / 'output/development/verifiable-lexical-scope-v114'
if not previous.exists():
    matches = [p.parent for p in (root / 'output/development').glob('*v114/registration.json')
               if json.loads(p.read_text()).get('status') == 'ALL outputs closed without Gold or quality grading']
    assert len(matches) == 1, matches
    previous = matches[0]
registration = json.loads((current / 'registration.json').read_text())
assert registration['status'] == 'ALL outputs closed without Gold or quality grading'
roots = json.loads(Path('/private/tmp/ken-verifiable-pieces-benchmark-20261015/source-metadata/roots.json').read_text())
counts = {'pool_cards_source_and_budget_valid': 0, 'top1_cards_source_and_budget_valid': 0,
          'pool_identity_or_order_changes': 0, 'top1_identity_changes': 0}
for repo, pins in registration['closed_workers']['baseline'].items():
    folder = current / 'baseline' / repo
    assert all(sha(folder / name) == digest for name, digest in pins.items())
    index = root / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db')
    conn = sqlite3.connect(f'file:{index}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    catalog = SourceCatalog(roots[repo], owner_passages(conn))
    dependencies = LocalCallEvidence(catalog)
    old = {r['id']: r for r in rows(previous / 'baseline' / repo / 'pools.jsonl')}
    for row in rows(folder / 'pools.jsonl'):
        a, b = [c['unit'] for c in row['cards']], [c['unit'] for c in old[row['id']]['cards']]
        counts['pool_identity_or_order_changes'] += a != b
        for card in row['cards']:
            validate_card(card, catalog, dependencies=dependencies)
            counts['pool_cards_source_and_budget_valid'] += 1
    old_answers = {r['id']: r for r in rows(previous / 'baseline' / repo / 'answers.jsonl')}
    for row in rows(folder / 'answers.jsonl'):
        if row['card'] is not None:
            validate_card(row['card'], catalog, dependencies=dependencies)
            counts['top1_cards_source_and_budget_valid'] += 1
        counts['top1_identity_changes'] += row['card']['unit'] != old_answers[row['id']]['card']['unit']
    conn.close()
assert counts == {'pool_cards_source_and_budget_valid': 3928,
                  'top1_cards_source_and_budget_valid': 200,
                  'pool_identity_or_order_changes': 0, 'top1_identity_changes': 0}, counts
result = {'clean_source_receipt': receipt, 'source_card_checks': counts,
          'scope': 'All closed v116 source, ownership, dependency and budget checks; no private acceptance or grading'}
out = root / 'output/analysis/owned-ranking-diagnostics-v120/source-card-audit.json'
out.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))

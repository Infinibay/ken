"""Prepare only new visible shadow cards for cross-curator review, without Gold."""
import argparse
import json
import random
import sqlite3
from pathlib import Path

from ken.retrieval.candidates import owner_passages
from ettin_cpu import sha
from verifiable_pieces import SourceCatalog, canonical, digest, validate_card


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser()
    for name in ('workspace', 'source-metadata', 'comparison', 'public-cases', 'principal-inputs',
                 'principal-judgment-seal', 'shadows', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    comparison_path = args.comparison / 'registration.json'
    comparison = json.loads(comparison_path.read_text())
    principal_receipt = args.principal_inputs / 'receipt.json'
    principal = json.loads(principal_receipt.read_text())
    seal = json.loads(args.principal_judgment_seal.read_text())
    shadow_path = args.shadows / 'registration.json'
    shadows = json.loads(shadow_path.read_text())
    if (comparison.get('status') != 'ALL outputs closed without Gold or quality grading'
            or seal.get('status') != 'ALL principal blind judgments closed before Gold'
            or shadows['principal_judgment_seal_sha256'] != sha(args.principal_judgment_seal)
            or shadows['comparison_sha256'] != sha(comparison_path)
            or principal['comparison_registration_sha256'] != sha(comparison_path)
            or seal['blind_input_receipt_sha256'] != sha(principal_receipt)):
        raise ValueError('shadow/original blind closures differ')
    for arm, repos in comparison['closed_workers'].items():
        for repo, files in repos.items():
            for name, expected in files.items():
                if sha(args.comparison / arm / repo / name) != expected:
                    raise ValueError('closed output changed')
    known = {}
    for name, expected in principal['files'].items():
        if sha(args.principal_inputs / name) != expected:
            raise ValueError('original blind input changed')
        if name != 'mapping.jsonl':
            known.update({r['judge_id']: r for r in rows(args.principal_inputs / name)})
    judgments = {}
    for name, expected in seal['judgment_files'].items():
        if sha(name) != expected:
            raise ValueError('original judgments changed')
        for row in rows(name):
            if row['judge_id'] in judgments:
                raise ValueError('duplicate original judgment')
            judgments[row['judge_id']] = row
    if set(known) != set(judgments):
        raise ValueError('original judgment scope differs')
    if sha(args.public_cases) != comparison['public_cases_sha256']:
        raise ValueError('public cases changed')
    cases = {r['id']: r for r in rows(args.public_cases)}
    pools = {r['id']: r for p in (args.comparison / 'baseline').glob('*/pools.jsonl') for r in rows(p)}
    selections = []
    for arm in ('17m', '32m', '68m'):
        path = args.shadows / (arm + '-selections.jsonl')
        if sha(path) != shadows['models'][arm]['selections_sha256']:
            raise ValueError('shadow selection changed')
        selections.extend(rows(path))
    roots = json.loads((args.source_metadata / 'roots.json').read_text())
    catalogs = {}
    new, mapping = {}, []
    for selection in selections:
        case = cases[selection['id']]
        index = selection['top_index']
        card = pools[case['id']]['cards'][index] if index is not None else None
        if card:
            repo = case['repo_id']
            if repo not in catalogs:
                path = args.workspace / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db')
                conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
                conn.row_factory = sqlite3.Row
                catalogs[repo] = SourceCatalog(roots[repo], owner_passages(conn))
                conn.close()
            validate_card(card, catalogs[repo])
        body = {k: case[k] for k in ('query', 'target_kind', 'language', 'facets')}
        body['card'] = card
        judge_id = 'J' + digest(body)[:24]
        visible = {'judge_id': judge_id, **body}
        if judge_id in known:
            if visible != known[judge_id]:
                raise ValueError('cannot reuse nonidentical visible input')
        else:
            new[judge_id] = visible
        mapping.append({'id': case['id'], 'arm': selection['arm'], 'policy': selection['policy'],
            'judge_id': judge_id, 'source_valid': card is not None, 'reused': judge_id in known})
    ordered = list(new.values())
    random.Random(2026101502).shuffle(ordered)
    args.output.mkdir(parents=True, exist_ok=False)
    for role, kinds in [('class-symbol', {'class', 'symbol'}), ('module-file', {'module', 'file'})]:
        (args.output / (role + '.jsonl')).write_text(''.join(canonical(r) + '\n'
            for r in ordered if r['target_kind'] in kinds))
    (args.output / 'mapping.jsonl').write_text(''.join(canonical(r) + '\n' for r in mapping))
    receipt = {'scope': 'only new byte-distinct query/card shadow pairs; original judgments reusable; no Gold',
        'principal_input_receipt_sha256': sha(principal_receipt),
        'principal_judgment_seal_sha256': sha(args.principal_judgment_seal),
        'shadows_registration_sha256': sha(shadow_path), 'selections': len(mapping),
        'new_visible_inputs': len(new), 'reused_selections': sum(r['reused'] for r in mapping),
        'seed': 2026101502, 'script_sha256': sha(__file__),
        'files': {p.name: sha(p) for p in args.output.glob('*.jsonl')}}
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps({k: receipt[k] for k in ('selections', 'new_visible_inputs', 'reused_selections')}))


if __name__ == '__main__':
    main()

"""Prepare or run a reproducible comparison without checking out either revision.

The default ONLY prepares an immutable git-archive baseline and source manifest.
Pass --run explicitly after other CPU-intensive work has finished. Both revisions
use the same installed Python dependencies and the same copied measurement runner.
No source programs from the external corpora are executed.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

BASELINE = '353fc1444823bded9e04b465e7ee64b3809bb043'
CORPORA = [('python-patterns', '/tmp/ken-pattern-corpus/python-patterns', 'patterns/'),
           ('cpp-patterns', '/tmp/ken-pattern-corpus/cpp-patterns', ''),
           ('guru-rust', '/tmp/ken-pattern-corpus/guru-rust', '')]
MAX_FILES = 20
REPEATS = 3


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def literal(path, name):
    """Read version/extension metadata without importing or running the engine."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f'{name} not found in {path}')


def engine_hashes(root):
    directory = root / 'src/ken/structural'
    return {str(p.relative_to(directory)): sha(p) for p in sorted(directory.rglob('*'))
            if p.suffix in {'.py', '.toml'}}


def sources(root, prefix, languages):
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    eligible = sorted(p for p in tracked if p and p.startswith(prefix)
                      and Path(p).suffix.lower() in languages
                      and not (root / p).is_symlink() and (root / p).is_file())
    if not eligible:
        raise ValueError(f'No source files under {root}/{prefix}')
    selected = [{'path': p, 'language': languages[Path(p).suffix.lower()],
                 'bytes': (root / p).stat().st_size, 'sha256': sha(root / p)}
                for p in eligible[:MAX_FILES]]
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'eligible_files': len(eligible), 'files': selected}


def commands(plan):
    result = {}
    for label, root in [('baseline', plan['baseline_root']), ('current', plan['workspace'])]:
        argv = [plan['python'], plan['runner'], '--no-diagnostics', '--require-stable',
                '--repeats', str(REPEATS), '--max-files', str(MAX_FILES),
                '--output', str(Path(plan['directory']) / (label + '.json'))]
        for case in plan['corpora']:
            argv += ['--case', case['name'], case['root'], case['prefix']]
        result[label] = {'argv': argv, 'cwd': root, 'PYTHONPATH': str(Path(root) / 'src')}
    return result


def prepare(workspace, directory, interpreter):
    directory.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', BASELINE + '^{commit}'],
                                     cwd=workspace, text=True).strip()
    archive = directory / ('baseline-' + commit[:12] + '.tar')
    baseline = directory / ('baseline-' + commit[:12])
    marker = directory / 'baseline-manifest.json'
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous['commit'] != commit or previous['engine_sha256'] != engine_hashes(baseline):
            raise ValueError('Existing baseline differs from its sealed manifest; use a new output directory')
    else:
        if baseline.exists():
            raise ValueError('Unsealed baseline already exists; use a new output directory')
        subprocess.run(['git', 'archive', '--format=tar', '--output', str(archive), commit],
                       cwd=workspace, check=True)
        baseline.mkdir()
        with tarfile.open(archive) as contents:
            contents.extractall(baseline, filter='data')
        save(marker, {'commit': commit, 'archive_sha256': sha(archive),
                      'engine_sha256': engine_hashes(baseline)})
    languages = literal(baseline / 'src/ken/structural/frontend.py', 'LANGUAGES')
    if languages != literal(workspace / 'src/ken/structural/frontend.py', 'LANGUAGES'):
        raise ValueError('The revisions select different source extensions; define an explicit common scope first')
    runner = directory / 'pipeline_runner.py'
    runner.write_bytes((workspace / 'examples/bench/validate_search_pipeline.py').read_bytes())
    plan = {'schema': 'ken-catalog-revision-comparison-plan/1',
            'prepared_utc': datetime.now(timezone.utc).isoformat(), 'timings_executed': False,
            'workspace': str(workspace), 'directory': str(directory), 'python': str(interpreter),
            'baseline_commit': commit, 'baseline_root': str(baseline),
            'baseline_ir_version': literal(baseline / 'src/ken/structural/model.py', 'IR_VERSION'),
            'runner': str(runner), 'runner_sha256': sha(runner),
            'repeats': REPEATS, 'max_files_per_corpus': MAX_FILES, 'languages': languages,
            'corpora': [{'name': name, 'root': str(Path(root).resolve()), 'prefix': prefix,
                         **sources(Path(root), prefix, languages)} for name, root, prefix in CORPORA],
            'method': {'execution_order': ['baseline', 'current'],
                       'cold': 'Empty disposable SQLite IR cache; parser/interpreter and OS pages are warm.',
                       'stages': 'Independent overlapping timings; do not add their durations.',
                       'precision': 'Not evaluated: match-count changes are not TP/FP labels.',
                       'small_sample': 'Three samples; p95 is their maximum, not a population estimate.',
                       'timing_gate': 'Preparation does not run benchmarks. Explicit --run is required.'}}
    plan['commands'] = commands(plan)
    save(directory / 'plan.json', plan)
    print(json.dumps({'prepared': str(directory / 'plan.json'), 'baseline_ir': plan['baseline_ir_version'],
                      'files': {c['name']: len(c['files']) for c in plan['corpora']},
                      'timings_executed': False}, indent=2))
    return plan


def verify_sources(plan):
    for case in plan['corpora']:
        actual = sources(Path(case['root']), case['prefix'], plan['languages'])
        if actual != {key: case[key] for key in ('commit', 'eligible_files', 'files')}:
            raise ValueError(f'Corpus changed since preparation: {case["name"]}')


def compare_reports(baseline, current):
    rows = []
    for before, after in zip(baseline['cases'], current['cases'], strict=True):
        if (before['name'], before['files']) != (after['name'], after['files']):
            raise ValueError('The revisions did not measure identical source inputs')
        timings = {}
        for phase in sorted(before['timings'].keys() & after['timings'].keys()):
            old, new = before['timings'][phase], after['timings'][phase]
            timings[phase] = {'baseline': old, 'current': new,
                             'p50_ratio_current_over_baseline': new['p50_ms'] / old['p50_ms'] if old['p50_ms'] else None}
        rows.append({'name': before['name'], 'files': before['files'],
                     'sizes': {'baseline': before['sizes'], 'current': after['sizes']},
                     'matches_by_rule': {'baseline': before['runs'][0]['matches_by_rule'],
                                         'current': after['runs'][0]['matches_by_rule']},
                     'timings': timings,
                     'all_runs_complete': all(r[k] for c in [before, after] for r in c['runs']
                                              for k in ('batch_complete', 'cold_complete', 'warm_complete')),
                     'cache_and_prepared_matches_equivalent': all(r['equivalent_matches'] for c in [before, after] for r in c['runs'])})
    return rows


def run(plan):
    verify_sources(plan)
    baseline = Path(plan['baseline_root'])
    sealed = json.loads((Path(plan['directory']) / 'baseline-manifest.json').read_text())
    if engine_hashes(baseline) != sealed['engine_sha256'] or sha(plan['runner']) != plan['runner_sha256']:
        raise ValueError('Sealed engine or measurement runner changed')
    reports = {}
    for label, command in commands(plan).items():
        verify_sources(plan)
        environment = dict(os.environ, PYTHONPATH=command['PYTHONPATH'], PYTHONDONTWRITEBYTECODE='1')
        log = Path(plan['directory']) / (label + '.log')
        print(f'Running {label}; progress: {log}', flush=True)
        with log.open('w') as output:
            subprocess.run(command['argv'], cwd=command['cwd'], env=environment,
                           stdout=output, stderr=subprocess.STDOUT, check=True)
        report = json.loads((Path(plan['directory']) / (label + '.json')).read_text())
        if Path(report['engine_root']).resolve() != (Path(command['cwd']) / 'src/ken/structural').resolve():
            raise ValueError('Worker imported the wrong revision')
        if not report['engine_unchanged_during_run']:
            raise ValueError('Worker reports unstable engine sources')
        for expected, measured in zip(plan['corpora'], report['cases'], strict=True):
            if expected['files'] != measured['files']:
                raise ValueError('Worker selected sources different from the sealed manifest')
        reports[label] = report
        verify_sources(plan)
    result = {'schema': 'ken-catalog-revision-comparison/1', 'plan': plan,
              'finished_utc': datetime.now(timezone.utc).isoformat(),
              'ir_versions': {key: report['ir_version'] for key, report in reports.items()},
              'engine_sha256': {key: report['engine_sha256'] for key, report in reports.items()},
              'runner_sha256': plan['runner_sha256'],
              'cases': compare_reports(reports['baseline'], reports['current'])}
    output = Path(plan['directory']) / 'comparison.json'
    save(output, result)
    print(f'Saved comparison: {output}', flush=True)
    if not all(case['all_runs_complete'] and case['cache_and_prepared_matches_equivalent'] for case in result['cases']):
        raise SystemExit('Evidence saved; incomplete queries or cache/prepared disagreements require review')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--directory', type=Path, default=Path('/tmp/ken-catalog-revision-comparison'))
    parser.add_argument('--run', action='store_true', help='Run previously prepared timings; wait until other CPU work is finished')
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.run:
        run(json.loads((directory / 'plan.json').read_text()))
    else:
        prepare(args.workspace.resolve(), directory, Path(sys.executable).absolute())


if __name__ == '__main__':
    main()

"""Inventory saved queries without confusing syntax conversion with semantic review.

Run from the repository root. This reads TOML text, never executes source fixtures.
"""
from pathlib import Path
import argparse
from collections import Counter
import json
import re
import tomllib


def inventory(root: Path):
    reviewed = {'singleton.shared_instance','singleton.observed_lazy_use','iterator#async-iterator','iterator#generator','iterator#delegated-generator','composite#recursive-contract', 'composite#recursive-nominal',
                'facade#object-surface','facade#module-surface','adapter#class-adapter',
                'decorator#typed-delegator','decorator#object-wrapper','decorator.result_forwarding',
                'bridge.returned_primitive','bridge#refined-composition','singleton.lazy_instance', 'factory-method#virtual-slot',
                'factory-method#contract-slot','factory-method.client_flow',
                'abstract-factory#nominal-families','abstract-factory#structural-families',
                'builder#mutable-product','builder#immutable-product','builder#accumulated-state',
                'state#state-enum',
                'observer#listener-registry','observer#event-bus','observer#map-key-registry',
                'prototype#explicit-copy','prototype#field-copy','prototype#language-copy','template-method#virtual-skeleton',
                'template-method#trait-default','template-method#composed-skeleton',
                'template-method.dependent_steps','mediator#direct-colleagues',
                'mediator#registered-colleagues','strategy#strategy-object',
                'strategy.consumed_policy','strategy.supplied_policy',
                'decorator#callable-wrapper','decorator#untyped-delegator','decorator#subclass-addition',
                'architecture.dependency-injection#retained-object',
                'architecture.dependency-injection#object-assignment',
                'architecture.dependency-injection#callable-input',
                'architecture.adapted-continuation-wrapper',
                'architecture.continuation-wrapper',
                'architecture.batch-work-queue','architecture.batch-work-queue#stored-batch',
                'architecture.batch-work-queue.drain'}
    rows = []
    files = []
    for directory in ('patterns', 'modern_patterns'):
        for path in sorted((root / 'src/ken/structural' / directory).glob('*.toml')):
            data = tomllib.loads(path.read_text())
            entries = [(data['id'], data)]
            for section, separator in (('variants','#'), ('operations','.')):
                entries.extend((data['id']+separator+row['id'],row) for row in data.get(section, []))
            for name, entry in entries:
                query = entry.get('query','')
                low_level = sorted(set(re.findall(r'\b(?:edge|walk)\s+(\w+)',query)))
                body = bool(re.search(r'\bbody\s*(?:(?:adjacent|linear)\s*)?\{',query))
                selectors = bool(re.search(r'\b(?:type|class|method|callable|field|param)\s+\$',query))
                status = ('missing_query' if not query else 'requires_rewrite' if low_level else
                          'behavior_reviewed' if name in reviewed else
                          'source_requires_review' if selectors or body else 'composition_requires_dependency_review')
                rows.append({'id':name,'file':str(path.relative_to(root)), 'status':status,
                             'has_body':body,'internal_relations':low_level})
            current = rows[-len(entries):]
            files.append({'id':data['id'],'file':str(path.relative_to(root)),
                          'all_queries_use_source_syntax':all(row['status'] not in ('missing_query','requires_rewrite') for row in current),
                          'has_legacy_query':bool(data.get('legacy_query'))})
    return {'scope':'23 GoF and modern catalog; syntax inventory is not detection accuracy',
            'counts':dict(sorted(Counter(row['status'] for row in rows).items())), 'files':files,'entries':rows}


def markdown(data):
    lines = ["# Estado de migración del catálogo", "",
             "Generado por `examples/bench/catalog_authoring_inventory.py`. "
             "Las cifras cuentan consultas raíz, variantes y operaciones por separado.", "",
             "Revisada significa revisión conductual acotada, no ausencia de FP/FN. "
             "Composición requiere revisar también sus dependencias. "
             "La columna legado indica `legacy_query` fuera de las consultas actuales.", "",
             "| Patrón | Con edge/walk | Sin query | Fuente por revisar | Composición | Revisadas | Legado |",
             "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for file in data['files']:
        counts = Counter(row['status'] for row in data['entries'] if row['file'] == file['file'])
        values = [str(counts[status]) for status in ('requires_rewrite','missing_query',
                  'source_requires_review','composition_requires_dependency_review','behavior_reviewed')]
        lines.append('| ' + file['id'] + ' | ' + ' | '.join(values) + ' | '
                     + ('sí' if file['has_legacy_query'] else 'no') + ' |')
    lines.extend(['', '## Entradas que todavía usan operadores internos', ''])
    lines.extend('- `' + row['id'] + '`' for row in data['entries'] if row['status'] == 'requires_rewrite')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--markdown',type=Path)
    args = parser.parse_args()
    data = inventory(Path(__file__).resolve().parents[2])
    result = json.dumps(data,indent=2,ensure_ascii=False)+'\n'
    if args.markdown:
        args.markdown.write_text(markdown(data))
    if args.output:
        args.output.write_text(result)
    else:
        print(result,end='')

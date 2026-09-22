"""Replay the variant/language ledger and render measured coverage.

Run from the repository: PYTHONPATH=. .venv/bin/python -m
examples.bench.audit_catalog_matrix --output docs/structural-validation/...
The known-failure ledger is read-only. Unexpected failures or fixes need review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from examples.bench.audit_catalog_semantics import audit
from ken.structural.frontend import LANGUAGES
from ken.structural.rules import builtin_rules
from tests.structural.catalog_matrix_support import DIRECTORY, FAMILIES, directed_cases, matrix_cases


def write_report(output: Path):
    cases = (*matrix_cases(), *directed_cases())
    inputs = []
    for case in cases:
        root, _, variant = case.target.partition('#')
        inputs.append(dict(id=case.id, rule=root, variant=variant or None,
                           language=case.language, source=case.source,
                           expected=case.expected, kind=case.family, why=case.reason))
    measured = audit(inputs)
    ledger = json.loads((DIRECTORY / 'known_failures.json').read_text())
    scope = json.loads((DIRECTORY / 'seeds.json').read_text())
    observations = {}
    unexpected = []
    for result in measured.pop('results'):
        selected = result['outcomes'][result['target']]
        known = ledger['cases'].get(result['id'])
        disagreement = result['verdict'] not in {'TP', 'TN'}
        if ((disagreement and (not known or known['observed'] != result['verdict']))
                or (known and not disagreement)):
            unexpected.append(result['id'])
        observations[result['id']] = dict(
            target=result['target'], language=result['language'], family=result['kind'],
            expected=result['expected'], actual=result['actual'], verdict=result['verdict'],
            complete=selected['complete'], unknown=selected['unknown'],
            diagnostics=result['diagnostics'], bindings=[m['bindings'] for m in selected['matches']],
            source_sha256=result['source_sha256'], stats=selected['stats'],
            timing_seconds=result['timing_seconds'], issue=known['issue'] if known else None,
            root_actual=bool(result['outcomes'][result['rule']]['matches']))
    cells = []
    for target, languages in sorted(scope['required'].items()):
        for language in sorted(languages):
            ids = [f'{target}/{language}/{family}' for family in FAMILIES]
            available = [id for id in ids if id in observations]
            directed = [id for id, value in observations.items()
                        if id.startswith('directed/') and value['target'] == target
                        and value['language'] == language]
            all_ids = available + directed
            failures = [id for id in all_ids if observations[id]['verdict'] not in {'TP', 'TN'}]
            cells.append(dict(target=target, language=language, case_ids=all_ids,
                              minimum_case_ids=available, directed_case_ids=directed,
                              missing=[id for id in ids if id not in observations],
                              counts=dict(Counter(observations[id]['verdict'] for id in all_ids)),
                              known_failures=failures,
                              status='missing' if len(ids) != len(available) else
                              'exercised-unexpected' if any(id in unexpected for id in all_ids) else
                              'exercised-with-known-failures' if failures else 'exercised-passing'))
    rules = [rule for rule in builtin_rules() if rule.source]
    unclaimed = {}
    for rule in rules:
        covered = {language for target, languages in scope['required'].items()
                   if target == rule.id or target.startswith(rule.id + '#') for language in languages}
        unclaimed[rule.id] = sorted(set(LANGUAGES.values()) - covered)
    design = [dict(target=rule.id + '#' + v['id'], status='design',
                   reason='No executable query; not counted as a tested negative.')
              for rule in rules for v in rule.variants if v['status'] == 'design']
    report = measured
    report.update(schema='ken-catalog-coverage/1',
                  required_cells=len(cells), cells=cells, observations=observations,
                  unclaimed_frontend_languages=unclaimed, design=design,
                  unexpected=unexpected,
                  ledger_sha256=hashlib.sha256((DIRECTORY / 'known_failures.json').read_bytes()).hexdigest(),
                  seeds_sha256=hashlib.sha256((DIRECTORY / 'seeds.json').read_bytes()).hexdigest(),
                  generator_sha256=hashlib.sha256((DIRECTORY.parent / 'catalog_matrix_support.py').read_bytes()).hexdigest())
    output.mkdir(parents=True, exist_ok=True)
    (output / 'matrix-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    grouped = {}
    for group, predicate in [('Matriz por variante/lenguaje', lambda v: not v['family'].startswith('directed-')),
                             ('Casos dirigidos adicionales', lambda v: v['family'].startswith('directed-'))]:
        grouped[group] = Counter(v['verdict'] for v in observations.values() if predicate(v))
    statuses = Counter(cell['status'] for cell in cells)
    lines = ['# Conteo verificable por patrón, variante, lenguaje y caso', '',
             f'Base `{report["base_commit"]}`, IR **{report["ir_version"]}**. '
             f'**{len(cells)} celdas**, **{len(matrix_cases())} casos de matriz** y '
             f'**{len(directed_cases())} casos dirigidos adicionales**. '
             f'Cada celda tiene {len(FAMILIES)} familias mínimas; no son el techo de cobertura.', '',
             'Las familias fijan el oráculo antes de consultar: `canonical` (positivo), '
             '`inert` (negativo claro), `noise-1` y `noise-20` (positivos válidos con '
             'instrucciones intercaladas, buscando FN), y `algorithm-removed` (negativo '
             'que conserva declaraciones pero elimina implementación, buscando FP). '
             '**TP/TN/FP/FN son resultados, no etiquetas que obliguen a conservar errores.**', '',
             'La matriz incluye todas las variantes ready y sus lenguajes anunciados en los TOML. '
             'Los tres roots sin variantes y las variantes sin lista de lenguajes tienen '
             'un ámbito explícito en seeds.json. Las combinaciones no anunciadas y las variantes '
             'design se enumeran abajo; no se contabilizan como aprobadas. '
             'Las quince operaciones se auditaron y tienen checks ABI previos; no se cuentan '
             'como variantes con esta matriz mínima.', '',
             '| Grupo | TP | TN | FP | FN |', '|---|---:|---:|---:|---:|']
    for name, count in grouped.items():
        lines.append('| ' + name + ' | ' + ' | '.join(str(count[k]) for k in ['TP', 'TN', 'FP', 'FN']) + ' |')
    lines += ['', f'**Celdas sin desacuerdos en el mínimo y sus casos dirigidos:** {statuses["exercised-passing"]}. '
              f'**Con regresiones conocidas:** {statuses["exercised-with-known-failures"]}. '
              f'**Celdas faltantes:** {statuses["missing"]}. '
              f'**Resultados inesperados respecto del ledger:** {len(unexpected)}.', '',
              '“Ejercitada” no equivale a implementación correcta. Los negativos inertes se '
              'repiten entre variantes y las transformaciones se parecen entre sí: los totales '
              'no son muestras independientes ni precisión/recall de producción. El mínimo '
              'uniforme se complementa con los contraejemplos específicos del reporte, los tests '
              'idiomáticos existentes y nuevos casos que se agreguen por causa. Un stub es un '
              'contraste de implementación, no prueba exhaustiva contra casi-patrones.', '',
              '## Cómo mantener el conteo', '',
              '1. Añadir una fuente y su procedencia a `tests/structural/catalog_matrix/seeds.json` '
              'cuando se anuncie una variante/lenguaje. El test de inventario falla si un TOML '
              'añade una combinación sin la celda correspondiente.',
              '2. Fijar expected y motivo antes de evaluar. Los casos dirigidos tienen fuente '
              'propia; no sustituirlos por variantes generadas del mismo ejemplo.',
              '3. Ejecutar pytest y este reporte. Un fallo nuevo falla el test; un fallo conocido '
              'sólo produce xfail tras verificar parsing y ejecución completa. Si se corrige, '
              'se produce un fallo XPASS hasta retirar su entrada exacta del ledger.',
              '4. Nunca registrar invalid/incomplete como TN ni generar el ledger automáticamente '
              'desde los resultados. Cada entrada tiene una causa revisada y propuesta de mejora.', '',
              '```sh\n.venv/bin/python -m pytest tests/structural/test_catalog_adversarial_matrix.py -q\n'
              'PYTHONPATH=. .venv/bin/python -m examples.bench.audit_catalog_matrix \\\n'
              '  --output docs/structural-validation/catalog-adversarial-2026-09-14\n```', '',
              'Archivos: [fuentes y ámbito](../../../tests/structural/catalog_matrix/seeds.json), '
              '[regresiones y causas](../../../tests/structural/catalog_matrix/known_failures.json), '
              '[resultados por caso](matrix-results.json), [reporte de cada patrón](README.md).', '',
              '## Cada celda', '',
              'Las columnas C/I/N1/N20/A muestran canonical, inert, noise-1, noise-20 y algorithm-removed. '
              'Cada combinación de fila y columna tiene el ID `target/language/family` en matrix-results.json. '
              'Dirigidos suma los casos adicionales de esa variante/lenguaje en orden TP/TN/FP/FN; '
              'las causas incluyen ambas fuentes de evidencia. Los ensayos que seleccionan sólo '
              'una raíz se muestran aparte, sin atribuirlos a una variante arbitraria.', '',
              '| Patrón / variante | Lenguaje | C | I | N1 | N20 | A | Dirigidos TP/TN/FP/FN | Causas pendientes |',
              '|---|---|---|---|---|---|---|---|---|']
    for cell in cells:
        verdicts = [observations[id]['verdict'] if id in observations else 'FALTA'
                    for id in [f'{cell["target"]}/{cell["language"]}/{f}' for f in FAMILIES]]
        issues = sorted({observations[id]['issue'] for id in cell['known_failures'] if observations[id]['issue']})
        extra = Counter(observations[id]['verdict'] for id in cell['directed_case_ids'])
        extra_text = '/'.join(str(extra[k]) for k in ('TP', 'TN', 'FP', 'FN'))
        lines.append('| `' + cell['target'] + '` | ' + cell['language'] + ' | '
                     + ' | '.join(verdicts) + ' | ' + extra_text + ' | ' + ', '.join(issues) + ' |')
    roots = sorted({(v['target'], v['language']) for v in observations.values()
                    if v['family'].startswith('directed-') and '#' not in v['target']})
    lines += ['', '## Ensayos dirigidos de raíz', '',
              'Estas filas seleccionan la query raíz, por lo que un match puede provenir de distintas variantes. '
              'Los tres roots sin variantes aparecen también en sus celdas anteriores: esta vista '
              'no añade casos al total.', '',
              '| Raíz | Lenguaje | TP | TN | FP | FN | Causas pendientes |', '|---|---|---:|---:|---:|---:|---|']
    for target, language in roots:
        values = [v for v in observations.values() if v['target'] == target and v['language'] == language
                  and v['family'].startswith('directed-')]
        counts = Counter(v['verdict'] for v in values)
        issues = sorted({v['issue'] for v in values if v['issue']})
        lines.append(f'| `{target}` | {language} | '
                     + ' | '.join(str(counts[k]) for k in ('TP', 'TN', 'FP', 'FN'))
                     + ' | ' + ', '.join(issues) + ' |')
    lines += ['', '## Combinaciones que no se anuncian como soportadas', '',
              'Esto distingue lenguajes del frontend de cobertura anunciada por patrón. '
              'Ruby está presente en el frontend y no tiene celdas anunciadas por estas queries. '
              'Estas ausencias quedan visibles; no prueban que el patrón sea imposible en el lenguaje.', '',
              '| Patrón raíz | Lenguajes del frontend fuera del ámbito anunciado |', '|---|---|']
    for target, languages in sorted(unclaimed.items()):
        lines.append(f'| `{target}` | {", ".join(languages) or "ninguno"} |')
    lines += ['', '## No implementado', '']
    lines += [f'- `{entry["target"]}`: {entry["reason"]}' for entry in design]
    lines += ['', '## Causas revisadas', '']
    for key, issue in ledger['issues'].items():
        ids = [id for id, failure in ledger['cases'].items() if failure['issue'] == key]
        lines += [f'**{key} — {issue["title"]} ({len(ids)} casos).** {issue["cause_and_fix"]}', '']
    lines += [f'Replay completo: {report["elapsed_seconds"]:.3f} s dentro del runner. '
              'Incluye construcción/consulta de muchos grafos pequeños; no mide escala de repositorio, '
              'cache de proyecto ni compilación de los programas. CPython valida la sintaxis de los '
              'snippets Python; los otros lenguajes tienen parsing Tree-sitter, sin certificación de typechecking.', '']
    (output / 'COVERAGE.md').write_text('\n'.join(lines))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = write_report(args.output)
    print(json.dumps(dict(counts=report['counts'], cells=report['required_cells'],
                          unexpected=report['unexpected']), ensure_ascii=False))
    if report['unexpected'] or any(cell['missing'] for cell in report['cells']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

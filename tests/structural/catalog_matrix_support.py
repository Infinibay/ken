"""Source-level matrix cases with oracles independent of detector output.

The JSON seeds identify a specific published variant and language. Transformations
are deterministic and never execute a seed. Coverage and known failures are
tracked separately: an xfail is exercised coverage, not a successful detector.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from ken.structural.frontend import FUNCTIONS, parser_for

DIRECTORY = Path(__file__).with_name('catalog_matrix')
FAMILIES = ('canonical', 'inert', 'noise-1', 'noise-20', 'algorithm-removed')


@dataclass(frozen=True)
class Case:
    id: str
    target: str
    language: str
    family: str
    expected: bool
    source: str
    reason: str
    origin: str


def body_nodes(source, language):
    data = source.encode()
    root = parser_for(language, 'matrix').parse(data).root_node
    assert not root.has_error, (language, source)
    bodies = []
    todo = [root]
    while todo:
        node = todo.pop()
        if node.type in FUNCTIONS:
            body = node.child_by_field_name('body')
            if body is not None:
                bodies.append((node, body))
        todo.extend(reversed(node.named_children))
    return data, bodies


def noise(source: str, language: str, count: int) -> str:
    """Insert independent arithmetic in concrete bodies, not just outside them."""
    if language == 'python':
        class Insert(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                self.generic_visit(node)
                if node.name != '__init__':
                    at = int(bool(node.body and isinstance(node.body[0], ast.Expr)
                                  and isinstance(node.body[0].value, ast.Constant)
                                  and isinstance(node.body[0].value.value, str)))
                    node.body[at:at] = ast.parse('\n'.join(
                        f'__ken_audit_noise_{i} = 1 + 2' for i in range(count))).body
                return node

            visit_AsyncFunctionDef = visit_FunctionDef

        return ast.unparse(ast.fix_missing_locations(Insert().visit(ast.parse(source)))) + '\n'
    data, bodies = body_nodes(source, language)
    points = set()
    for node, body in bodies:
        name = node.child_by_field_name('name')
        if node.type == 'constructor_declaration' or (name is not None and name.text == b'constructor'):
            continue  # Java/JS explicit base-constructor calls must stay first.
        if body.text.startswith(b'{'):
            points.add(body.start_byte + 1)
        elif language == 'ruby':
            # Ruby bodies are keyword-delimited: the statement goes after the header line.
            points.add(body.start_byte + (1 if body.text.startswith(b'\n') else 0))
    statement = {'javascript': 'const __ken_audit_noise_{i} = 1 + 2;',
                 'typescript': 'const __ken_audit_noise_{i} = 1 + 2;',
                 'java': 'int __ken_audit_noise_{i} = 1 + 2;',
                 'csharp': 'int __ken_audit_noise_{i} = 1 + 2;',
                 'cpp': 'int __ken_audit_noise_{i} = 1 + 2;',
                 'go': '_ = 1 + 2;', 'rust': 'let _ = 1 + 2;',
                 'ruby': '__ken_audit_noise_{i} = 1 + 2'}[language]
    inserted = ('\n' + '\n'.join(statement.format(i=i) for i in range(count)) + '\n').encode()
    for point in sorted(points, reverse=True):
        data = data[:point] + inserted + data[point:]
    if not points:
        # Concise expression closures have no statement body. Preserve their
        # semantics and report this family honestly, instead of inventing an edit.
        return source
    return data.decode()


def without_algorithm(source: str, language: str) -> str:
    """Retain declaration scaffolding, remove callable implementations.

    This negative tests an implementation contract. A declaration-only signature
    (e.g. a C++ copy constructor) can still match and must be classified as such.
    """
    if language == 'python':
        class Stub(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                node.body = ast.parse('raise NotImplementedError').body
                return node

            visit_AsyncFunctionDef = visit_FunctionDef

        return ast.unparse(ast.fix_missing_locations(Stub().visit(ast.parse(source)))) + '\n'
    data, bodies = body_nodes(source, language)
    # Replacing an outer function also removes its nested closures.
    selected = []
    for node, body in sorted(bodies, key=lambda pair: (pair[1].start_byte, -pair[1].end_byte)):
        if not any(a <= body.start_byte and body.end_byte <= b for a, b, _ in selected):
            replacement = {'javascript': '{ throw 0; }', 'typescript': '{ throw 0; }',
                           'java': '{ throw new UnsupportedOperationException(); }',
                           'csharp': '{ throw new System.NotImplementedException(); }',
                           'cpp': '{ throw 0; }', 'go': '{ panic("unimplemented") }',
                           'rust': '{ panic!("unimplemented") }',
                           'ruby': '\n raise NotImplementedError\n'}[language]
            selected.append((body.start_byte, body.end_byte, replacement.encode()))
    for start, end, replacement in reversed(selected):
        data = data[:start] + replacement + data[end:]
    text = data.decode()
    # An empty/throwing function* still implements the generator protocol.
    # Explicitly remove its generator marker for the negative oracle.
    if language in {'javascript', 'typescript'}:
        import re
        text = re.sub(r'\bfunction\s*\*', 'function ', text)
    return text


def inert(language):
    return {'python': 'class CatalogUnrelated:\n pass\n',
            'javascript': 'class CatalogUnrelated {}', 'typescript': 'class CatalogUnrelated {}',
            'java': 'class CatalogUnrelated {}', 'csharp': 'class CatalogUnrelated {}',
            'cpp': 'struct CatalogUnrelated {};', 'go': 'package p\ntype CatalogUnrelated struct{}\n',
            'rust': 'struct CatalogUnrelated;', 'ruby': 'class CatalogUnrelated\nend\n'}[language]


@lru_cache(maxsize=1)
def matrix_cases():
    manifest = json.loads((DIRECTORY / 'seeds.json').read_text())
    cases = []
    for seed in manifest['seeds']:
        target, language = seed['target'], seed['language']
        if language not in manifest['required'].get(target, []):
            continue
        for family in FAMILIES:
            source = seed['source']
            reason = 'Published variant source witness; oracle fixed before running the query.'
            if family.startswith('noise-'):
                source = noise(source, language, int(family.split('-')[1]))
                reason = ('Independent arithmetic in concrete non-constructor bodies must preserve the algorithm.'
                          if source != seed['source'] else
                          'Expression-only body: no statement insertion applied; not an interleaving witness.')
            elif family == 'inert':
                source = inert(language)
                reason = 'An unrelated declaration supplies no collaboration or implementation.'
            elif family == 'algorithm-removed':
                source = without_algorithm(source, language)
                reason = 'Declaration scaffolding remains; every callable implementation was removed.'
            cases.append(Case(f'{target}/{language}/{family}', target, language, family,
                              family not in {'inert', 'algorithm-removed'}, source, reason, seed['origin']))
    return tuple(cases)


@lru_cache(maxsize=1)
def directed_cases():
    """Individually labelled counterexamples, beyond the uniform minimum."""
    path = DIRECTORY.parents[2] / 'docs/structural-validation/catalog-adversarial-2026-09-14/cases.json'
    return tuple(Case('directed/' + c['id'],
                      c['rule'] + ('#' + c['variant'] if c.get('variant') else ''),
                      c['language'], 'directed-' + c['kind'], c['expected'], c['source'],
                      c['why'], str(path.relative_to(DIRECTORY.parents[2])))
                 for c in json.loads(path.read_text()))

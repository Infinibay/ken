"""Local miss checks must use the lookup value, not any assignment in the method."""
from __future__ import annotations

import pytest

from .test_flyweight_explicit_interning import detect

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', *, noise: bool = False, inverted: bool = False) -> str:
    key = '"other"' if mutation == 'wrong-lookup-key' else 'key'
    pool = 'other' if mutation == 'wrong-lookup-pool' else 'pool'
    if language == 'python':
        lines = [f'        result = self.{pool}.get({key})']
        if mutation == 'reset-before-guard': lines += ['        result = None']
        if mutation == 'reset-and-restore': lines += ['        result = None', '        result = self.pool.get(key)']
        if mutation == 'construct-before-guard': lines += ['        result = Glyph(key)']
        if noise: lines += ['        audit = 17 * 3', '        print(audit)']
        if inverted:
            lines += ['        if result is not None:', '            print("hit")', '        else:']
        else:
            lines += ['        if result is None:']
        if mutation == 'lookup-after-guard':
            lines[0] = '        result = None'
            lines += ['            result = self.pool.get(key)']
        if mutation != 'construct-before-guard': lines += ['            result = Glyph(key)']
        if noise: lines += ['            print("created")']
        if mutation == 'overwrite-before-insert': lines += ['            result = None']
        lines += ['            self.pool[key] = result']
        if mutation == 'overwrite-after-insert': lines += ['        result = None']
        if noise: lines += ['        print("returning")']
        lines += ['        return result']
        return '''class Glyph:
    def __init__(self, key): self.key = key
class Pool:
    def __init__(self):
        self.pool = {}
        self.other = {}
    def get(self, key):
''' + '\n'.join(lines) + '\n'
    java = language == 'java'
    empty = 'null' if java else 'undefined'
    lookup = f'this.{pool}.get({key})' if java else f'this.{pool}[{key}]'
    lines = [f'{"Glyph" if java else "let"} result = {lookup};']
    if mutation == 'reset-before-guard': lines += [f'result = {empty};']
    if mutation == 'reset-and-restore': lines += [f'result = {empty};', f'result = {lookup};']
    if mutation == 'construct-before-guard': lines += ['result = new Glyph(key);']
    log = 'System.out.println' if java else 'console.log'
    if noise: lines += [f'{"int" if java else "const"} audit = 17 * 3;', f'{log}(audit);']
    if inverted:
        lines += [f'if (result {"!=" if java else "!=="} {empty}) {{ {log}("hit"); }} else {{']
    else:
        lines += [f'if (result {"==" if java else "==="} {empty}) {{']
    if mutation == 'lookup-after-guard':
        lines[0] = f'{"Glyph" if java else "let"} result = {empty};'
        lines += [f'result = {lookup};']
    if mutation != 'construct-before-guard': lines += ['result = new Glyph(key);']
    if noise: lines += [f'{log}("created");']
    if mutation == 'overwrite-before-insert': lines += [f'result = {empty};']
    lines += ['this.pool.put(key, result);' if java else 'this.pool[key] = result;', '}']
    if mutation == 'overwrite-after-insert': lines += [f'result = {empty};']
    if noise: lines += [f'{log}("returning");']
    lines += ['return result;']
    if java:
        prefix = '''import java.util.Map;
import java.util.HashMap;
class Glyph { String key; Glyph(String key) {this.key=key;} }
class Pool {
 Map<String,Glyph> pool=new HashMap<>();
 Map<String,Glyph> other=new HashMap<>();
 Glyph get(String key) {
'''
    else:
        prefix = '''class Glyph { constructor(public key:string) {} }
class Pool {
 pool:{[key:string]:Glyph}={};
 other:{[key:string]:Glyph}={};
 get(key:string):Glyph {
'''
    return prefix + '\n'.join(lines) + '\n}}'


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', [False, True])
@pytest.mark.parametrize('inverted', [False, True])
def test_local_lookup_survives_noise_and_inverted_miss_guard(language, noise, inverted):
    matches = detect(language, source(language, noise=noise, inverted=inverted))
    assert len(matches) == 1
    assert '/CLASS:Pool' in matches[0]['bindings']['$unit']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', [
    'reset-before-guard', 'reset-and-restore', 'construct-before-guard',
    'lookup-after-guard', 'overwrite-before-insert', 'overwrite-after-insert',
    'wrong-lookup-key', 'wrong-lookup-pool',
])
def test_local_guard_rejects_uncorrelated_values_and_extra_writes(language, mutation):
    assert not detect(language, source(language, mutation, noise=True))


@pytest.mark.parametrize('language', ('python', 'typescript'))
def test_local_truthiness_guard(language):
    text = source(language, noise=True)
    text = text.replace('if result is None:', 'if not result:').replace(
        'if (result === undefined)', 'if (!result)')
    assert len(detect(language, text)) == 1


@pytest.mark.parametrize('language', LANGUAGES)
def test_local_lookup_is_independent_of_names(language):
    text = source(language, noise=True).replace('Pool', 'Registry').replace('result', 'selected').replace('pool', 'entries')
    assert len(detect(language, text)) == 1


@pytest.mark.parametrize('language', LANGUAGES)
def test_local_lookup_with_many_statements_stays_within_query_budget(language):
    from ken.structural.frontend import lower_source
    from ken.structural.kenql import Engine, query_graph
    from ken.structural.query import QueryBudget
    from ken.structural.rules import builtin_rules, query_registry
    from ken.structural.semantic import link_project

    text = source(language, noise=True)
    if language == 'python':
        # Large body, but retain the variant's documented 32-edge gap bound.
        before = '\n'.join(f'        noise_{i} = {i} + 1\n        print(noise_{i})' for i in range(40))
        text = text.replace('        result = self.pool.get(key)', before + '\n        result = self.pool.get(key)')
        text = text.replace('        print(audit)', '\n'.join(f'        print({i})' for i in range(10)))
    else:
        log = 'System.out.println' if language == 'java' else 'console.log'
        declaration = 'int' if language == 'java' else 'const'
        before = '\n'.join(f'{declaration} noise_{i} = {i} + 1; {log}(noise_{i});' for i in range(40))
        lookup = 'Glyph result = this.pool.get(key);' if language == 'java' else 'let result = this.pool[key];'
        text = text.replace(lookup, before + '\n' + lookup)
        text = text.replace(f'{log}(audit);', '\n'.join(f'{log}({i});' for i in range(10)))
    graph = link_project([lower_source(text, language, 'pool.' + language)])
    assert not graph.diagnostics
    registry = query_registry(builtin_rules())
    engine = Engine(query_graph(graph), registry,
                    QueryBudget(max_matches=200, max_rows=500000, max_states=100000, timeout_ms=3000),
                    'strict')
    result = engine.execute(registry['flyweight#explicit-interning'])
    assert result['complete'], result
    assert len(result['matches']) == 1

"""Flyweight pooling flow and explicitly stronger intrinsic-state contracts."""
from __future__ import annotations

import pytest

from .test_gof_executable import evaluate

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: bool = True) -> str:
    receiver = 'self' if language == 'python' else 'this'
    write_key = '0' if mutation == 'wrong-insert-key' else 'key'
    return_key = '0' if mutation == 'wrong-return-key' else 'key'
    create_key = '0' if mutation == 'abandoned-construction' else 'key'
    if language == 'python':
        before = '        audit = 17 * 3\n        print(audit)\n' if noise else ''
        after = '        independent = 9 + 1\n        print(independent)\n' if noise else ''
        abandoned = '        unused = Glyph(key)\n' if mutation == 'abandoned-construction' else ''
        condition = 'True' if mutation == 'replace-every-time' else 'key not in self.pool'
        wrong_state = '        self.font = x\n' if mutation == 'captures-extrinsic' else ''
        return f'''class Glyph:
    def __init__(self, font): self.font = font
    def draw(self, x):
{wrong_state}        return self.font + x
class Pool:
    def __init__(self): self.pool = {{}}
    def get(self, key):
{before}{abandoned}        if {condition}:
            self.pool[{write_key}] = Glyph({create_key})
{after}        return self.pool[{return_key}]

def draw_pair(pool: Pool):
    first = pool.get(7)
    second = pool.get(7)
    first.draw(10)
    second.draw(20)
'''
    if language == 'java':
        before = 'int audit = 17 * 3; System.out.println(audit);' if noise else ''
        after = 'int independent = 9 + 1; System.out.println(independent);' if noise else ''
        abandoned = 'Glyph unused = new Glyph(key);' if mutation == 'abandoned-construction' else ''
        condition = 'true' if mutation == 'replace-every-time' else 'this.pool[key] == null'
        wrong_state = 'this.font = x;' if mutation == 'captures-extrinsic' else ''
        return f'''class Glyph {{
    int font;
    Glyph(int font) {{ this.font = font; }}
    int draw(int x) {{ {wrong_state} return this.font + x; }}
}}
class Pool {{
    Glyph[] pool = new Glyph[100];
    Glyph get(int key) {{
        {before} {abandoned}
        if ({condition}) {{ this.pool[{write_key}] = new Glyph({create_key}); }}
        {after} return this.pool[{return_key}];
    }}
}}
class Client {{
    void drawPair(Pool pool) {{
        Glyph first = pool.get(7); Glyph second = pool.get(7);
        first.draw(10); second.draw(20);
    }}
}}
'''
    before = 'const audit = 17 * 3; console.log(audit);' if noise else ''
    after = 'const independent = 9 + 1; console.log(independent);' if noise else ''
    abandoned = 'const unused = new Glyph(key);' if mutation == 'abandoned-construction' else ''
    condition = 'true' if mutation == 'replace-every-time' else 'this.pool[key] === undefined'
    wrong_state = 'this.font = x;' if mutation == 'captures-extrinsic' else ''
    return f'''class Glyph {{
    font: number;
    constructor(font: number) {{ this.font = font; }}
    draw(x: number): number {{ {wrong_state} return this.font + x; }}
}}
class Pool {{
    pool: Array<Glyph> = [];
    get(key: number): Glyph {{
        {before} {abandoned}
        if ({condition}) {{ this.pool[{write_key}] = new Glyph({create_key}); }}
        {after} return this.pool[{return_key}];
    }}
}}
function drawPair(pool: Pool) {{
    const first = pool.get(7); const second = pool.get(7);
    first.draw(10); second.draw(20);
}}
'''


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', [False, True])
def test_flyweight_tolerates_independent_work(language, noise):
    assert evaluate(source(language, noise=noise), language, 'flyweight')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['wrong-insert-key', 'wrong-return-key', 'abandoned-construction'])
def test_pool_requires_same_key_and_retained_creation(language, mutation):
    assert not evaluate(source(language, mutation), language, 'flyweight')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Pooling query does not prove miss-only creation or stable returned identity; algorithms/flyweight.md')
def test_interning_must_reuse_an_existing_entry(language):
    assert not evaluate(source(language, 'replace-every-time'), language, 'flyweight')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Stronger stable-intrinsic-state contract: draw stores per-call position into shared font; generic pooling query does not inspect use')
def test_desired_stable_intrinsic_state_rejects_extrinsic_overwrite(language):
    assert not evaluate(source(language, 'captures-extrinsic'), language, 'flyweight')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Indexed key facts identify bindings but do not preserve their values through assignments; algorithms/flyweight.md')
def test_interning_preserves_key_value_until_return(language):
    text = source(language)
    if language == 'python':
        text = text.replace('        return self.pool[key]', '        key = 0\n        return self.pool[key]')
    else:
        text = text.replace('return this.pool[key];', 'key = 0; return this.pool[key];')
    assert not evaluate(text, language, 'flyweight')

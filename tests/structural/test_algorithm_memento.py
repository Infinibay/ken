"""Memento algorithm contracts, with unmet historical guarantees kept explicit."""
from __future__ import annotations

import pytest

from .test_gof_executable import evaluate
from .test_memento_accessors import source as accessor_source

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: bool = True) -> str:
    mutable = mutation == 'mutable-history'
    receiver = 'self' if language == 'python' else 'this'
    stored = '0' if mutation == 'lost-constructor-input' else 'state'
    supplied = '0' if mutation == 'wrong-save-input' else receiver + '.state'
    restored = 'snapshot.other' if mutation == 'wrong-snapshot-field' else 'snapshot.saved'
    target = 'other' if mutation == 'wrong-origin-field' else 'state'
    if mutation == 'no-snapshot-read':
        restored = '0'
    if language == 'python':
        audit = '        audit = 17 * 3\n        print(audit)\n' if noise else ''
        overwrite = '        self.state = 0\n' if mutation == 'restore-overwrite' else ''
        edit = '        self.state[0] = 99\n' if mutable else '        self.state = 99\n'
        return f'''class Snapshot:
    def __init__(self, state):
        self.saved = {stored}
        self.other = 0
class Originator:
    def __init__(self):
        self.state = {'[1]' if mutable else '1'}
        self.other = 0
    def save(self):
{audit}        return Snapshot({supplied})
    def restore(self, snapshot: Snapshot):
{audit}        self.{target} = {restored}
{overwrite}    def edit(self):
{edit}
def exercise(origin: Originator):
    snapshot = origin.save()
    origin.edit()
    origin.restore(snapshot)
'''
    if language == 'java':
        state_type = 'int[]' if mutable else 'int'
        initial = 'new int[]{1}' if mutable else '1'
        audit = 'int audit = 17 * 3; System.out.println(audit);' if noise else ''
        overwrite = 'this.state = 0;' if mutation == 'restore-overwrite' else ''
        edit = 'this.state[0] = 99;' if mutable else 'this.state = 99;'
        return f'''class Snapshot {{
    {state_type} saved; int other;
    Snapshot({state_type} state) {{ this.saved = {stored}; this.other = 0; }}
}}
class Originator {{
    {state_type} state = {initial}; int other = 0;
    Snapshot save() {{ {audit} return new Snapshot({supplied}); }}
    void restore(Snapshot snapshot) {{ {audit} this.{target} = {restored}; {overwrite} }}
    void edit() {{ {edit} }}
}}
class Exercise {{
    void run(Originator origin) {{
        Snapshot snapshot = origin.save(); origin.edit(); origin.restore(snapshot);
    }}
}}
'''
    state_type = 'number[]' if mutable else 'number'
    initial = '[1]' if mutable else '1'
    audit = 'const audit = 17 * 3; console.log(audit);' if noise else ''
    overwrite = 'this.state = 0;' if mutation == 'restore-overwrite' else ''
    edit = 'this.state[0] = 99;' if mutable else 'this.state = 99;'
    return f'''class Snapshot {{
    saved: {state_type}; other: number = 0;
    constructor(state: {state_type}) {{ this.saved = {stored}; }}
}}
class Originator {{
    state: {state_type} = {initial}; other: number = 0;
    save(): Snapshot {{ {audit} return new Snapshot({supplied}); }}
    restore(snapshot: Snapshot): void {{ {audit} this.{target} = {restored}; {overwrite} }}
    edit(): void {{ {edit} }}
}}
function exercise(origin: Originator) {{
    const snapshot = origin.save(); origin.edit(); origin.restore(snapshot);
}}
'''


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', [False, True])
def test_scalar_snapshot_round_trip_tolerates_independent_work(language, noise):
    assert evaluate(source(language, noise=noise), language, 'memento')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['wrong-save-input', 'wrong-origin-field', 'no-snapshot-read'])
def test_snapshot_rejects_broken_capture_or_restore_origin(language, mutation):
    assert not evaluate(source(language, mutation), language, 'memento')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['lost-constructor-input', 'wrong-snapshot-field', 'restore-overwrite'])
def test_direct_snapshot_requires_capture_and_final_restoration(language, mutation):
    assert not evaluate(source(language, mutation), language, 'memento')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Stronger historical-snapshot contract: explicit shared array mutation invalidates saved history; not proved by structural Memento query')
def test_desired_historical_snapshot_rejects_shared_mutable_array(language):
    assert not evaluate(source(language, 'mutable-history'), language, 'memento')


@pytest.mark.parametrize('language', LANGUAGES)
def test_accessor_snapshot_also_tolerates_independent_logging(language):
    text = accessor_source(language)
    if language == 'python':
        text = text.replace('  return result', '  audit=17*3\n  print(audit)\n  return result')
    else:
        audit = 'int audit=17*3;System.out.println(audit);' if language == 'java' else 'const audit=17*3;console.log(audit);'
        text = text.replace('return result;', audit + 'return result;')
    assert evaluate(text, language, 'memento')

"""Malformed Tree-sitter spans cannot make execution annotation loop forever."""
import subprocess
import sys

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


@pytest.mark.parametrize('language', ['python', 'java', 'javascript', 'typescript', 'csharp', 'cpp', 'go', 'rust'])
def test_error_recovery_always_terminates_and_withholds_execution(language):
    # Exercise an isolated process so an accidental syntax-graph cycle fails
    # with a bounded timeout instead of hanging the whole structural suite.
    script = '''
import sys
from ken.structural.frontend import lower_source
g=lower_source('class Shared {} ???',sys.argv[1],'malformed')
assert g.diagnostics
assert all(op.attrs['execution']=='unknown' for op in g.operations)
'''
    result = subprocess.run([sys.executable, '-c', script, language], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_fallthrough_does_not_cross_a_branch_or_return():
    g = link_project([lower_source('def f(x):\n a=1\n if x:\n  return a\n b=2\n return b\n', 'python', 'flow.py')])
    fallthrough = {(f.subject, f.object) for f in g.facts if f.relation == 'CFG_FALLTHROUGH'}
    expected = {(f.subject, f.object) for f in g.facts if f.relation == 'CFG_NEXT' and f.attrs['kind'] == 'next'}
    assert fallthrough == expected and fallthrough
    branch_or_return = {op.id for op in g.operations if op.kind in {'BRANCH', 'RETURN'}}
    assert not any(source in branch_or_return for source, _ in fallthrough)

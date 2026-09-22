"""Authored KQL2 checks the collaboration, including control-flow counterexamples."""
import pytest
from .contract_support import contract_matches


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('mode', ['positive', 'reversed', 'unused_fields', 'exclusive_branches', 'one_service'])
def test_facade_coordinates_its_own_services_on_one_path(language, mode):
    if language == 'python':
        actions = '  self.first.start()\n  print(123)\n  self.second.finish()'
        if mode == 'reversed': actions = '  self.second.finish()\n  print(123)\n  self.first.start()'
        if mode == 'unused_fields': actions = '  other_first.start()\n  other_second.finish()'
        if mode == 'exclusive_branches': actions = '  if flag:\n   self.first.start()\n  else:\n   self.second.finish()'
        if mode == 'one_service': actions = '  self.first.start()'
        source = 'class First:\n def start(self): pass\nclass Second:\n def finish(self): pass\nclass Surface:\n first: First\n second: Second\n def run(self, flag, other_first: First, other_second: Second):\n' + actions + '\n'
    else:
        actions = 'this.first.start(); log(); this.second.finish();'
        if mode == 'reversed': actions = 'this.second.finish(); log(); this.first.start();'
        if mode == 'unused_fields': actions = 'other_first.start(); other_second.finish();'
        if mode == 'exclusive_branches': actions = 'if (flag) { this.first.start(); } else { this.second.finish(); }'
        if mode == 'one_service': actions = 'this.first.start();'
        source = ('class First { void start() {} } class Second { void finish() {} } class Surface { First first; Second second; void run(boolean flag, First other_first, Second other_second) { ' + actions + ' } }'
                  if language == 'java' else 'class First { start() {} } class Second { finish() {} } class Surface { first: First; second: Second; run(flag: boolean, other_first: First, other_second: Second) { ' + actions + ' } }')
    assert bool(contract_matches(source, language, 'facade#object-surface')) is (mode in ('positive','reversed'))

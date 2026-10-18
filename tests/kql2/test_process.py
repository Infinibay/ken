"""Process startup owns GC policy; embedded sessions do not."""

import subprocess
import sys


def test_process_freezes_only_startup_and_still_collects_new_cycles():
    code = '''
import gc, weakref
from ken.kql2.process import prepare_process
before = gc.get_freeze_count()
prepare_process(freeze=False)
assert gc.get_freeze_count() <= before
prepare_process(freeze=True)
assert gc.isenabled()
assert gc.get_freeze_count() > before
class Cycle: pass
cycle = Cycle()
cycle.self = cycle
reference = weakref.ref(cycle)
del cycle
gc.collect()
assert reference() is None
before = gc.get_freeze_count()
prepare_process(freeze=True)
assert gc.get_freeze_count() == before
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

"""A real NumberWords iterator exposed missing coarse WRITES for augmented state."""
import pytest

from .test_gof_executable import evaluate


@pytest.mark.parametrize('update',['self.index += 1','self.index = self.index + 1'])
@pytest.mark.parametrize('noise',[False,True])
def test_field_assignment_occurrence_retains_explicit_cursor(update,noise):
    source='''class Cursor:
 def __init__(self,start,stop):
  self.index=start
  self.stop=stop
 def __iter__(self): return self
 def __next__(self):
  if self.index>self.stop: raise StopIteration
  current=self.index
  UPDATE
  return current
'''.replace('UPDATE',update)
    if noise: source=source.replace('  current=', '  metric=1+2\n  print(metric)\n  current=')
    assert evaluate(source,'python','iterator')
    assert not evaluate(source.replace(update,'metric=1+2\n  print(metric)'),'python','iterator')

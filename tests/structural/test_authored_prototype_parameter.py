"""Copy input is correlated with its constructor parameter, not a fixed index."""
import pytest
from .contract_support import contract_matches

SOURCES = {
 'python': 'class Record:\n def __init__(self, ignored, state):\n  self.state = state\n def duplicate(self):\n  return Record(0, self.state)\n',
 'java': 'class Record { int state; Record(int ignored,int value){this.state=value;} Record duplicate(){return new Record(0,this.state);} }',
 'typescript': 'class Record { state: number; constructor(ignored: number,value: number){this.state=value;} duplicate(){return new Record(0,this.state);} }',
 'csharp': 'class Record { int state; Record(int ignored,int value){this.state=value;} Record duplicate(){return new Record(0,this.state);} }',
}

@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('wrong_slot',[False,True])
def test_copy_supplies_retained_parameter_in_any_position(language,wrong_slot):
 source=SOURCES[language]
 if wrong_slot:
  source=source.replace('0, self.state','self.state, 0').replace('0,this.state','this.state,0')
 assert bool(contract_matches(source,language,'prototype#explicit-copy')) is not wrong_slot


def test_copy_supplies_retained_parameter_by_name():
 source=SOURCES['python'].replace('Record(0, self.state)','Record(state=self.state, ignored=0)')
 assert contract_matches(source,'python','prototype#explicit-copy')

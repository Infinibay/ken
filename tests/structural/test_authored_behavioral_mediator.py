"""Bidirectional participant coordination, authored as source declarations and calls."""
from pathlib import Path
import tomllib
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget

SOURCES={
 'python':'''class Peer:
 center: Center
 def event(self):
  print(1)
  self.center.coordinate()
 def receive(self): pass
class Center:
 first: Peer
 second: Peer
 def coordinate(self):
  self.first.receive()
  print(2)
  self.second.receive()
''',
 'java':'''class Peer { Center center; void event(){log();center.coordinate();} void receive(){} }
 class Center { Peer first; Peer second; void coordinate(){first.receive(); log();second.receive();} }''',
 'typescript':'''class Peer { center:Center; event(){log();this.center.coordinate();} receive(){} }
 class Center { first:Peer; second:Peer; coordinate(){this.first.receive();log();this.second.receive();} }''',
}
@pytest.mark.parametrize('variant',['registered-colleagues','direct-colleagues'])
@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','no_callback','one_recipient','wrong_center'])
def test_colleagues_can_share_a_type_but_need_both_directions(language,mutation,variant):
 source=SOURCES[language]
 if mutation=='no_callback': source=source.replace('self.center.coordinate()','print(0)').replace('this.center.coordinate()','log()').replace('center.coordinate()','log()')
 if mutation=='one_recipient':source=source.replace('second.receive()','first.receive()')
 if mutation=='wrong_center':
  source=source.replace('center: Center','center: Unrelated').replace('Center center','Unrelated center').replace('center:Center','center:Unrelated')
  source+= '\nclass Unrelated:\n def coordinate(self): pass\n' if language=='python' else '\nclass Unrelated { void coordinate(){} }' if language=='java' else '\nclass Unrelated { coordinate(){} }'
 data=tomllib.loads((Path(__file__).parents[2]/'src/ken/structural/patterns/mediator.toml').read_text())
 q=next(x['query'] for x in data['variants'] if x['id']==variant)
 index=query_graph(link_project([lower_source(source,language,'sample.'+language)]))
 result=Executor(index,{},QueryBudget()).execute(compile_source(q))
 assert result['complete'],result
 assert bool(result['matches']) is (mutation=='positive'),result

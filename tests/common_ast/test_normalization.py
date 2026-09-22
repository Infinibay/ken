import json
from dataclasses import replace
import pytest
from ken.common_ast import parse, Program
from .sources import SOURCES


@pytest.mark.parametrize('language',SOURCES)
def test_common_kinds_and_ordered_tree_in_each_supported_language(language):
 source=SOURCES[language]; p=parse(source,language,'sample')
 assert not p.diagnostics
 kinds={n.kind for n in p.nodes}
 assert {'module','callable','parameter','if','return','identifier','literal'} <= kinds
 assert 'while' in kinds or language=='go' and 'for' in kinds
 assert any(n.operator=='+' for n in p.nodes)
 assert any(n.operator=='>' for n in p.nodes)
 for parent in p.nodes:
  kids=[n for n in p.nodes if n.parent==parent.id]
  assert [n.ordinal for n in kids]==list(range(len(kids)))
  assert all(parent.start<=n.start<=n.end<=parent.end for n in kids)
 assert Program.from_dict(json.loads(json.dumps(p.to_dict())))==p


@pytest.mark.parametrize('language',SOURCES)
def test_parameter_and_local_are_distinct_symbols_and_return_is_resolved(language):
 p=parse(SOURCES[language],language)
 x=[s for s in p.symbols if s.name=='x']; y=[s for s in p.symbols if s.name=='y']
 assert len(x)==len(y)==1
 assert x[0].id!=y[0].id and x[0].kind=='parameter'
 returns=[n for n in p.nodes if n.kind=='return']
 references=[r for r in p.references if any(n.id<r.node<n.subtree_end for n in returns)]
 assert any(r.symbol==y[0].id and r.mode=='read' for r in references)


def test_opaque_nodes_are_retained_with_explicit_coverage():
 p=parse('def f(x):\n match x:\n  case [a,b]: return a\n','python')
 assert len(p.nodes)>10
 assert any(n.kind=='match' for n in p.nodes)
 assert all('normalization_unknown' in n.flags for n in p.nodes if n.kind=='opaque')


def test_utf8_ranges_are_bytes_and_identity_is_not_name():
 p=parse('def café():\n π=1\n return π\n','python')
 assert next(n for n in p.nodes if n.name=='π').end-next(n for n in p.nodes if n.name=='π').start==2
 assert len({n.id for n in p.nodes})==len(p.nodes)


def test_control_variants_are_preserved():
 p=parse('int f() { for(int i=0;i<3;i++) { if(i) continue; } return 1; }','cpp')
 loop=next(n for n in p.nodes if n.kind=='for')
 assert {'init','condition','step','body'} <= {n.role for n in p.nodes if n.parent==loop.id}
 assert any(n.kind=='continue' for n in p.nodes)


@pytest.mark.parametrize('language,source',[
 ('python','def f():\n yield 1\n yield from g()\n'),
 ('javascript','async function* f() { yield 1; yield* g(); await h(); }'),
 ('typescript','async function* f() { yield 1; yield* g(); await h(); }'),
])
def test_yield_delegation_and_async_remain_distinct(language,source):
 p=parse(source,language)
 yields=[n for n in p.nodes if n.kind=='yield']
 assert len(yields)==2 and sum('delegated' in n.flags for n in yields)==1
 if language!='python': assert any(n.kind=='await' for n in p.nodes)


def test_invalid_parent_is_rejected_on_decode():
 p=parse('x=1','python'); data=p.to_dict(); data['nodes'][1]['parent']=99
 with pytest.raises(ValueError): Program.from_dict(data)

"""Approved source quantifiers are declaration contracts, not pattern detectors."""
import pytest
from ken.kql2 import parse
from ken.kql2.compiler import compile,CompileError
from ken.kql2.graph import relational_plan
from ken.kql2.execution import execute
from ken.kql2.service import search
from ken.kql2.source_quantifiers import quantify
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.model import IR,Entity
from ken.structural_store import Store

HEADER='language "kql/2"; module requirements; '
QUERY=HEADER+'''pattern Restricted(out TypeDecl $type) {
 type $type {}
 require exists constructor of $type;
 require every constructor of $type { visibility: private; }
}
query q {use Restricted(type:$selected);select $selected;}
'''

SOURCES={
 'java':'class A {private A(){}}',
 'csharp':'class A {private A(){}}',
 'typescript':'class A {private constructor(){}}',
}

def run(ir,query=QUERY,reference=False):
 executor=Executor(query_graph(ir),{},None);executor.reference=reference
 return executor.execute(relational_plan(compile(parse(query))))

@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('reference',[False,True])
@pytest.mark.parametrize('change',['private','public','protected','empty','overloads','static-initializer','comment'])
def test_quantified_constructor_visibility(language,reference,change):
 text=SOURCES[language]
 if change in ('public','protected'):text=text.replace('private',change)
 if change=='empty':text='class A {}'
 if change=='overloads':
  text='class A {private constructor();private constructor(x:number);private constructor(x?:number){}}' if language=='typescript' else 'class A {private A(){}private A(int x){}}'
 if change=='static-initializer':
  text=text[:-1]+('static A(){}' if language=='csharp' else 'static {}')+'}'
 if change=='comment':text=text.replace('private','/*private*/public')
 result=run(link_project([lower_source(text,language,'source')]),reference=reference)
 assert result['complete'],result
 assert bool(result['matches']) is (change in ('private','overloads','static-initializer')),result


@pytest.mark.parametrize('quantifier,values,closed,expected',[
 ('exists',(),True,False),('every',(),True,True),
 ('exists',(),False,None),('every',(),False,None),
 ('exists',(True,),False,True),('every',(False,),False,False),
 ('every',(True,None),True,None),('exists',(False,None),True,None),
])
def test_quantifier_truth_is_independent_of_constructor_domain(quantifier,values,closed,expected):
 assert quantify(quantifier,values,closed) is expected


def test_every_empty_is_vacuously_true_but_exists_excludes_it():
 ir=link_project([lower_source('class A {}','java','source')])
 assert run(ir,QUERY.replace(' require exists constructor of $type;',''))['matches']
 assert not run(ir)['matches']

@pytest.mark.parametrize('change',['missing-inventory','partial','unknown-visibility','missing-member','imported'])
def test_incomplete_constructor_inventory_is_unknown(change):
 ir=link_project([lower_source(SOURCES['csharp'],'csharp','source')])
 if change=='partial':ir=link_project([lower_source('partial '+SOURCES['csharp'],'csharp','source')])
 if change=='missing-inventory':ir.facts=[f for f in ir.facts if f.relation!='CONSTRUCTOR_INVENTORY']
 if change=='unknown-visibility':
  for entity in ir.entities.values():
   if entity.attrs.get('instance_constructor'):entity.attrs['visibility_status']='unsupported';entity.attrs['visibility']='unknown'
 if change=='missing-member':ir.facts=[f for f in ir.facts if f.relation!='HAS_METHOD']
 if change=='imported':
  ir=IR('source','java');ir.entities['external']=Entity('external','CLASS','Imported','external.jar',1,1,{'external':True});ir.add('external','ENTITY','CLASS')
 result=run(ir)
 assert not result['matches'] and result['unknown'],result


def test_known_public_counterexample_defeats_every_even_if_inventory_is_open():
 ir=link_project([lower_source('partial class A {public A(){}}','csharp','source')])
 result=run(ir)
 assert not result['matches'] and not result['unknown'],result


def test_public_visibility_can_be_quantified_without_any_singleton_structure():
 ir=link_project([lower_source('class A {public A(){}}','java','source')])
 assert run(ir,QUERY.replace('visibility: private','visibility: public'))['matches']

@pytest.mark.parametrize('text',[
 'require exists constructor of $missing;',
 'require every constructor of $type {}',
 'require every constructor of $type {name: "A";}',
 'require every constructor of $type {visibility: /private/;}',
 'require every constructor of $type {visibility: private;visibility: public;}',
 'require exists method of $type;',
 'require exists constructor of $type {visibility: private;}',
])
def test_unsupported_forms_fail_before_execution(text):
 with pytest.raises((CompileError,ValueError)):
  compile(parse(HEADER+'query q {type $type {} '+text+'select $type;}'))


def test_named_input_aliases_and_snapshot_reopen(tmp_path):
 query=HEADER+'''pattern Restricted(in TypeDecl $owner) {
 require exists constructor of $owner;
 require every constructor of $owner {visibility: private;}
 }
 query q {type $candidate {} bind $alias=$candidate;use Restricted(owner:$alias);select $candidate;}
 '''
 database=tmp_path/'snapshot.db'
 with Store(database) as store:
  unit=store.put_unit('source',lower_source(SOURCES['java'],'java','source'),'h','v')
  snapshot=store.publish([unit],expected_parent=None)
  first=execute(compile(parse(query)),store,snapshot)
  assert first.complete and len(first.rows)==1
 with Store(database) as store:
  second=execute(compile(parse(query)),store,snapshot,reference=True)
  assert second.complete and second.rows==first.rows


def test_public_service_reuses_serialized_compilation_and_results(tmp_path):
 (tmp_path/'A.java').write_text(SOURCES['java'])
 first=search(tmp_path,QUERY)
 second=search(tmp_path,QUERY)
 assert first['complete'] and first['rows']==second['rows'] and len(second['rows'])==1
 assert second['analysis']['result_cache']=='disk_hit'


@pytest.mark.parametrize('visibility',['protected internal','private protected'])
def test_known_compound_visibility_is_a_counterexample_to_private(visibility):
 ir=link_project([lower_source('class A {'+visibility+' A(){}}','csharp','source')])
 result=run(ir)
 assert not result['matches'] and not result['unknown'],result


NAMED_WITNESS=HEADER+'''pattern UniqueDispatch(out Callable $owner, out Callable $helper) {
 callable $owner {}
 callable $helper {}
 require one dispatch of $owner named $helper;
}
query q {use UniqueDispatch(owner: $selected, helper: $other);select $selected;}
'''

SELF_WITNESS=HEADER+'''pattern Recursive(out Callable $owner) {
 callable $owner {}
 require one dispatch of $owner;
}
query q {use Recursive(owner: $selected);select $selected;}
'''

DISPATCH_SOURCES={
 'once':'def helper(y):\n    return y\ndef owner(x):\n    helper(x)\n    return 0\n',
 'twice':'def helper(y):\n    return y\ndef owner(x):\n    helper(x)\n    helper(x + 1)\n    return 0\n',
 'other-name':'def helper(y):\n    return y\ndef owner(x):\n    audit(x)\n    return 0\n',
 'self-once':'def owner(x):\n    if x > 1:\n        owner(x - 1)\n    return 0\n',
 'self-twice':'def owner(x):\n    owner(x - 1)\n    owner(x - 2)\n    return 0\n',
}


@pytest.mark.parametrize('name,expected',[
 ('once',True),('twice',False),('other-name',False),
])
def test_named_dispatch_counts_the_witness_spelling(name,expected):
 ir=link_project([lower_source(DISPATCH_SOURCES[name],'python','source')])
 result=run(ir,NAMED_WITNESS)
 assert result['complete'],result
 assert bool(result['matches']) is expected,result


@pytest.mark.parametrize('name,expected',[('self-once',True),('self-twice',False)])
def test_bare_dispatch_still_counts_the_owners_own_name(name,expected):
 ir=link_project([lower_source(DISPATCH_SOURCES[name],'python','source')])
 result=run(ir,SELF_WITNESS)
 assert result['complete'],result
 assert bool(result['matches']) is expected,result


@pytest.mark.parametrize('text',[
 'require one dispatch of $owner named $missing;',
 'require one allocation of $owner named $helper;',
 'require every dispatch of $owner named $helper;',
])
def test_only_one_dispatch_accepts_a_named_witness(text):
 with pytest.raises((CompileError,ValueError)):
  compile(parse(HEADER+'query q {callable $owner {} callable $helper {} '
                +text+'select $owner;}'))

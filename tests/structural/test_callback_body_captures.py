"""Approved nested BODY captures describe evaluated calls, not assignments."""
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor

QUERY='''language "kql/2";module callbacks;
pattern p(out Callable $iterator,out Operation $loop,out Operation $exit,out Value $accepted){
 callable $iterator{param $callback{name:"callback";}param $items{name:"items";}
 body{iterate $items as $item as $loop{body{
 let $accepted=call $callback{argument $item at 0;};
 if($accepted == false){break $loop as $exit;}
 }}}}
}query q{use p(iterator:$iterator,loop:$loop,exit:$exit,accepted:$accepted);select $iterator,$loop,$exit,$accepted;}'''


def run(body):
 source='package t\nfunc Each(items []int, callback func(int) bool) {for _,item := range items {'+body+'}}'
 graph=link_project([lower_source(source,'go','case.go')])
 return Executor(query_graph(graph),{},None).execute(compile_source(QUERY))

@pytest.mark.parametrize('body',[
 'if callback(item) == false {break}',
 'accepted := callback(item); if accepted == false {break}',
])
def test_evaluated_call_capture_exported_from_nested_body(body):
 result=run(body)
 assert result['matches'],result
 assert not result['unknown'],result
 for row in result['matches']:
  assert set(row['bindings'])=={'$iterator','$loop','$exit','$accepted'}

@pytest.mark.parametrize('body',[
 'callback(item); if callback(0) == false {break}',
 'accepted := callback(item); accepted = true; if accepted == false {break}',
 'accepted := callback(item); if accepted == false {for {break}}',
])
def test_callback_condition_and_break_belong_to_the_matched_loop(body):
 result=run(body)
 assert not result['matches'],result

@pytest.mark.parametrize('language,source',[
 ('javascript','function Each(items,callback){for(const item of items){if(callback(item)==false){break;}}}'),
 ('typescript','function Each(items:number[],callback:(x:number)=>boolean){for(const item of items){if(callback(item)==false){break;}}}'),
 ('python','def Each(items,callback):\n for item in items:\n  if callback(item)==False:\n   break\n'),
])
def test_inline_call_has_no_source_assignment(language,source):
 graph=link_project([lower_source(source,language,'case.'+language)])
 result=Executor(query_graph(graph),{},None).execute(compile_source(QUERY))
 assert result['matches'],result
 assert not result['unknown'],result

@pytest.mark.parametrize('language,source,proven',[
 ('go','package t\nfunc Each(items []int,callback func(int) bool){for _,item:=range items{if !callback(item){break}}}',True),
 ('typescript','function Each(items:number[],callback:(x:number)=>boolean){for(const item of items){if(!callback(item)){break;}}}',True),
 ('javascript','function Each(items,callback){for(const item of items){if(!callback(item)){break;}}}',False),
 ('python','def Each(items,callback):\n for item in items:\n  if not callback(item):\n   break\n',False),
])
def test_negation_requires_accredited_boolean_result(language,source,proven):
 graph=link_project([lower_source(source,language,'case.'+language)])
 result=Executor(query_graph(graph),{},None).execute(compile_source(QUERY))
 assert bool(result['matches']) is proven,result
 if not proven:assert result['unknown'],result

@pytest.mark.parametrize('extension,source',[
 ('go','package t\nfunc Each(items []int,callback func(int) bool){for _,item:=range items{if !callback(item){break}}}'),
 ('ts','function Each(items:number[],callback:(x:number)=>boolean){for(const item of items){if(!callback(item)){break;}}}'),
])
def test_saved_backend_nested_capture_and_boolean_contract(tmp_path,extension,source):
 from ken.kql2.service import search
 (tmp_path/('case.'+extension)).write_text(source)
 result=search(tmp_path,QUERY,cache_mb=0)
 assert result['rows'],result

@pytest.mark.parametrize('body',[
 'if callback(item)==false {for {break}}',
 'if callback(item)==false {continue}',
 'if callback(0)==false {break}',
 'if callback(item)==true {break}',
])
def test_inline_counterexamples(body):
 result=run(body)
 assert not result['matches'],result

@pytest.mark.parametrize('body,positive',[
 ('break if callback.call(item) == false',True),
 ('break if callback.call(0) == false',False),
 ('break if callback.call(item) == true',False),
])
def test_ruby_suffix_break_preserves_condition_and_receiver(body,positive):
 source='def Each(items,callback)\n for item in items\n  '+body+'\n end\nend'
 # Ruby invokes the retained callable through its explicit call method. Select
 # the occurrence and receiver without pretending every .call is a Proc slot.
 query=QUERY.replace('param $items{name:"items";}','param $items{name:"items";} call $invocation{name:"call";}')
 query=query.replace('call $callback{argument','call $invocation{receiver:$callback;argument')
 graph=link_project([lower_source(source,'ruby','case.rb')])
 result=Executor(query_graph(graph),{},None).execute(compile_source(query))
 assert bool(result['matches']) is positive,result

@pytest.mark.parametrize('language,source',[
 ('javascript','function Each(items,callback){for(const item of items){let accepted=callback(item);if(accepted==false){break;}}}'),
 ('typescript','function Each(items:number[],callback:(x:number)=>boolean){for(const item of items){let accepted=callback(item);if(accepted==false){break;}}}'),
 ('python','def Each(items,callback):\n for item in items:\n  accepted=callback(item)\n  if accepted==False:\n   break\n'),
])
@pytest.mark.parametrize('reassigned',[False,True])
def test_saved_callback_result_requires_current_origin(language,source,reassigned):
 if reassigned:
  source=source.replace('if(accepted','accepted=true;if(accepted').replace('  if accepted','  accepted=True\n  if accepted')
 graph=link_project([lower_source(source,language,'case.'+language)])
 result=Executor(query_graph(graph),{},None).execute(compile_source(QUERY))
 assert bool(result['matches']) is (not reassigned),result

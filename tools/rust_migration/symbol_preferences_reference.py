"""First independent observations of explicit symbol requirements and preferences."""
from pathlib import Path
import gzip,hashlib,json,subprocess
from .reference import Reference,reference_env,verify_reference

FIXTURE='crates/ken-retrieval/tests/fixtures/symbol-preferences-reference.json.gz'
SUITE=['tests/retrieval/test_source_operations.py::test_query_requirements_are_explicit_and_skip_negated_prose','tests/retrieval/test_source_operations.py::test_preference_is_stable_and_never_drops_unknown_candidates','tests/retrieval/test_source_operations.py::test_negated_refresh_is_not_a_request_for_a_flag_update','tests/retrieval/test_source_operations.py::test_invocation_requirement_is_an_active_positive_action_with_an_object','tests/retrieval/test_symbol_ranking.py::test_only_explicit_code_operators_are_requirements','tests/retrieval/test_symbol_ranking.py::test_bitwise_descriptions_do_not_require_boolean_keyword_witnesses']

def cases():
    rows=[]
    queries=[]
    for action in ('invoke','invokes','invoking'):
        for prefix in ('Find a handler that ','Never ','without ','not; ','avoid registering then ','prevent later ','cannot ','not. '):
            queries.append(prefix+action+' a listener')
    queries+=['invoke','invokes no listener','invokes nothing','invoked later','Show the `invoke` definition','invokes\u00a0a callback','invokes\x1ca callback','invokes\ud800','Find a handler that invokes\nlistener','without invoking a callback! invokes another callback','keep exception cause','preserve exception cause after attribute-error','retain exception cause after attribute error','not keep exception cause','preserve exception without its cause','preserve exception; without cause','mapping key assignment remembers old value','dictionary key set with previous state','mapping key never assigning old value','returns flag or updates it','returns boolean or refresh state','return flag or default without updating','returns state or assignment','returns state without updating or refresh','Find a handler for AND and OR expressions.','Find `not` and `in` operators','bit-wise AND OR NOT IN IS','bit wise `AND` or OR','bitwise AND but `in`','AND_1 AND2 _OR OR_ NOT','`aNd` and `Is`','`and_or` and `or2`','KAND İOR ſNOT and ıIS','🙂 AND\x00`not`\ud800']
    test_queries=['Which regression checks the value?','Find tests for code','Find test helpers','Find a test helper','Where does a test helper create values?','Where is behavior tested?','Where are values tested using mocks?','Find a test-double factory for testing','Find a test-double helper','Show regression fixtures','¿Qué pruebas verifican el valor?','Find integration tests','Which tests factory creates values?','Find functions with tests','find TESTS','Where is a regression helper?']
    for purpose in ('auto','implementation','tests'):
        for query in queries+test_queries:
            rows.append(dict(id='requirements-'+str(len(rows)),kind='requirements',input=dict(request=dict(query=query,purpose=purpose))))
    for query in ['Find tests that invoke a handler AND preserve exception cause','Find test helpers with OR','Find code that keeps exception cause','Find code that retains exception cause after attribute error','Find code with NOT and `in`','Find a bitwise AND handler','Find code','Find tests with OR']:
        for count in(0,1,3,10):
            for reverse in(False,True):
                witnesses=[['invocation','cause:AttributeError'],['cause:Other'],[],['cause:unknown','invocation'],['cause:'],['snapshot_keyed_write','returned_flag_refresh']]
                implementations=['return left && right','return first || second','return not item in values','OR AND NOT IN IS','and or not in is','return first | second']
                rows.append(dict(id='preference-'+str(len(rows)),kind='preferences',input=dict(request=dict(query=query),witnesses=[witnesses[i%len(witnesses)]for i in range(count)],test_cases=[i%3==1 for i in range(count)],implementations=[implementations[i%len(implementations)]for i in range(count)],order=list(range(count))[::-1]if reverse else list(range(count)))))
    return rows

def sources():
    return {
      'tests/test_sample.py': 'def test_top():\n    return 1\n\ndef helper():\n    def test_nested():\n        return 2\n    return test_nested\n\nclass Suite:\n    def test_method(self):\n        return 3\n    def helper(self):\n        return 4\n\nclass test_class:\n    pass\n',
      'app.py':'def test_production():\n    return 1\n',
      'tests/test_stub.pyi':'def test_stub() -> int: ...\n',
      'tests/Sample.java':'class Sample {\n @Test\n void direct() {}\n @org.junit.jupiter.api.ParameterizedTest\n void qualified() {}\n @RepeatedTest(3)\n void repeated() {}\n @TestFactory\n Object factory() { return null; }\n @TestTemplate\n void template() {}\n @Tested\n void helper() {}\n void testNamed() {}\n}\n',
      'Production.java':'class Production {\n @Test\n void annotated() {}\n}\n',
      'tests/sample.js':'function test_function() { return 1; }\n',
    }

SCRIPT=r'''
import dataclasses,json,pathlib,platform,sys
import pytest
import ken.retrieval.symbol_requirements as original
from ken.retrieval.model import SearchRequest,EntityKey
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
records=[]
for case in request['cases']:
 data=case['input'];required=original.requirements(SearchRequest(**data['request']))
 result=dict(operations=sorted(required.operations),operators=sorted(required.operators),test_case=required.test_case)
 if case['kind']=='preferences':
  order=original.prefer_operations(required.operations,data['witnesses'],data['order'])
  if required.test_case:order=sorted(order,key=lambda i:not data['test_cases'][i])
  result['order']=original.prefer_explicit_code_terms(data['request']['query'],data['implementations'],order)
 records.append(dict(**case,result=result))
physical=pathlib.Path(request['catalog_root']);physical.mkdir()
catalog=make_catalog(physical,request['sources'])
input_=dict(files={name:list(source.encode())for name,source in request['sources'].items()},owners=[dict(key=dataclasses.asdict(key),passages=[dataclasses.asdict(p)for p in ps])for key,ps in catalog.owners.items()])
# Change disk after construction: identity classification must still use catalog bytes.
for name in request['sources']:(physical/name).write_text('changed after catalog creation\n')
classifications=[dict(key=dataclasses.asdict(key),test_case=original.is_test_case(key,catalog))for key in catalog.owners]
unknown=EntityKey(path='missing.py',kind='function',qualname='test_missing')
classifications.append(dict(key=dataclasses.asdict(unknown),test_case=original.is_test_case(unknown,catalog)))
catalogs=[dict(input=input_,result=classifications)]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
discovered=[];states=[]
code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-symbol-preferences-reference/1',cases=records,catalogs=catalogs,discovered=discovered,test_states=states,original_test_exit=code,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()))
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n');sys.exit(code)
'''

def digest(value):
    return hashlib.sha256(json.dumps({k:value[k]for k in('cases','catalogs')},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-symbol-preferences-reference/1','preference reference format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'preference observer differs')
        require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==cases(),'preference inputs differ')
        require(all(set(c)=={'id','kind','input','result'}for c in value['cases']),'incomplete preference observations')
        require(value['observations_sha256']==digest(value),'preference observation digest differs')
        require(len(value['catalogs'])==1 and value['catalogs'][0]['input']['files']=={k:list(v.encode())for k,v in sources().items()},'preference catalog source differs')
        require(value['original_test_exit']==0 and len(value['discovered'])==len(set(value['discovered']))==13,'preference original test roots differ')
        require({s['nodeid']for s in value['test_states']}==set(value['discovered'])and all(s['when']=='call'and s['outcome']=='passed'for s in value['test_states']),'preference original roots incomplete')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9'),'preference original runtime differs')
        require(value['reference_fingerprint']=='5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038','preference original source differs')
        return[]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]

def capture(reference:Reference,out:Path):
    if out.exists():raise FileExistsError(out)
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    out.mkdir(parents=True,exist_ok=False);(out/'capture.py').write_text(SCRIPT)
    request=dict(reference=str(reference.root),cases=cases(),sources=sources(),catalog_root=str(out/'catalog'),suite=SUITE,junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    result=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=180)
    (out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    if result.returncode:raise ValueError('preference original capture failed: '+result.stdout.decode(errors='replace')[-1500:]+result.stderr.decode(errors='replace')[-1500:])
    value=json.loads((out/'observations.json').read_bytes());value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=reference.fingerprint);value['observations_sha256']=digest(value)
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source changed')
    errors=validate_reference(value)
    if errors:raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value

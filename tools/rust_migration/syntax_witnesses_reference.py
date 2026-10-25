"""First independent observations of the frozen Java/JS/TS witness backend."""
from pathlib import Path
import gzip,hashlib,json,subprocess
from .reference import Reference,reference_env,verify_reference
FIXTURE='crates/ken-retrieval/tests/fixtures/syntax-witnesses-reference.json.gz'
SUITE=['tests/retrieval/test_source_operations.py::test_returned_flag_update_is_same_value_not_just_an_or_token','tests/retrieval/test_source_operations.py::test_java_witnesses_use_the_catalog_snapshot_after_disk_changes','tests/retrieval/test_source_operations.py::test_a_nested_java_lambda_return_does_not_belong_to_the_enclosing_method','tests/retrieval/test_source_operations.py::test_invocation_uses_owned_body_not_stored_callbacks_defaults_or_nested_bodies']
def cases():
    rows=[]
    bodies=[('stored','return flag;'),('call','return attempt();'),('new','return new Entry();'),('refresh','return flag || (flag = attempt());'),('parentheses','return ((flag)) || (((flag = ((attempt())))));'),('other-target','return flag || (other = attempt());'),('bitwise','return flag | (flag = attempt());'),('three-or','return flag || (flag = attempt()) || other;'),('rhs-or','return flag || ((flag = attempt()) || other);'),('new-assigned','return flag || (flag = new Entry());'),('member','return this.flag || (this.flag = this.attempt());'),('indexed','return slots [ key ] || (slots[key] = attempt());'),('literal-spaces','return slots["a b"] || (slots["ab"] = attempt());'),('literal-quotes',"return slots['a'] || (slots[\"a\"] = attempt());"),('comment-target','return (/*hint*/flag) || (flag = attempt());'),('comment-call','return flag || (flag = (/*hint*/attempt()));'),('branch','if (flag) { return other; }\n    return flag || (flag = attempt());')]
    for suffix in('java','js','mjs','cjs','ts','tsx'):
        for name,body in bodies:
            source=('class Demo {\n Object flag, other;\n Object selected() {\n    '+body+'\n }\n}\n')if suffix=='java'else('function selected(flag, other) {\n    '+body+'\n}\n')
            rows.append(dict(id=suffix+'-'+name,files={'sample.'+suffix:source},mode='real'))
    extra=[('java-constructor','Sample.java','class Sample {\n Sample() { super(); }\n}\n'),('java-nested','Sample.java','class Sample {\n Object selected() {\n  return () -> { return flag || (flag = attempt()); };\n }\n}\n'),('java-local-class','Sample.java','class Sample {\n Object selected() {\n  class Local { Object field = attempt(); void deferred() { other(); } }\n  return null;\n }\n}\n'),('java-oneline','Sample.java','class Sample { Object selected() { return attempt(); } }\n'),('js-nested','sample.js','function selected() {\n const later = () => { return flag || (flag = attempt()); };\n return later;\n}\n'),('js-generator','sample.js','function* selected() { yield attempt(); }\n'),('js-default','sample.js','function selected(value = attempt()) { return value; }\n'),('js-arrow-expr','sample.js','const selected = () => flag || (flag = attempt());\n'),('js-arrow-block','sample.js','const selected = () => { return flag || (flag = attempt()); };\n'),('js-expression','sample.js','const selected = function() { return attempt(); };\n'),('js-class','sample.js','class Sample { selected() { return attempt(); } get value() { return this.flag; } }\n'),('ts-typed','sample.ts','function selected(flag: boolean): boolean { return flag || (flag = attempt()); }\n'),('ts-declaration','sample.ts','declare function selected(flag: boolean): boolean;\n'),('tsx-element','sample.tsx','const View = () => <Card value={attempt()} />;\n'),('js-recovery','sample.js','function selected() {\n return attempt();\n}\n???\n')]
    rows.extend(dict(id=name,files={path:source},mode='real')for name,path,source in extra)
    for mode in('crop-end','crop-start','expand-end'):
        rows.append(dict(id='extent-'+mode,files={'sample.js':'function selected() {\n return attempt();\n}\n// trailing\n'},mode=mode))
    return rows
SCRIPT=r'''
import dataclasses,hashlib,importlib.metadata,json,pathlib,platform,sys
import pytest
import ken.retrieval.source_operations as original
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.model import Span
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
records=[]
for case in request['cases']:
 directory=pathlib.Path(request['catalog_root'])/case['id'];directory.mkdir(parents=True)
 catalog=make_catalog(directory,case['files'])
 if case['mode']!='real':
  owners={}
  for key,passages in catalog.owners.items():
   if key.qualname=='selected':
    adjusted=[]
    for p in passages:
     span=p.entity_span
     if case['mode']=='crop-end':span=Span(span.start_line,span.end_line-1)
     elif case['mode']=='crop-start':span=Span(span.start_line+1,span.end_line)
     else:span=Span(span.start_line,span.end_line+1)
     adjusted.append(dataclasses.replace(p,span=span,entity_span=span))
    passages=adjusted
   owners[key]=passages
  catalog=SourceCatalog(directory,owners)
 physical=dict(files={name:list(source.encode())for name,source in case['files'].items()},owners=[dict(key=dataclasses.asdict(key),passages=[dataclasses.asdict(p)for p in passages])for key,passages in catalog.owners.items()])
 for name in case['files']:(directory/name).write_text('changed after catalog construction\n')
 observer=original.OperationWitnesses(catalog);observed=[]
 for key in catalog.owners:
  cold=observer.for_owner(key);warm=observer.for_owner(key)
  observed.append(dict(key=dataclasses.asdict(key),cold=sorted(cold),warm=sorted(warm)))
 records.append(dict(id=case['id'],input=physical,result=observed))
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
discovered=[];states=[]
code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-syntax-witnesses-reference/1',cases=records,inputs_sha256=hashlib.sha256(json.dumps(request['cases'],sort_keys=True).encode()).hexdigest(),discovered=discovered,test_states=states,original_test_exit=code,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),packages={p:importlib.metadata.version(p)for p in('tree-sitter','tree-sitter-language-pack')}))
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n');sys.exit(code)
'''
def digest(value):
    return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-syntax-witnesses-reference/1','witness format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'witness observer differs')
        require(value['inputs_sha256']==hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest(),'witness inputs differ')
        require([c['id']for c in value['cases']]==[c['id']for c in cases()],'witness cases differ')
        for case,source in zip(value['cases'],cases(),strict=True):
            require(set(case)=={'id','input','result'}and case['input']['files']=={p:list(s.encode())for p,s in source['files'].items()},'witness physical source differs')
            require([r['key']for r in case['result']]==[o['key']for o in case['input']['owners']]and all(r['cold']==r['warm']for r in case['result']),'witness membership/cache differs')
        require(value['observations_sha256']==digest(value),'witness observations differ')
        require(value['original_test_exit']==0 and len(value['discovered'])==len(set(value['discovered']))==4,'witness original roots differ')
        require({s['nodeid']for s in value['test_states']}==set(value['discovered'])and all(s['when']=='call'and s['outcome']=='passed'for s in value['test_states']),'witness original roots incomplete')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9',packages={'tree-sitter':'0.25.2','tree-sitter-language-pack':'1.8.1'}),'witness original runtime differs')
        require(value['reference_fingerprint']=='5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038','witness frozen source differs')
        return[]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def capture(reference:Reference,out:Path):
    if out.exists():raise FileExistsError(out)
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    inputs=dict(reference=str(reference.root),cases=cases(),catalog_root=str(out/'catalogs'),suite=SUITE,junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
    (out/'inputs.json').write_text(json.dumps(inputs,ensure_ascii=True)+'\n')
    child=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=180)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError('witness original failed: '+child.stdout.decode(errors='replace')[-2000:]+child.stderr.decode(errors='replace')[-2000:])
    value=json.loads((out/'observations.json').read_bytes());value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=reference.fingerprint);value['observations_sha256']=digest(value)
    if verify_reference(reference.root,reference.manifest_path)or validate_reference(value):raise ValueError('witness original validation failed: '+str(validate_reference(value)))
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value

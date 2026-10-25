"""Disjoint first observations of Python nonspace backtracking before its fix."""
from pathlib import Path
import hashlib,json,subprocess
from .reference import Reference,reference_env,verify_reference
FIXTURE='crates/ken-retrieval/tests/fixtures/symbol-preferences-whitespace-reference.json.gz'
def cases():
    spaces=[9,10,11,12,13,28,29,30,31,32,133,160,5760,*range(8192,8203),8232,8233,8239,8287,12288]
    queries=['Find a handler that invokes '+chr(point)+suffix for point in spaces for suffix in('','no listener','nothing','callback')]
    queries+=['Find a handler that invokes \x00','Find a handler that invokes \ud800']
    return [dict(id='nonspace-'+str(i),kind='requirements',input=dict(request=dict(query=query)))for i,query in enumerate(queries)]
SCRIPT=r'''
import hashlib,json,pathlib,platform,sys
from ken.retrieval.symbol_requirements import requirements
import ken.retrieval.symbol_requirements as module
from ken.retrieval.model import SearchRequest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(module.__file__).resolve().is_relative_to(root/'src')
records=[]
for case in request['cases']:
 result=requirements(SearchRequest(**case['input']['request']))
 records.append(dict(**case,result=dict(operations=sorted(result.operations),operators=sorted(result.operators),test_case=result.test_case)))
value=dict(format='ken-symbol-preferences-whitespace/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()))
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def validate(value):
    try:
        def require(ok):
            if not ok:raise ValueError('whitespace observation differs')
        require(value['format']=='ken-symbol-preferences-whitespace/1')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest())
        require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==cases())
        require(value['observations_sha256']==hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest())
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9'))
        require(value['reference_fingerprint']=='5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038')
        return[]
    except(KeyError,TypeError,ValueError):return['whitespace observation differs']
def capture(reference:Reference,out:Path):
    if out.exists():raise FileExistsError(out)
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    request=dict(reference=str(reference.root),cases=cases(),result=str(out/'observations.json'))
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    result=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=60)
    (out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    if result.returncode:raise ValueError(result.stderr.decode(errors='replace'))
    value=json.loads((out/'observations.json').read_bytes());value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=reference.fingerprint)
    value['observations_sha256']=hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    if verify_reference(reference.root,reference.manifest_path)or validate(value):raise ValueError('whitespace original differs')
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value

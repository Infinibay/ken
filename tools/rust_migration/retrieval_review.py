"""Supplemental actual-original regressions, without rerunning accepted observations/tests."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from .retrieval_reference import SCRIPT,passage,owners,digest
from .reference import Reference,reference_env
from .native_json import identity,load,NativeJsonCapture
from .retrieval_validate import FORMAT,compare_observations,requests,source_identity
from .index_validate import require,same_value

def definitions():
    cases=[]
    for field,lengths,averages,k1 in [('identity',{},{},-1.),('body',{'body':-1},{'body':3.},1.2)]:
        cases.append(dict(id='review:zero-divisor:'+field,kind='bm25f',input=dict(frequencies={field:1},lengths=lengths,averages=averages,document_frequency=1,documents=2,k1=k1)))
    e=2**-26;matrix=[[.5,e,-.5,e,.5,0,-.5,0],[e,0,0,-.5,.5,.5,-.5,e]]
    for same in (False,True):
        ps=[[1,passage('first',1)],[2,passage('first'if same else'second',10)]]
        cases.append(dict(id='review:dense:'+('evidence'if same else'cutoff'),kind='dense',input=dict(passages=ps,ids=[1,2],matrix=matrix,query=[1.]*8,view='identity',limit=1)))
    return cases

REVIEW_SCRIPT=SCRIPT.split('discovered=[];states=[]')[0]+r'''
value=dict(format='ken-retrieval-review-reference/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),numpy=np.__version__),blas=np.__config__.CONFIG['Build Dependencies']['blas'])
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n')
'''

def capture(reference:Reference,out:Path,repo:Path):
    expected=owners(repo)
    for name,sha in expected.items():require(identity(reference.root/name)['sha256']==sha,'original review owner changed')
    out.mkdir(parents=True,exist_ok=False);(out/'capture.py').write_text(REVIEW_SCRIPT)
    payload=dict(root=str(reference.root),cases=definitions(),result=str(out/'observations.json'))
    (out/'request.json').write_text(json.dumps(payload,ensure_ascii=True))
    proc=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'stdout.log').write_bytes(proc.stdout);(out/'stderr.log').write_bytes(proc.stderr)
    (out/'process-exit.json').write_text(json.dumps(dict(exit=proc.returncode)))
    require(proc.returncode==0,'actual original review process failed')
    value=load(out/'observations.json');value.update(owners=expected,execution={name:identity(out/name)for name in('capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json')})
    value['corpus_sha256']=digest(value['cases']);(out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n')
    return value

def verify_original(out:Path,repo:Path,system:str):
    value=load(out/'reference.json')
    require(value['format']=='ken-retrieval-review-reference/1'and value['owners']==owners(repo),'supplemental original ownership differs')
    require(value['runtime']==dict(system='Darwin'if system=='macos'else'Linux',machine='arm64'if system=='macos'else'aarch64',python='3.12.9',numpy='2.4.4'),'supplemental original platform differs')
    require((out/'capture.py').read_text()==REVIEW_SCRIPT and load(out/'process-exit.json')=={'exit':0},'supplemental original observer/exit differs')
    require(value['execution']=={name:identity(out/name)for name in('capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json')},'supplemental original process bytes differ')
    require(same_value(load(out/'request.json')['cases'],definitions()),'supplemental original inputs differ')
    require(all(same_value(value[k],v)for k,v in load(out/'observations.json').items())and digest(value['cases'])==value['corpus_sha256'],'supplemental original observations differ')
    require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==definitions(),'supplemental original inventory differs')
    return value

def run_native(repo:Path,binary:Path,reference:dict,out:Path):
    from .retrieval_validate import prepare_runtime
    sources=source_identity(repo)
    with NativeJsonCapture(binary,out,repo=repo,prefix='ken-retrieval-native-')as capture:
        prepare_runtime(capture)
        actual=capture.run(requests(reference['cases']))
    (out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n');(out/'BUILD.json').write_text(json.dumps(dict(format='ken-retrieval-build/1',sources=sources,native_sha256=identity(binary)['sha256']),indent=2)+'\n')
    require(not compare_observations(reference,actual),'supplemental native regression mismatch')
    return actual

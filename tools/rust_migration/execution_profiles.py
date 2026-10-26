"""Independent full original captures for declared x86 numerical execution profiles."""
from pathlib import Path
import argparse,ctypes,dataclasses,hashlib,json,os,platform,subprocess,sys
from .native_json import identity,load,same_value
from .reference import Reference,reference_env,verify_reference
from .context_reference import _CHILD,context_cases,TOLERANCES,snapshot_state,stderr_errors
from .numeric_alignment_reference import SCRIPT
from .numeric_reference import definitions
FP='5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038'
CORE_SHA='c450a686085f441803ef914fc7e68bd417452e34ba5573344dc3dd40c0c71896'
BLAS_SHA='05c9f9eb89ee68a4b9d673184fa91c99587e736392c0c2d49180a8aa5303d080'
FEATURES=['sse41','avx','avx2','fma','f16c','avx512f','avx512bw','avx512dq','avx512vl','avx512vnni','avx_vnni','avx_vnni_int8','amx_tile_hardware','amx_int8_hardware','hybrid']
ALIGNMENT_OBSERVER=SCRIPT.split('discovered=[];states=[]',1)[0]+r'''
import ctypes,hashlib
library=next((pathlib.Path(np.__file__).parent.parent/'numpy.libs').glob('libscipy_openblas64_*.so'))
blas=ctypes.CDLL(str(library));core=blas.scipy_openblas_get_corename64_;core.restype=ctypes.c_char_p
threads=blas.scipy_openblas_get_num_threads64_;threads.restype=ctypes.c_int
value=dict(format='ken-profile-alignment-original/1',family='alignment',cases=records,runtime=dict(python=platform.python_version(),numpy=np.__version__,system=platform.system(),machine=platform.machine()),blas=dict(core=core().decode(),threads=threads(),sha256=hashlib.sha256(library.read_bytes()).hexdigest()),source_sha256=hashlib.sha256((root/'src/ken/retrieval/alignment.py').read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n')
'''
def require(ok,message):
    if not ok:raise ValueError(message)
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=True,indent=2,allow_nan=False)+'\n')
def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def assert_fresh(out):
    if out.exists()or out.is_symlink():raise FileExistsError(out)
def capabilities(probe:Path):
    child=subprocess.run([str(probe.resolve())],capture_output=True,text=True,timeout=30,check=True)
    require(not child.stderr,'capability probe stderr');value=json.loads(child.stdout)
    return validate_capabilities(value)

def validate_capabilities(value):
    require(set(value)=={'format','target','features'}and value['format']=='ken-x86-capabilities/1'and value['target']=='linux-x86_64','capability target differs')
    require(set(value['features'])==set(FEATURES)and all(type(x)is bool for x in value['features'].values()),'capability mask differs');return value

def inputs(repo):return dict(context=context_cases(),alignment=definitions('alignment',repo))
def descriptors(caps,blas):
    validate_capabilities(caps)
    require(blas['sha256']==BLAS_SHA and blas['threads']==1 and type(blas['threads'])is int and isinstance(blas['core'],str)and blas['core'],'pinned one-thread BLAS required')
    return dict(context=dict(format='ken-context-profile/1',target='linux-x86_64',features=caps['features'],native_core_sha256=CORE_SHA,onnxruntime='1.25.1',tokenizers='0.22.2'),alignment=dict(format='ken-alignment-profile/1',target='linux-x86_64',numpy='2.4.4',**blas))

def verify_capture(out:Path,repo:Path):
    try:
        record=load(out/'CAPTURE.json');fixed=inputs(repo);require(record['format']=='ken-original-execution-profile/1'and record['reference_fingerprint']==FP,'capture identity differs')
        require(record['script_sha256']==dict(context=hashlib.sha256(_CHILD.encode()).hexdigest(),alignment=hashlib.sha256(ALIGNMENT_OBSERVER.encode()).hexdigest()),'original observer source differs')
        require(same_value(load(out/'inputs.json'),fixed),'full original input corpus differs')
        require(record['inputs_sha256']==fingerprint(fixed),'input hash differs')
        for name,pin in record['files'].items():require(identity(out/name)==pin,'original raw transport differs: '+name)
        require(set(record['files'])=={'context.stdout','context.stderr','context-inputs.json','context.json','alignment.stdout','alignment.stderr','alignment-inputs.json','alignment.json','alignment-observer.py'},'original raw inventory differs')
        context=load(out/'context.json');alignment=load(out/'alignment.json')
        ctx_input=load(out/'context-inputs.json');align_input=load(out/'alignment-inputs.json')
        require(set(ctx_input)=={'reference','snapshot','definition','cases'}and same_value(ctx_input['cases'],fixed['context']),'original context request contains answers or differs')
        require(set(align_input)=={'root','cases','result'}and same_value(align_input['cases'],fixed['alignment']),'original alignment request contains answers or differs')
        require(same_value(ctx_input['definition'],load(repo/'src/ken/embedder/data/code-context-int8.json')),'original model definition differs')
        raw_context=load(out/'context.stdout');raw_context['oracle']['stderr']=(out/'context.stderr').read_text()
        artifacts={name:{key:row[key]for key in('bytes','sha256')}for name,row in ctx_input['definition']['artifacts'].items()}
        raw_context.update(format='ken-context-oracle/1',definition=ctx_input['definition'],artifacts=artifacts,cases=fixed['context'],tolerances=TOLERANCES,reference_fingerprint=FP)
        require(same_value(context,raw_context),'normalized context changed original observations')
        require(alignment['source_sha256']=='4fd861b5f2d9fa792fe47ab9900af926acb697245e702687df26ab63a1aaa99b','original alignment source identity differs')

        require(context['format']=='ken-context-oracle/1'and context['reference_fingerprint']==FP and context['cases']==fixed['context']and context['tolerances']==TOLERANCES,'context contract differs')
        require(context['dimension']==768 and len(context['results'])==20 and [r['id']for r in context['results']]==[c['id']for c in fixed['context']],'context observations incomplete')
        require(all(len(r['calls'])==len(c['calls'])for r,c in zip(context['results'],fixed['context'],strict=True)),'context histories incomplete')
        require(context['oracle']['runtime']==dict(numpy='2.4.4',onnxruntime='1.25.1',tokenizers='0.22.2',onnx='1.20.1')and context['oracle']['frozen_import']is True,'original context runtime differs')
        require(alignment['format']=='ken-profile-alignment-original/1'and alignment['runtime']==dict(python='3.12.9',numpy='2.4.4',system='Linux',machine='x86_64'),'original alignment runtime differs')
        require([{k:r[k]for k in('id','kind','input')}for r in alignment['cases']]==fixed['alignment']and all(('result'in r)^('error'in r)for r in alignment['cases']),'alignment observations incomplete')
        require(record['exits']==dict(context=0,alignment=0),'original execution failed')
        require(same_value(record['descriptors'],descriptors(record['capabilities'],alignment['blas'])),'execution descriptors differ')
        require(record['ids']=={kind:fingerprint(value)for kind,value in record['descriptors'].items()},'execution profile ids differ')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def capture(reference:Reference,snapshot:Path,probe:Path,out:Path,repo:Path):
    assert_fresh(out);require(not verify_reference(reference.root,reference.manifest_path)and reference.fingerprint==FP,'frozen1066 source drift')
    reference=dataclasses.replace(reference,python=Path(sys.executable).absolute());before=capabilities(probe);probe_before=identity(probe);out.mkdir(parents=True)
    fixed=inputs(repo);save(out/'inputs.json',fixed);definition=load(reference.root/'src/ken/embedder/data/code-context-int8.json');artifacts=snapshot_state(snapshot,definition)
    env=reference_env(reference,out/'environment');env['OPENBLAS_NUM_THREADS']='1';env.pop('OPENBLAS_CORETYPE',None);env.update(TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1')
    context_input=dict(reference=str(reference.root),snapshot=str(snapshot.resolve()),definition=definition,cases=fixed['context']);save(out/'context-inputs.json',context_input)
    context=subprocess.run([str(reference.python),'-B','-c',_CHILD],input=json.dumps(context_input),cwd=reference.root,env=env,capture_output=True,text=True,timeout=600)
    (out/'context.stdout').write_text(context.stdout);(out/'context.stderr').write_text(context.stderr);require(context.returncode==0,'original context process failed')
    value=json.loads(context.stdout);require(not stderr_errors(context.stderr,value['platform']),'original context stderr differs')
    value['oracle']['stderr']=context.stderr;value.update(format='ken-context-oracle/1',definition=definition,artifacts=artifacts,cases=fixed['context'],tolerances=TOLERANCES,reference_fingerprint=FP);save(out/'context.json',value)
    (out/'alignment-observer.py').write_text(ALIGNMENT_OBSERVER);request=dict(root=str(reference.root),cases=fixed['alignment'],result=str((out/'alignment.json').resolve()));save(out/'alignment-inputs.json',request)
    alignment=subprocess.run([str(reference.python),'-B',str((out/'alignment-observer.py').resolve()),str((out/'alignment-inputs.json').resolve())],cwd=reference.root,env=env,capture_output=True,timeout=300)
    (out/'alignment.stdout').write_bytes(alignment.stdout);(out/'alignment.stderr').write_bytes(alignment.stderr);require(alignment.returncode==0,'original alignment process failed')
    require(probe_before==identity(probe)and before==capabilities(probe)and not verify_reference(reference.root,reference.manifest_path)and artifacts==snapshot_state(snapshot,definition),'profile/source/artifact changed during capture')
    ds=descriptors(before,load(out/'alignment.json')['blas'])
    names=['context.stdout','context.stderr','context-inputs.json','context.json','alignment.stdout','alignment.stderr','alignment-inputs.json','alignment.json','alignment-observer.py']
    record=dict(format='ken-original-execution-profile/1',reference_fingerprint=FP,inputs_sha256=fingerprint(fixed),script_sha256=dict(context=hashlib.sha256(_CHILD.encode()).hexdigest(),alignment=hashlib.sha256(ALIGNMENT_OBSERVER.encode()).hexdigest()),capabilities=before,descriptors=ds,ids={kind:fingerprint(value)for kind,value in ds.items()},exits=dict(context=context.returncode,alignment=alignment.returncode),files={name:identity(out/name)for name in names},probe=identity(probe),cpuinfo=Path('/proc/cpuinfo').read_text(),candidate=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip())
    save(out/'CAPTURE.json',record);errors=verify_capture(out,repo);require(not errors,str(errors));return record

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['capture','verify']);p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--reference',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--probe',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.operation=='capture':print(json.dumps(capture(Reference.load(a.reference),a.snapshot,a.probe,a.out.resolve(),a.repo.resolve())['ids']))
    else:require(not verify_capture(a.out,a.repo),str(verify_capture(a.out,a.repo)));print('PASS original full-corpus execution profile')
if __name__=='__main__':main()

"""Source-bound complete PieceSearch composition over controlled leaves and native Ettin."""
from pathlib import Path
import gzip,json,math,os,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .python_witnesses_host import grammar_bytes
from .symbol_ranking_host import verify_host as verify_operations
from .piece_search_reference import FIXTURE,validate_reference
from .ettin_host import generated_files,REGISTRATION,RUNTIME
from .ettin_reference import source_state
from .ettin_compare import _score_errors,TOLERANCES
from .context_compare import core_for_platform
from .retrieval_validate import prepare_runtime,runtime_files,runtime_manifest
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors
PREFIX='ken-piece-search-'
REFERENCE_ID={'bytes': 84765, 'sha256': 'd9c9a401154054153b555b347486a84cd81d94a4eebac25c23864e4a850efcfd'}
TEST_FILES=['tests/rust_migration/test_piece_search_reference.py','tests/rust_migration/test_piece_search_host.py']
PYTHON_ROOTS=29
COMMANDS={'piece-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','piece_search_probe']}
def reference(repo):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved piece search original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));require(not validate_reference(value),'original piece search contract differs');return value

def request(repo,original,root):
    definition=load(repo/REGISTRATION)
    return dict(grammar_manifest=str(root/'grammar-manifest'),registration=definition,source=str(root/'source'/definition['source']['revision']),cache=str(root/'prepared'),runtime_registration=load(repo/RUNTIME),library=str(root/'runtime-core'),cases=[{key:row[key]for key in('id','input')}for row in original['cases']])

def compare_response(wanted,actual,calls,path='response'):
    if isinstance(wanted,dict):
        require(isinstance(actual,dict)and set(wanted)==set(actual),path+': response fields differ')
        for key,w in wanted.items():
            a=actual[key];where=path+'.'+key
            if key in('neural_score','code_score','mean_score'):
                require(type(a)in(int,float)and math.isfinite(a)and not(w==0 and a!=0)and abs(w-a)<=TOLERANCES['atol']+TOLERANCES['rtol']*abs(w),where+': score differs')
            elif key in('reranker','additional_reranker'):
                score_calls=[c for c in calls if c['op']=='score'];call=score_calls[0 if key=='reranker'else -1];count=len(call['texts'])
                errors=_score_errors(dict(scores=[0.]*count,details=w),dict(scores=[0.]*count,details=a),call,where)
                require(not errors,str(errors))
            else:compare_response(w,a,calls,where)
    elif isinstance(wanted,list):
        require(isinstance(actual,list)and len(wanted)==len(actual),path+': response count differs')
        for i,(w,a)in enumerate(zip(wanted,actual,strict=True)):compare_response(w,a,calls,path+f'[{i}]')
    else:require(same_value(wanted,actual),path+': response value differs')

def compare(original,actual,core):
    try:
        require(set(actual)=={'format','runtime','cases'}and actual['format']=='ken-piece-search-native/1','native piece search format differs')
        require(same_value(actual['runtime'],core),'actual piece runtime differs')
        require([r['id']for r in actual['cases']]==[r['id']for r in original['cases']],'native cases differ')
        for frame,row in zip(original['cases'],actual['cases'],strict=True):
            require(set(row)=={'id','observations'},'foreign native row fields')
            require(isinstance(row['observations'],list)and len(row['observations'])==2,'cold/warm observations required')
            for a,b in zip(frame['observations'],row['observations'],strict=True):
                require(set(a)==set(b)and same_value(a['calls'],b['calls'])and same_value(a['cache'],b['cache']),frame['id']+': source/cache/calls differ')
                if frame['input']['model']['kind']=='controlled':require(same_value(a,b),frame['id']+': controlled composition differs')
                else:compare_response(a['result'],b['result'],a['calls'],frame['id'])
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration,OverflowError)as error:return[str(error)]

def verify_capture(packet,repo):
    try:
        require(not (errors:=verify_operations(packet,repo)),'complete SymbolRanker parent: '+str(errors));original=reference(repo);out=packet/'piece-search';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'piece search requires Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'original transport differs')
        require((out/'grammar-manifest').read_bytes()==grammar_bytes(repo),'piece grammar differs')
        require(not (errors:=verify_native_json(capture,PREFIX,generated_files=generated_files(original))),str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd']);require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'piece search ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'piece execution host differs')
        binary=out/'bin/piece_search_probe';check_native_architecture(binary,('linux','x86_64'));wanted=request(repo,original,root)
        require(same_value(load(capture/'inputs.json'),wanted),'piece request contains answers or foreign inputs')
        core=core_for_platform(wanted['runtime_registration'],'Linux','x86_64');resources={'native-probe':identity(binary),'runtime-core':{k:core[k]for k in('bytes','sha256')},'grammar-manifest':identity(out/'grammar-manifest')}
        resources.update({'dense-blas/'+name:record for name,record in runtime_files(repo,'x86_64').items()})
        manifest=runtime_manifest(repo,'x86_64')
        require(str(root/'dense-blas'/manifest['library'])in(capture/'stderr.log').read_text(),'isolated pinned piece BLAS not loaded')
        resources.update({'source/'+wanted['registration']['source']['revision']+'/'+name:row for name,row in original['definition']['source']['artifacts'].items()})
        require(execution['native_sha256']==identity(binary)['sha256']and same_value(execution['owned_before'],resources),'piece native resources differ')
        require(not (errors:=compare(original,load(capture/'stdout.json'),core)),str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet,repo):
    try:
        require(not (errors:=verify_capture(packet,repo)),str(errors));out=packet/'piece-search'
        return command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def capture_native(repo,original,out,binary,library,source):
    definition=load(repo/REGISTRATION)
    require(source_state(source,definition['source'])==definition['source']['artifacts'],'piece source differs')
    (out/'grammar-manifest').write_bytes(grammar_bytes(repo))
    with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,generated_files=generated_files(original))as capture:
        inputs=request(repo,original,capture.root)
        prepare_runtime(capture)
        shutil.copyfile(out/'grammar-manifest',inputs['grammar_manifest']);shutil.copyfile(library,inputs['library'])
        for name in definition['source']['artifacts']:
            target=Path(inputs['source'])/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
        capture.run(inputs)

def run_host(repo,packet):
    original=reference(repo);out=packet/'piece-search';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target');run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/piece_search_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/piece_search_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz');(out/'grammar-manifest').write_bytes(grammar_bytes(repo))
        definition=load(repo/REGISTRATION);source=Path(os.environ['KEN_ETTIN_SOURCE']);require(source_state(source,definition['source'])==definition['source']['artifacts'],'piece source differs')
        library=Path(load(packet/'SDK.json')['prepared']['onnx_library']);os.environ['KEN_ORT_LIBRARY']=str(library)
        capture_native(repo,original,out,binary,library,source)
        require(not (errors:=verify_capture(packet,repo)),str(errors));os.environ['KEN_PIECE_SEARCH_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        require(not (errors:=verify_host(packet,repo)),str(errors))
    finally:os.environ.clear();os.environ.update(environment)

"""Source-bound BestSearch and contextual preparation over explicit x86 resources."""
from pathlib import Path
import gzip,json,os,shutil,re
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .python_witnesses_host import grammar_bytes
from .piece_search_host import verify_host as verify_pieces,compare_response
from .best_search_reference import FIXTURE,validate_reference
from .context_preparation_reference import FIXTURE as PREPARATION_FIXTURE,validate_reference as validate_preparation
from .context_compare import core_for_platform
from .retrieval_validate import prepare_runtime,runtime_files,runtime_manifest
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors,run_lint_gates,lint_gate_errors
from .integration_validate import rust_gate_errors
PREFIX='ken-best-search-'
PREPARATION_PREFIX='ken-source-preparation-'
REFERENCE_ID={'bytes':37286,'sha256':'73ec863b28c5e9473c8e8826dce943a5c44e13d30dac51d2a47b87d217402aeb'}
PREPARATION_ID={'bytes':13811,'sha256':'8daeb0d83b3ef2c34df17357e13f3740484b3bfa7e895218f51505df1cf62710'}
TEST_FILES=['tests/rust_migration/test_context_preparation_reference.py','tests/rust_migration/test_best_search_reference.py','tests/rust_migration/test_best_search_host.py']
PYTHON_ROOTS=49
NATIVE_TEST=['cargo','test','--locked','--offline','-p','ken-core','-p','ken-retrieval','-p','ken-index','-p','ken-syntax','-p','ken-search','--all-targets']
STATIC_TEST=['cargo','test','--locked','--offline','-p','ken-models','--lib','registered_feature_identity']
IDENTITY_TEST=['cargo','test','--locked','--offline','-p','ken-models','--test','profile_identity']
COMMANDS={'best-list':[*NATIVE_TEST,'--','--list'],'best-tests':[*NATIVE_TEST,'--no-fail-fast'],'static-list':[*STATIC_TEST,'--','--list'],'static-tests':[*STATIC_TEST,'--no-fail-fast'],'identity-list':[*IDENTITY_TEST,'--','--list'],'identity-tests':[*IDENTITY_TEST,'--no-fail-fast'],'best-build':['cargo','build','--locked','--offline','-p','ken-search','--example','best_search_probe','-p','ken-retrieval','--example','context_preparation_probe']}
LINT={'fmt':['cargo','fmt','--all','--check'],'clippy':['cargo','clippy','--locked','--offline','-p','ken-search','-p','ken-index','-p','ken-retrieval','-p','ken-syntax','-p','ken-models','--all-targets','--','-D','warnings']}
RANKING='crates/ken-retrieval/resources/ranking'
RUNTIME='crates/ken-models/resources/onnx-runtime-libraries.json'
def originals(repo):
    result=[]
    for name,wanted,validate in [(FIXTURE,REFERENCE_ID,validate_reference),(PREPARATION_FIXTURE,PREPARATION_ID,validate_preparation)]:
        require(identity(repo/name)==wanted,'preserved original differs: '+name)
        value=json.loads(gzip.decompress((repo/name).read_bytes()));require(not(errors:=validate(value)),str(errors));result.append(value)
    return tuple(result)

def source_definitions(original):
    return {name:(original['registrations'][name]['source']if name=='ettin'else original['registrations'][name])for name in('potion','context','ettin')}

def request(repo,original,root):
    return dict(grammar_manifest=str(root/'grammar-manifest'),ranking_directory=str(root/'ranking'),runtime_registration=load(repo/RUNTIME),library=str(root/'runtime-core'),cache_parent=str(root/'private'),sources={definition['model_id']:str(root/'sources'/name/definition['revision'])for name,definition in source_definitions(original).items()},cases=[{key:row[key]for key in('id','input')}for row in original['cases']])

def preparation_request(original):return dict(cases=[{key:row[key]for key in('id','input')}for row in original['cases']])

def compare(original,actual,core):
    try:
        require(set(actual)=={'format','runtime','cases'}and actual['format']=='ken-best-search-native/1','native best format differs')
        require(same_value(actual['runtime'],core),'actual runtime differs')
        require([r['id']for r in actual['cases']]==[r['id']for r in original['cases']],'native endpoint inventory differs')
        for frame,row in zip(original['cases'],actual['cases'],strict=True):
            require(set(row)=={'id','events'},'foreign endpoint row fields')
            require(isinstance(row['events'],list)and len(row['events'])==len(frame['events']),frame['id']+': endpoint history differs')
            for wanted,got in zip(frame['events'],row['events'],strict=True):
                require(set(wanted)==set(got)and same_value(wanted['calls'],got['calls'])and same_value(wanted['state'],got['state']),frame['id']+': source/calls/generation/cache differs')
                if frame['input']['models']['kind']=='controlled':require(same_value(wanted,got),frame['id']+': controlled endpoint differs')
                else:
                    calls=[c|dict(op='score')for c in wanted['calls']if c['op']=='neural_score']
                    compare_response(wanted['result'],got['result'],calls,frame['id'])
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration,OverflowError)as error:return[str(error)]

def compare_preparation(original,actual):
    try:
        require(set(actual)=={'format','cases'}and actual['format']=='ken-context-preparation-native/1','native preparation format differs')
        require(same_value(actual['cases'],[{key:row[key]for key in('id','events')}for row in original['cases']]),'source cache/artifacts/mapping observations differ')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def best_resources(repo,original,root,binary,core,grammar):
    resources={'native-probe':identity(binary),'runtime-core':{k:core[k]for k in('bytes','sha256')},'grammar-manifest':identity(grammar)}
    resources.update({'dense-blas/'+n:r for n,r in runtime_files(repo,'x86_64').items()})
    resources.update({'ranking/'+p.name:identity(p)for p in sorted((repo/RANKING).iterdir())if p.is_file()})
    resources.update({'sources/'+name+'/'+definition['revision']+'/'+n:r for name,definition in source_definitions(original).items()for n,r in definition['artifacts'].items()})
    return resources

def verify_endpoints(out,repo):
    """Check new captures for preflight; complete acceptance also requires parents."""
    try:
        best,prep=originals(repo)
        for name,record in [('ORIGINAL.json.gz',REFERENCE_ID),('PREPARATION-ORIGINAL.json.gz',PREPARATION_ID)]:require(identity(out/name)==record,'original transport differs')
        require((out/'grammar-manifest').read_bytes()==grammar_bytes(repo),'best grammar differs')
        for name,prefix in [('native',PREFIX),('preparation',PREPARATION_PREFIX)]:
            capture=out/name;require(not(errors:=verify_native_json(capture,prefix)),str(errors));execution=load(capture/'execution.json');root=Path(execution['cwd'])
            require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'native capture ran inside checkout')
            require((execution['system'],execution['machine'])==('linux','x86_64'),'execution host differs')
            binary=out/'bin'/('best_search_probe'if name=='native'else'context_preparation_probe');check_native_architecture(binary,('linux','x86_64'))
            expected=request(repo,best,root)if name=='native'else preparation_request(prep)
            require(same_value(load(capture/'inputs.json'),expected),'native request contains answers or foreign inputs')
            core=core_for_platform(load(repo/RUNTIME),'Linux','x86_64')
            resources=best_resources(repo,best,root,binary,core,out/'grammar-manifest')if name=='native'else{'native-probe':identity(binary)}|{'dense-blas/'+n:r for n,r in runtime_files(repo,'x86_64').items()}
            require(execution['native_sha256']==identity(binary)['sha256']and same_value(execution['owned_before'],resources),'immutable resource closure differs')
            manifest=runtime_manifest(repo,'x86_64');require(str(root/'dense-blas'/manifest['library'])in(capture/'stderr.log').read_text(),'isolated pinned BLAS was not loaded')
            errors=compare(best,load(capture/'stdout.json'),core)if name=='native'else compare_preparation(prep,load(capture/'stdout.json'))
            require(not errors,str(errors))
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError)as error:return[str(error)]

def verify_capture(packet,repo):
    try:
        require(not(errors:=verify_pieces(packet,repo)),'complete PieceSearch parent: '+str(errors))
        host=load(packet/'HOST.json');require((host['os'],host['arch'])==('linux','x86_64'),'BestSearch requires Linux x86_64')
        return verify_endpoints(packet/'best-search',repo)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet,repo):
    try:
        require(not(errors:=verify_capture(packet,repo)),str(errors));out=packet/'best-search'
        require(not(errors:=command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')),str(errors))
        for prefix,count in [('best',216),('static',1),('identity',5)]:
            listed=(out/f'gates/{prefix}-list.log').read_text();output=(out/f'gates/{prefix}-tests.log').read_text()
            require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==count,'all native roots required: '+prefix)
        return lint_gate_errors(out/'gates',LINT)or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def capture_native(repo,best,prep,out):
    out.mkdir(parents=True,exist_ok=True);(out/'grammar-manifest').write_bytes(grammar_bytes(repo))
    (out/'bin').mkdir(exist_ok=True)
    for name in('best_search_probe','context_preparation_probe'):shutil.copyfile(repo/'target/debug/examples'/name,out/'bin'/name)
    shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz');shutil.copyfile(repo/PREPARATION_FIXTURE,out/'PREPARATION-ORIGINAL.json.gz')
    with NativeJsonCapture(repo/'target/debug/examples/context_preparation_probe',out/'preparation',repo=repo,prefix=PREPARATION_PREFIX)as capture:
        prepare_runtime(capture);capture.run(preparation_request(prep))
    with NativeJsonCapture(repo/'target/debug/examples/best_search_probe',out/'native',repo=repo,prefix=PREFIX)as capture:
        inputs=request(repo,best,capture.root);prepare_runtime(capture)
        shutil.copyfile(out/'grammar-manifest',inputs['grammar_manifest']);shutil.copytree(repo/RANKING,inputs['ranking_directory']);shutil.copyfile(os.environ['KEN_ORT_LIBRARY'],inputs['library']);Path(inputs['cache_parent']).mkdir()
        for name,definition in source_definitions(best).items():
            source=Path(os.environ[{'potion':'KEN_POTION_SOURCE','context':'KEN_CONTEXT_SNAPSHOT','ettin':'KEN_ETTIN_SOURCE'}[name]])
            for filename,record in definition['artifacts'].items():
                require(identity(source/filename)==record,'registered source differs: '+name+'/'+filename)
                path=Path(inputs['sources'][definition['model_id']])/filename;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/filename,path)
        capture.run(inputs)

def run_host(repo,packet):
    best,prep=originals(repo);out=packet/'best-search';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target');run_command_gates(out/'gates',COMMANDS,record_name='RUST.json');run_lint_gates(out/'gates',LINT)
        (out/'bin').mkdir()
        for name in('best_search_probe','context_preparation_probe'):shutil.copyfile(repo/'target/debug/examples'/name,out/'bin'/name)
        shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz');shutil.copyfile(repo/PREPARATION_FIXTURE,out/'PREPARATION-ORIGINAL.json.gz')
        capture_native(repo,best,prep,out);require(not(errors:=verify_capture(packet,repo)),str(errors));os.environ['KEN_BEST_SEARCH_PACKET']=str(packet);run_python_scope(out,TEST_FILES);require(not(errors:=verify_host(packet,repo)),str(errors))
    finally:os.environ.clear();os.environ.update(environment)

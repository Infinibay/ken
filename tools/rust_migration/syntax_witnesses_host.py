"""Input-only native CST witnesses on immutable source catalogs and builtin grammars."""
from pathlib import Path
import gzip,json,os,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .symbol_preferences_host import verify_host as verify_preferences
from .syntax_witnesses_reference import FIXTURE,validate_reference
from .grammar_prepare import _manifest
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors
PREFIX='ken-syntax-witnesses-'
REFERENCE_ID=dict(bytes=12758,sha256='3f1f851be636cce48403df41fda0d88a49f28b6159df7e924d4a04899c64d805')
TEST_FILES=['tests/rust_migration/test_syntax_witnesses_reference.py','tests/rust_migration/test_syntax_witnesses_host.py','tests/rust_migration/test_syntax_profile_sequence.py']
PYTHON_ROOTS=25
COMMANDS={'syntax-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','syntax_witnesses_probe']}
def reference(repo:Path):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved syntax original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));errors=validate_reference(value);require(not errors,str(errors));return value

def grammar_bytes(repo:Path):
    return (json.dumps(_manifest(load(repo/'crates/ken-syntax/grammars.lock.json'),'linux-x86_64'),indent=2)+'\n').encode()

def request(original:dict,root:Path):
    return dict(grammar_manifest=str(root/'grammar-manifest'),cases=[{k:row[k]for k in('id','input')}for row in original['cases']])

def compare(original:dict,actual:dict):
    expected=dict(format='ken-syntax-witnesses-native/1',cases=[dict(id=row['id'],result=row['result'])for row in original['cases']])
    return []if same_value(actual,expected)else['native CST operation witnesses differ']

def verify_capture(packet:Path,repo:Path):
    try:
        errors=verify_preferences(packet,repo);require(not errors,'complete preference parent: '+str(errors))
        original=reference(repo);out=packet/'syntax-witnesses';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'syntax witnesses require Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'syntax original transport differs')
        require((out/'grammar-manifest').read_bytes()==grammar_bytes(repo),'syntax grammar manifest differs')
        errors=verify_native_json(capture,PREFIX);require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd'])
        require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'syntax witnesses ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'syntax execution host differs')
        binary=out/'bin/syntax_witnesses_probe';check_native_architecture(binary,('linux','x86_64'));binary_id=identity(binary)
        resources={'native-probe':binary_id,'grammar-manifest':identity(out/'grammar-manifest')}
        require(execution['native_sha256']==binary_id['sha256']and same_value(execution['owned_before'],resources),'syntax native resources differ')
        require(same_value(load(capture/'inputs.json'),request(original,root)),'syntax request contains answers or foreign inputs')
        errors=compare(original,load(capture/'stdout.json'));require(not errors,str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet:Path,repo:Path):
    try:
        errors=verify_capture(packet,repo);require(not errors,str(errors));out=packet/'syntax-witnesses'
        return command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def run_host(repo:Path,packet:Path):
    original=reference(repo);out=packet/'syntax-witnesses';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target')
        run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/syntax_witnesses_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/syntax_witnesses_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz')
        (out/'grammar-manifest').write_bytes(grammar_bytes(repo))
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX)as capture:
            shutil.copyfile(out/'grammar-manifest',capture.root/'grammar-manifest');capture.run(request(original,capture.root))
        errors=verify_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_SYNTAX_WITNESSES_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        errors=verify_host(packet,repo);require(not errors,str(errors))
    finally:os.environ.clear();os.environ.update(environment)

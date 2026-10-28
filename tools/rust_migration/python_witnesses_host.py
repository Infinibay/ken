"""Input-only native Python AST and routed CST witnesses on immutable source catalogs and builtin grammars."""
from pathlib import Path
import gzip,json,os,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .syntax_witnesses_host import verify_host as verify_syntax
from .python_witnesses_reference import FIXTURE,validate_reference
from .python_witnesses_compat import FIXTURE_COMPAT
from .grammar_prepare import _manifest
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors
PREFIX='ken-python-witnesses-'
REFERENCE_ID={'bytes': 16172, 'sha256': 'b9eda1f055e4f32794e70e422733fc907a2fe99b055a8e827f6e1d2d2e570782'}
COMPAT_ID={'bytes': 3215, 'sha256': 'ddafb8d84b0454390564facc8cf9e4a35b4468393928fbc906a2902ae4a2d57f'}
TEST_FILES=['tests/rust_migration/test_python_witnesses_reference.py','tests/rust_migration/test_python_witnesses_host.py','tests/rust_migration/test_python_witnesses_archive.py']
PYTHON_ROOTS=26
COMMANDS={'python-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','python_witnesses_probe']}
def reference(repo:Path):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved Python original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));errors=validate_reference(value);require(not errors,str(errors))
    require(identity(repo/FIXTURE_COMPAT)==COMPAT_ID,'preserved compatibility original differs')
    compat=json.loads(gzip.decompress((repo/FIXTURE_COMPAT).read_bytes()));require(not validate_reference(compat),'compatibility contract differs')
    return dict(cases=value['cases']+compat['cases'])

def grammar_bytes(repo:Path):
    return (json.dumps(_manifest(load(repo/'crates/ken-syntax/grammars.lock.json'),'linux-x86_64'),indent=2)+'\n').encode()

def request(original:dict,root:Path):
    return dict(grammar_manifest=str(root/'grammar-manifest'),cases=[{k:row[k]for k in('id','input')}for row in original['cases']])

def compare(original:dict,actual:dict):
    expected=dict(format='ken-python-witnesses-native/1',cases=[dict(id=row['id'],result=row['result'])for row in original['cases']])
    return []if same_value(actual,expected)else['native Python operation witnesses differ']

def verify_capture(packet:Path,repo:Path):
    try:
        errors=verify_syntax(packet,repo);require(not errors,'complete CST parent: '+str(errors))
        original=reference(repo);out=packet/'python-witnesses';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'Python witnesses require Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'Python original transport differs')
        require(identity(out/'COMPAT.json.gz')==COMPAT_ID,'compatibility original transport differs')
        require((out/'grammar-manifest').read_bytes()==grammar_bytes(repo),'Python grammar manifest differs')
        errors=verify_native_json(capture,PREFIX);require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd'])
        require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'Python witnesses ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'Python execution host differs')
        binary=out/'bin/python_witnesses_probe';check_native_architecture(binary,('linux','x86_64'));binary_id=identity(binary)
        resources={'native-probe':binary_id,'grammar-manifest':identity(out/'grammar-manifest')}
        require(execution['native_sha256']==binary_id['sha256']and same_value(execution['owned_before'],resources),'Python native resources differ')
        require(same_value(load(capture/'inputs.json'),request(original,root)),'Python request contains answers or foreign inputs')
        errors=compare(original,load(capture/'stdout.json'));require(not errors,str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet:Path,repo:Path):
    try:
        errors=verify_capture(packet,repo);require(not errors,str(errors));out=packet/'python-witnesses'
        return command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def run_host(repo:Path,packet:Path):
    original=reference(repo);out=packet/'python-witnesses';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target')
        run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/python_witnesses_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/python_witnesses_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz');shutil.copyfile(repo/FIXTURE_COMPAT,out/'COMPAT.json.gz')
        (out/'grammar-manifest').write_bytes(grammar_bytes(repo))
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX)as capture:
            shutil.copyfile(out/'grammar-manifest',capture.root/'grammar-manifest');capture.run(request(original,capture.root))
        errors=verify_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_PYTHON_WITNESSES_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        errors=verify_host(packet,repo);require(not errors,str(errors))
    finally:os.environ.clear();os.environ.update(environment)

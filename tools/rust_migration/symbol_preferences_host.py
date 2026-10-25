"""Authenticated input-only execution of the explicit symbol preference policy."""
from pathlib import Path
import gzip,json,os,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .symbol_views_host import verify_host as verify_views
from .symbol_preferences_reference import FIXTURE,validate_reference
from . import symbol_preferences_whitespace as whitespace
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors
PREFIX='ken-symbol-preferences-'
REFERENCE_ID=dict(bytes=6670,sha256='dfa4e7b78aabd72e573435aeb0564d219ee18cf48c664218abc83fd472351e73')
TEST_FILES=['tests/rust_migration/test_symbol_preferences_reference.py','tests/rust_migration/test_symbol_preferences_host.py','tests/rust_migration/test_symbol_profile_sequence.py']
PYTHON_ROOTS=24
COMMANDS={'preferences-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','symbol_preferences_probe']}
def reference(repo:Path):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved preference original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));errors=validate_reference(value);require(not errors,str(errors))
    require(identity(repo/whitespace.FIXTURE)==dict(bytes=1116,sha256='7ab32bc98cbc5b51d1740391b44e354b8a792de4d2dec2e4fc734ed335d61165'),'whitespace original differs')
    extension=json.loads(gzip.decompress((repo/whitespace.FIXTURE).read_bytes()));errors=whitespace.validate(extension);require(not errors,str(errors))
    return value|dict(whitespace=extension)

def request(original:dict):
    return dict(cases=[{k:row[k]for k in('id','kind','input')}for row in original['cases']+original['whitespace']['cases']],catalogs=[row['input']for row in original['catalogs']])

def compare(original:dict,actual:dict):
    expected=dict(format='ken-symbol-preferences-native/1',cases=[dict(id=row['id'],result=row['result'])for row in original['cases']+original['whitespace']['cases']],catalogs=[row['result']for row in original['catalogs']])
    return []if same_value(actual,expected)else['native explicit symbol preferences differ']

def verify_capture(packet:Path,repo:Path):
    try:
        errors=verify_views(packet,repo);require(not errors,'complete symbol-view parent: '+str(errors))
        original=reference(repo);out=packet/'symbol-preferences';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'preferences require Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'preference original transport differs')
        errors=verify_native_json(capture,PREFIX);require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd'])
        require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'preferences ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'preference execution host differs')
        binary=out/'bin/symbol_preferences_probe';check_native_architecture(binary,('linux','x86_64'));binary_id=identity(binary)
        require(execution['native_sha256']==binary_id['sha256']and execution['owned_before']=={'native-probe':binary_id},'preference native resources differ')
        require(same_value(load(capture/'inputs.json'),request(original)),'preference request contains answers or foreign inputs')
        errors=compare(original,load(capture/'stdout.json'));require(not errors,str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet:Path,repo:Path):
    try:
        errors=verify_capture(packet,repo);require(not errors,str(errors));out=packet/'symbol-preferences'
        return command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def run_host(repo:Path,packet:Path):
    original=reference(repo);out=packet/'symbol-preferences';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target')
        run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/symbol_preferences_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/symbol_preferences_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz')
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX)as capture:capture.run(request(original))
        errors=verify_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_SYMBOL_PREFERENCES_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        errors=verify_host(packet,repo);require(not errors,str(errors))
    finally:os.environ.clear();os.environ.update(environment)

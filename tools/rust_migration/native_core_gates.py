"""Complete command discovery/execution contracts for native CPU runtime cores."""
from pathlib import Path
import re
from .command_gates import command_gate_errors,lint_gate_errors
from .integration_validate import rust_gate_errors
from .native_json import load
from .receipts import junit_states
ROOT_TEST=['cargo','test','--locked','--offline','-p','ken-models','--test','native_onnx','--example','native_core_probe','--example','native_isolation_probe']
TORCH_TEST=['cargo','test','--locked','--offline','--manifest-path','native/ken-torch-backend/Cargo.toml']
ROOT_COMMANDS={'native-list':[*ROOT_TEST,'--','--list'],'native-tests':[*ROOT_TEST,'--no-fail-fast'],'probe-build':['cargo','build','--locked','--offline','-p','ken-models','--example','native_core_probe','--example','model_integration_probe','--example','native_isolation_probe']}
TORCH_COMMANDS={'torch-list':[*TORCH_TEST,'--','--list'],'torch-tests':[*TORCH_TEST,'--no-fail-fast'],'torch-build':['cargo','build','--locked','--offline','--manifest-path','native/ken-torch-backend/Cargo.toml']}
LINT_COMMANDS={'fmt':['cargo','fmt','--all','--check'],'clippy':['cargo','clippy','--locked','--offline','-p','ken-models','--all-targets','--','-D','warnings']}
TORCH_LINT={'fmt':['cargo','fmt','--manifest-path','native/ken-torch-backend/Cargo.toml','--check'],'clippy':['cargo','clippy','--locked','--offline','--manifest-path','native/ken-torch-backend/Cargo.toml','--all-targets','--','-D','warnings']}

def test_files(repo:Path):
    files=sorted(str(path.relative_to(repo))for path in(repo/'tests/rust_migration').glob('test_*.py')if any(path.name.startswith('test_'+prefix+'_')for prefix in('context','ettin','fastembed','transformer','integration')))
    return files+['tests/rust_migration/test_native_platform.py','tests/rust_migration/test_native_core_prepare.py','tests/rust_migration/test_native_core_evidence.py']

PYTHON_ROOTS=364

def native_test_roots(system:str):
    if system not in('linux','macos'):raise ValueError('unknown native core gate platform')
    return{'native':6,'torch':16 if system=='macos'else 15}

def verify_core_gates(gates:Path,*,system:str='linux'):
    try:
        errors=command_gate_errors(gates,{**ROOT_COMMANDS,**TORCH_COMMANDS},record_name='RUST.json')
        if errors:return errors
        for prefix,count in native_test_roots(system).items():
            listed=(gates/(prefix+'-list.log')).read_text();output=(gates/(prefix+'-tests.log')).read_text()
            if rust_gate_errors(listed,output)or len(re.findall(r'^([^\n]+): test$',listed,re.M))!=count:raise ValueError('complete native core test roots required: '+prefix)
        files=test_files(Path(__file__).resolve().parents[2]);records=load(gates/'PYTHON.json')
        if set(records)!={'python-list','python-tests'}:raise ValueError('complete core tooling commands required')
        for name,row in records.items():
            argv=row['command']
            if Path(argv[0]).name not in('python','python3','python3.12')or argv[1:-1]!=['-m','pytest','-o','addopts=','-q',*files]:raise ValueError('scoped core tooling command differs')
            if name=='python-list'and argv[-1]!='--collect-only':raise ValueError('core tooling discovery missing')
            if name=='python-tests'and(not argv[-1].startswith('--junitxml=')or Path(argv[-1].split('=',1)[1]).name!='python.xml'):raise ValueError('core tooling JUnit missing')
        errors=command_gate_errors(gates,{name:row['command']for name,row in records.items()},record_name='PYTHON.json')
        if errors:return errors
        discovered=[]
        for line in(gates/'python-list.log').read_text().splitlines():
            if any(line.startswith(name+'::')for name in files):
                path,node=line.split('::',1);discovered.append(path[:-3].replace('/','.')+'::'+node)
        states=junit_states(gates/'python.xml')
        if len(discovered)!=len(set(discovered))or len(discovered)!=PYTHON_ROOTS or set(discovered)!=set(states)or set(states.values())!={'passed'}:raise ValueError('complete native core tooling roots required')
        return lint_gate_errors(gates,LINT_COMMANDS)or lint_gate_errors(gates/'torch-lint',TORCH_LINT)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

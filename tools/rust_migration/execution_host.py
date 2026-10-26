"""Record validation execution profiles; replay uses recorded identities, never this CPU."""
from pathlib import Path
import ctypes,json
from .native_json import identity,load,same_value
from .execution_profiles import capabilities,descriptors,require
from .execution_registry import select
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors

FILE='EXECUTION-PROFILES.json'
TEST_FILES=['tests/rust_migration/test_execution_profiles.py','tests/rust_migration/test_execution_registry.py','tests/rust_migration/test_execution_host.py']
PYTHON_ROOTS=16
NATIVE=['cargo','test','--locked','--offline','-p','ken-models','--test','execution_profile']
COMMANDS={'profile-list':[*NATIVE,'--','--list'],'profile-tests':[*NATIVE,'--no-fail-fast']}

def detect_profiles(probe:Path,*,repo:Path|None=None):
    import numpy as np
    require(np.__version__=='2.4.4','profile NumPy version differs')
    libraries=list((Path(np.__file__).parent.parent/'numpy.libs').glob('libscipy_openblas64_*.so'))
    require(len(libraries)==1,'actual NumPy BLAS is ambiguous')
    library=libraries[0];runtime=ctypes.CDLL(str(library))
    core=runtime.scipy_openblas_get_corename64_;core.restype=ctypes.c_char_p
    threads=runtime.scipy_openblas_get_num_threads64_;threads.restype=ctypes.c_int
    caps=capabilities(probe)
    alignment=descriptors(caps,dict(core=core().decode(),threads=threads(),sha256=identity(library)['sha256']),repo or Path(__file__).resolve().parents[2])['alignment']
    return caps,alignment

def record_profiles(repo:Path,packet:Path,caps:dict,alignment:dict):
    path=packet/FILE;require(not path.exists(),'execution-profile packet already exists')
    ds=descriptors(caps,{key:alignment[key]for key in('core','threads','sha256')},repo)
    require(same_value(ds['alignment'],alignment),'alignment descriptor differs')
    references={kind:{key:select(repo,kind,descriptor)[0][key]for key in('id','reference')}for kind,descriptor in ds.items()}
    record=dict(format='ken-validation-execution-profiles/1',capabilities=caps,descriptors=ds,references=references)
    with path.open('x')as stream:stream.write(json.dumps(record,indent=2)+'\n')
    return record

def recorded_reference(repo:Path,packet:Path,kind:str):
    record=load(packet/FILE)
    require(set(record)=={'format','capabilities','descriptors','references'}and record['format']=='ken-validation-execution-profiles/1','profile packet schema differs')
    ds=record['descriptors'];alignment=ds['alignment']
    expected=descriptors(record['capabilities'],{key:alignment[key]for key in('core','threads','sha256')},repo)
    require(same_value(ds,expected)and set(record['references'])==set(expected),'recorded profile descriptors differ')
    selections={}
    for family,descriptor in ds.items():
        entry,original=select(repo,family,descriptor)
        require(same_value(record['references'][family],{key:entry[key]for key in('id','reference')}),'recorded reference identity differs')
        selections[family]=(entry,original)
    return selections[kind]

def verify_host(repo:Path,packet:Path):
    from .integration_validate import rust_gate_errors
    import re
    try:
        recorded_reference(repo,packet,'context');out=packet/'execution-profiles'
        errors=command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json');require(not errors,str(errors))
        listed=(out/'gates/profile-list.log').read_text();output=(out/'gates/profile-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==4,'all4execution profile native roots required')
        return python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def prepare_host(repo:Path,packet:Path,probe:Path):
    caps,alignment=detect_profiles(probe,repo=repo)
    with(packet/'DETECTED-PROFILES.json').open('x')as stream:
        stream.write(json.dumps(dict(format='ken-detected-execution-profiles/1',capabilities=caps,alignment=alignment,probe=identity(probe)),indent=2)+'\n')
    record_profiles(repo,packet,caps,alignment)
    out=packet/'execution-profiles';(out/'gates').mkdir(parents=True)
    run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
    run_python_scope(out,TEST_FILES)
    errors=verify_host(repo,packet);require(not errors,str(errors))

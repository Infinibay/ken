"""Source-bound qualification of real native public CLI and MCP processes."""
from pathlib import Path
import json,os,platform,re,shutil,subprocess,tarfile

from .command_gates import (cargo_artifact,command_gate_errors,run_command_gates,
    run_python_scope,python_scope_errors)
from .native_binary import check_native_architecture
from .native_core_evidence import core_source_identity,require
from .native_core_packet import tooling_identity
from .native_json import identity,load
from .native_snapshot import read_source_snapshot
from .public_search_capture import capture,verify_execution
from .public_search_resources import plan,input_errors
from .translation_cpu_build import PROOF_FILES,proof_errors
from .x86_translation_host import sdk_manifest

SPEC='docs/superpowers/specs/2026-10-28-rust-public-search-design.md'
PLAN='docs/superpowers/plans/2026-10-28-rust-public-search.md'
WORKFLOW='.github/workflows/rust-public-search.yml'
NATIVE=['cargo','test','--locked','--offline',*sum((['-p',p]for p in
    ('ken-core','ken-retrieval','ken-index','ken-syntax','ken-search','ken-cli')),[]),'--all-targets']
BUILD=['cargo','test','--locked','--offline','-p','ken-cli','--test','search_cli','--no-run','--message-format=json']
COMMANDS={
    'native-list':[*NATIVE,'--','--list'],
    'native-tests':[*NATIVE,'--no-fail-fast'],
    'fmt':['cargo','fmt','--all','--check'],
    'clippy':['cargo','clippy','--locked','--offline','-p','ken-cli','-p','ken-search',
        '-p','ken-retrieval','-p','ken-index','-p','ken-syntax','-p','ken-models','--all-targets','--','-D','warnings'],
}
PYTHON_FILES=['tests/rust_migration/test_public_search_host.py',
    'tests/rust_migration/test_public_search_packet.py','tests/rust_migration/test_command_gates.py']
PYTHON_ROOTS=21
NATIVE_ROOTS=261


def sources(repo):
    records=core_source_identity(repo)|tooling_identity(repo)
    for folder in('crates/ken-cli','native/ken-ct2-backend'):
        records.update({str(p.relative_to(repo)):identity(p)for p in(repo/folder).rglob('*')
            if p.is_file()and not any(v in('target','__pycache__')for v in p.relative_to(repo/folder).parts)})
    for name in(SPEC,PLAN,WORKFLOW):records[name]=identity(repo/name)
    for p in(repo/'.github/workflows').glob('rust*.yml'):records[str(p.relative_to(repo))]=identity(p)
    for p in(repo/'tools/rust_migration/data').glob('*.json'):records[str(p.relative_to(repo))]=identity(p)
    return records


def artifacts(log,repo,target):
    return {destination:cargo_artifact(log,repo,target,package='ken-cli',name=name,kind=kind,
        source=source,binary_pattern=pattern)for destination,name,kind,source,pattern in(
            ('ken-rs','ken-rs','bin','src/main.rs','ken-rs'),
            ('native-caller','search_cli','test','tests/search_cli.rs',r'search_cli-[0-9a-f]{16}'))}


def verify_capture(out,repo):
    try:
        out,repo=map(Path,(out,repo));host=load(out/'HOST.json')
        require(set(host)=={'format','os','arch','python','rustc','repo','target','commit','dirty'},'public host fields differ')
        require((host['format'],host['os'],host['arch'],host['python'])==
            ('ken-public-search-host/1','linux','x86_64','3.12.9')and host['rustc'].startswith('rustc 1.95.0 '),'public host tools/architecture differ')
        require(re.fullmatch('[0-9a-f]{40}',host['commit'])is not None and type(host['dirty'])is bool,'actual public Git state required')
        for key in('repo','target'):
            require(Path(host[key]).is_absolute()and'..'not in Path(host[key]).parts,'absolute public build roots required')
        require(load(out/'SOURCES.json')==sources(repo),'public source/tooling inventory differs')
        require(load(out/'SDK.json')==sdk_manifest(repo),'public CT2 SDK differs')
        build=load(out/'BACKEND-BUILD.json');module=out/'bin/libken_ct2_backend.so'
        require(build['source_root']==host['repo'],'public translation module built from another checkout')
        errors=proof_errors(build,out/'backend-proof',repo,identity(module),identity(out/'SDK.json'))
        require(not errors,str(errors))
        inputs=load(out/'INPUTS.json')
        errors=input_errors(inputs,repo,out/'GRAMMARS.json',build['registration']);require(not errors,str(errors))
        for name in('ken-rs','native-caller','libken_ct2_backend.so'):
            check_native_architecture(out/'bin'/name,('linux','x86_64'))
        errors=verify_execution(out/'native',repo,inputs,caller=identity(out/'bin/native-caller'),application=identity(out/'bin/ken-rs'))
        require(not errors,str(errors))
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError)as error:return[str(error)]


def verify_host(out,repo):
    try:
        out,repo=map(Path,(out,repo));errors=verify_capture(out,repo);require(not errors,str(errors))
        host=load(out/'HOST.json');require(host['dirty']is False,'public qualification requires committed sources')
        recorded_repo=Path(host['repo']);target=Path(host['target'])
        require(not(errors:=command_gate_errors(out/'gates',{'public-build':BUILD},record_name='BUILD.json',cwd=recorded_repo)),str(errors))
        selected=artifacts(out/'gates/public-build.log',recorded_repo,target)
        require(load(out/'BINARIES.json')=={name:dict(path=str(path),artifact=identity(out/'bin'/name))for name,path in selected.items()},'public binaries differ from Cargo-selected artifacts')
        require(not(errors:=command_gate_errors(out/'gates',COMMANDS,cwd=recorded_repo)),str(errors))
        from .integration_validate import rust_gate_errors
        listed=(out/'gates/native-list.log').read_text();completed=(out/'gates/native-tests.log').read_text()
        require(not rust_gate_errors(listed,completed)
            and len(re.findall(r'^([^\n]+): test$',listed,re.M))==NATIVE_ROOTS,'all native public dependencies must pass')
        require((out/'gates/fmt.log').read_bytes()==b''and re.search(r'Finished `dev` profile .*target\(s\) in \S+\s*$',(out/'gates/clippy.log').read_text())is not None,'actual fmt/strict Clippy completion required')
        require(not(errors:=python_scope_errors(out,PYTHON_FILES,PYTHON_ROOTS,cwd=recorded_repo)),str(errors))
        records=sources(repo);require(load(out/'SNAPSHOT.json')==records,'public source archive inventory differs')
        read_source_snapshot(out,required=records)
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError,tarfile.TarError)as error:return[str(error)]


def run_host(repo,out,*,allow_dirty=False):
    repo,out=map(lambda p:Path(p).resolve(),(repo,out))
    require(not out.exists()and not out.is_symlink(),'fresh public packet destination required')
    require((platform.system(),platform.machine(),platform.python_version())==('Linux','x86_64','3.12.9'),'pinned Linux x86 public host required')
    target=Path(os.environ.get('CARGO_TARGET_DIR',str(repo/'target')))
    if not target.is_absolute():target=repo/target
    target=target.absolute();saved=os.environ.copy();records=sources(repo)
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True))
    require(allow_dirty or not dirty,'commit public sources before qualification')
    (out/'gates').mkdir(parents=True)
    try:
        os.environ['CARGO_TARGET_DIR']=str(target)
        run_command_gates(out/'gates',{'public-build':BUILD},record_name='BUILD.json',cwd=repo)
        selected=artifacts(out/'gates/public-build.log',repo,target);(out/'bin').mkdir()
        for name,path in selected.items():shutil.copy2(path,out/'bin'/name)
        (out/'BINARIES.json').write_text(json.dumps({name:dict(path=str(path),artifact=identity(path))for name,path in selected.items()},indent=2)+'\n')
        inputs=plan(repo,os.environ);backend=Path(os.environ['KEN_CT2_PREPARATION']).parent
        built=load(backend/'PREPARATION.json')
        shutil.copyfile(built['module_path'],out/'bin/libken_ct2_backend.so')
        shutil.copyfile(backend/'PREPARATION.json',out/'BACKEND-BUILD.json')
        shutil.copyfile(Path(os.environ['KEN_CT2_SDK'])/'PREPARATION.json',out/'SDK.json')
        shutil.copyfile(os.environ['KEN_GRAMMAR_MANIFEST'],out/'GRAMMARS.json')
        for name in PROOF_FILES:
            destination=out/'backend-proof'/name;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(backend/name,destination)
        host=dict(format='ken-public-search-host/1',os='linux',arch='x86_64',python=platform.python_version(),
            rustc=subprocess.check_output(['rustc','--version'],text=True).strip(),repo=str(repo),target=str(target),
            commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),dirty=dirty)
        for name,value in(('HOST.json',host),('SOURCES.json',records),('INPUTS.json',inputs)):
            (out/name).write_text(json.dumps(value,indent=2)+'\n')
        capture(out/'native',repo,out/'bin/native-caller',out/'bin/ken-rs',inputs)
        errors=verify_capture(out,repo);require(not errors,str(errors))
        os.environ['KEN_PUBLIC_SEARCH_PACKET']=str(out)
        run_command_gates(out/'gates',COMMANDS,cwd=repo)
        run_python_scope(out,PYTHON_FILES,cwd=repo)
        require(records==sources(repo),'public sources changed during validation')
        with tarfile.open(out/'source-snapshot.tar.gz','w:gz')as archive:
            for name in sorted(records):archive.add(repo/name,arcname=name,recursive=False)
        (out/'SNAPSHOT.json').write_text(json.dumps(records,indent=2)+'\n')
        if not allow_dirty:
            errors=verify_host(out,repo);require(not errors,str(errors))
    finally:os.environ.clear();os.environ.update(saved)
    return out

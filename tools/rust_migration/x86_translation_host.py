"""Native-only x86 translation histories, source/build closure and command gates."""
from pathlib import Path
import json, os, platform, re, shutil, subprocess, sys, tarfile
from .native_json import NativeJsonCapture, identity, load, same_value, verify_native_json
from .native_binary import check_native_architecture
from .native_core_evidence import core_source_identity, require
from .native_core_packet import tooling_identity
from .native_snapshot import read_source_snapshot
from .translation_cpu_prepare import registration, expected_files, verify_sdk
from .translation_cpu_build import verify_build, source_files, PROOF_FILES
from .translation_compare import compare_output
from .x86_translation_reference import load as original, FIXTURE
from .command_gates import run_command_gates, command_gate_errors, run_python_scope, python_scope_errors

PREFIX='ken-x86-translation-'
MODEL='src/ken/embedder/data/es-en-ct2-int8.json'
SPEC='docs/superpowers/specs/2026-10-28-rust-x86-query-expansion-design.md'
PLAN='docs/superpowers/plans/2026-10-28-rust-x86-query-expansion.md'
PYTHON_FILES=['tests/rust_migration/test_'+name+'.py'for name in(
    'translation_reference','x86_translation_reference','translation_compare','translation_cpu_prepare',
    'translation_cpu_build','native_core_prepare','x86_translation_host')]
PYTHON_ROOTS=61
RUST_TEST=['cargo','test','--locked','--offline','-p','ken-models','--lib','--test','query_expansion','--test','translation_runtime','--test','model_factory']
SEARCH_TEST=['cargo','test','--locked','--offline','-p','ken-search','--test','translation_warming']
COMMANDS={
    'model-list':[*RUST_TEST,'--','--list'],'model-tests':[*RUST_TEST,'--no-fail-fast'],
    'search-list':[*SEARCH_TEST,'--','--list'],'search-tests':[*SEARCH_TEST,'--no-fail-fast'],
    'probe-build':['cargo','build','--locked','--offline','-p','ken-models','--example','translation_probe'],
    'fmt':['cargo','fmt','--all','--check'],
    'clippy':['cargo','clippy','--locked','--offline','-p','ken-models','-p','ken-search','--all-targets','--','-D','warnings'],
}

def sources(repo):
    result=core_source_identity(repo)|tooling_identity(repo)
    for pattern in ('native/ken-ct2-backend/**/*','tools/rust_migration/data/*.json','.github/workflows/rust*.yml'):
        result.update({str(p.relative_to(repo)):identity(p)for p in repo.glob(pattern)if p.is_file()})
    for name in (MODEL,SPEC,PLAN):result[name]=identity(repo/name)
    for p in (repo/'docs/validation/rust-migration-2026-10-19/m2-translation').glob('*.json'):
        result[str(p.relative_to(repo))]=identity(p)
    return result

def declaration(module,repo):
    return dict(format='ken-native-translation/1',runtimes=[dict(os='linux',arch='x86_64',
        core_version='4.8.2',abi=1,module=module,libraries=registration(repo)['libraries'])])

def request_for(expected,root,module,repo):
    return dict(registration=expected['definition'],source=str(root/'source'/expected['definition']['source']['revision']),
        cache=str(root/'prepared'/expected['definition']['derived']['revision']),cases=expected['cases'],
        native_runtime=dict(registration=declaration(module,repo),module_path=str(root/'runtime/libken_ct2_backend.so'),core_root=str(root/'runtime')))

def generated(expected):
    prefix='prepared/'+expected['definition']['derived']['revision']+'/'
    return {prefix+name:row for name,row in expected['prepared_artifacts'].items()}

def sdk_manifest(repo):
    row=registration(repo)
    return dict(format='ken-translation-cpu-sdk/1',os='linux',arch='x86_64',version='4.8.2',
        source_wheel=row['wheel'],source_headers=row['headers'],files=expected_files(row),python_runtime_imported=False)

def verify_capture(out,repo):
    try:
        out,repo=map(Path,(out,repo));expected=original(repo);host=load(out/'HOST.json')
        require(host['format']=='ken-x86-translation-host/1'and(host['os'],host['arch'])==('linux','x86_64'),'x86 translation host differs')
        require(host['python']=='3.12.9'and host['rustc'].startswith('rustc 1.95.0 '),'pinned host tools differ')
        require(re.fullmatch('[0-9a-f]{40}',host['commit'])is not None and type(host['dirty'])is bool,'candidate Git state missing')
        cpu=(out/'CPUINFO.txt').read_text();vendors=set(re.findall(r'^vendor_id\s*:\s*(\S+)',cpu,re.M))
        require(len(vendors)==1 and host['cpu_vendor']in vendors,'actual CPU vendor differs')
        backend='MKL'if host['cpu_vendor']=='GenuineIntel'else'DNNL'
        require(host['backend']==backend,'default CT2 CPU backend differs')
        require(load(out/'SOURCES.json')==sources(repo),'complete translation source/tooling inventory differs')
        require(load(out/'SDK.json')==sdk_manifest(repo),'registered SDK source/header inventory differs')
        binary=out/'bin/translation_probe';module=out/'bin/libken_ct2_backend.so'
        for path in(binary,module):check_native_architecture(path,('linux','x86_64'))
        build=load(out/'BACKEND-BUILD.json')
        require(build['format']=='ken-translation-cpu-build/1'and build['sources']==source_files(repo),'native module source binding differs')
        require(build['registration']==declaration(identity(module),repo)and build['sdk']==identity(out/'SDK.json'),'native module/core build identity differs')
        require(build['cmake_version'].splitlines()[0]=='cmake version 3.31.10','pinned CMake proof missing')
        require(build['proof_files']=={name:identity(out/'backend-proof'/name)for name in PROOF_FILES},'compiler/build log proof differs')
        require('Built target ken_ct2_backend'in(out/'backend-proof/1.stdout').read_text(),'actual native module compilation absent')
        require(not(out/'backend-proof/0.stderr').read_bytes()and not(out/'backend-proof/1.stderr').read_bytes(),'native module compiler diagnostics present')
        capture=out/'native';errors=verify_native_json(capture,PREFIX,generated_files=generated(expected));require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd'])
        require((execution['system'],execution['machine'])==('linux','x86_64')and not root.is_relative_to(repo.resolve()),'actual native execution host differs')
        require(execution['native_sha256']==identity(binary)['sha256'],'native probe differs')
        request=request_for(expected,root,identity(module),repo)
        require(same_value(load(capture/'inputs.json'),request),'translation request contains answers or foreign resources')
        resources={'native-probe':identity(binary),'runtime/libken_ct2_backend.so':identity(module)}
        resources.update({'runtime/'+name:row for name,row in registration(repo)['libraries'].items()})
        resources.update({'source/'+expected['definition']['source']['revision']+'/'+name:row for name,row in expected['source_artifacts'].items()})
        require(execution['owned_before']==resources,'complete native resource closure differs')
        errors=compare_output(expected,load(capture/'stdout.json'),backend=backend);require(not errors,str(errors))
        loader=(capture/'stderr.log').read_text()
        require('ken-ct2-core-'in loader and 'libctranslate2-'in loader,'actual private CT2 loading absent')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError)as error:return[str(error)]

def verify_host(out,repo):
    try:
        out,repo=map(Path,(out,repo))
        errors=verify_capture(out,repo);require(not errors,str(errors))
        require(load(out/'HOST.json')['dirty']is False,'qualified candidate must be committed')
        errors=command_gate_errors(out/'gates',COMMANDS);require(not errors,str(errors))
        from .integration_validate import rust_gate_errors
        for name,count in(('model',67),('search',1)):
            listed=(out/'gates'/f'{name}-list.log').read_text();output=(out/'gates'/f'{name}-tests.log').read_text()
            require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==count,'complete native test roots required: '+name)
        errors=python_scope_errors(out,PYTHON_FILES,PYTHON_ROOTS);require(not errors,str(errors))
        records=sources(repo);require(load(out/'SNAPSHOT.json')==records,'translation snapshot inventory differs')
        read_source_snapshot(out,required=records)
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError,tarfile.TarError)as error:return[str(error)]

def _capture_into(repo,out,source,sdk,backend):
    repo,out,source,sdk,backend=map(Path,(repo,out,source,sdk,backend))
    if(platform.system(),platform.machine())!=('Linux','x86_64'):raise ValueError('Linux x86 translation host required')
    if errors:=verify_sdk(sdk,repo):raise ValueError(errors)
    if errors:=verify_build(backend,repo,sdk):raise ValueError(errors)
    expected=original(repo);records=sources(repo);ready=load(backend/'PREPARATION.json')
    (out/'bin').mkdir()
    binary=repo/'target/debug/examples/translation_probe';shutil.copy2(binary,out/'bin/translation_probe')
    module=Path(ready['module_path']);shutil.copy2(module,out/'bin/libken_ct2_backend.so')
    shutil.copyfile(sdk/'PREPARATION.json',out/'SDK.json');shutil.copyfile(backend/'PREPARATION.json',out/'BACKEND-BUILD.json')
    for name in PROOF_FILES:
        target=out/'backend-proof'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(backend/name,target)
    cpu=Path('/proc/cpuinfo').read_text();(out/'CPUINFO.txt').write_text(cpu)
    vendors=set(re.findall(r'^vendor_id\s*:\s*(\S+)',cpu,re.M));require(len(vendors)==1,'one CPU vendor required');vendor=vendors.pop()
    host=dict(format='ken-x86-translation-host/1',os='linux',arch='x86_64',python=platform.python_version(),
        rustc=subprocess.check_output(['rustc','--version'],text=True).strip(),cpu_vendor=vendor,backend='MKL'if vendor=='GenuineIntel'else'DNNL',
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)))
    (out/'HOST.json').write_text(json.dumps(host,indent=2)+'\n');(out/'SOURCES.json').write_text(json.dumps(records,indent=2)+'\n')
    with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,generated_files=generated(expected))as process:
        request=request_for(expected,process.root,identity(module),repo)
        source_root=Path(request['source']);source_root.mkdir(parents=True)
        for name,wanted in expected['source_artifacts'].items():
            require(identity(source/name)==wanted,'registered translation source changed: '+name)
            shutil.copyfile(source/name,source_root/name)
        runtime=process.root/'runtime';runtime.mkdir();shutil.copyfile(module,runtime/'libken_ct2_backend.so')
        for name in registration(repo)['libraries']:shutil.copyfile(sdk/'lib'/name,runtime/name)
        process.run(request)
    require(records==sources(repo),'translation sources changed during native execution')
    if errors:=verify_capture(out,repo):raise ValueError(errors)
    return out

def capture(repo,out,source,sdk,backend):
    out=Path(out)
    if out.exists()or out.is_symlink():raise ValueError('fresh translation host output required')
    out.mkdir(parents=True)
    return _capture_into(repo,out,source,sdk,backend)

def run_host(repo,out,source,sdk,backend):
    # The caller prepares immutable physical inputs and all dependent test assets.
    repo,out,source,sdk,backend=map(Path,(repo,out,source,sdk,backend))
    if out.exists()or out.is_symlink():raise ValueError('fresh translation host output required')
    (out/'gates').mkdir(parents=True);environment=os.environ.copy()
    try:
        os.environ.update(KEN_CT2_SDK=str(sdk),KEN_CT2_PREPARATION=str(backend/'PREPARATION.json'),
            KEN_TRANSLATION_SOURCE=str(source),KEN_X86_TRANSLATION_PACKET=str(out))
        run_command_gates(out/'gates',{'probe-build':COMMANDS['probe-build']},record_name='BUILD.json')
        _capture_into(repo,out,source,sdk,backend)
        run_command_gates(out/'gates',COMMANDS)
        run_python_scope(out,PYTHON_FILES)
        records=sources(repo)
        with tarfile.open(out/'source-snapshot.tar.gz','w:gz')as archive:
            for name in sorted(records):archive.add(repo/name,arcname=name,recursive=False)
        (out/'SNAPSHOT.json').write_text(json.dumps(records,indent=2)+'\n')
        if errors:=verify_host(out,repo):raise ValueError(errors)
    finally:os.environ.clear();os.environ.update(environment)
    return out

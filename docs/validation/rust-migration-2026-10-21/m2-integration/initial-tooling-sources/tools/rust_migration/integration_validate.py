"""Final gates authenticate complete raw regression and saved model observations."""
from __future__ import annotations
from collections import Counter
import re


def rust_gate_errors(discovery:str,output:str)->list[str]:
    expected=Counter(re.findall(r'^([^\n]+): test$',discovery,re.M))
    actual=Counter(re.findall(r'^test ([^\n]+) \.\.\. ok$',output,re.M))
    errors=[]
    if not expected or actual!=expected:errors.append('missing, duplicate or unexpected executed Rust cases')
    if re.search(r'\b[1-9]\d* (failed|ignored|filtered out)\b|test result: FAILED|^error:',output,re.M):
        errors.append('failed, ignored, filtered or aborted Rust suite')
    counts=[int(n)for n in re.findall(r'test result: ok\. (\d+) passed; 0 failed; 0 ignored;',output)]
    if sum(counts)!=sum(expected.values()):errors.append('incomplete Rust result counters')
    return errors

from pathlib import Path
import hashlib,json
from .integration_replay import _json,replay_role,replay_transformer_profile
from .policy_evidence import _read,_relative
from .transformer_evidence import source_identity
from .reference import verify_reference
from .receipts import compare_python

# These are earlier accepted scopes, at their original sources/hosts. Their
# immutable manifest identities cannot be replaced by a new passing flag.
PREDECESSORS={
 'docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance':'17222298037b7e957e36fbb76af94c80f2bed9450fde3b1a115346b8b75d42ed',
 'docs/validation/rust-migration-2026-10-20/m2-transformer-review':'a474592018a9adb2a8922c2a969fcfd8741cc1ada5ccd3bc8ae39d267cef2382',
 'docs/validation/rust-migration-2026-10-21/m2-native-transport':'b0c9f01be0cc25f6a095bd35e1e1958ac42698facc8adf8a287d5ea1ced2f98f',
}


def _identity(raw:bytes)->dict:
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def _manifest_errors(directory:Path,pinned:str|None=None)->list[str]:
    try:
        raw=_read(directory,'FILES.json')
        if pinned and hashlib.sha256(raw).hexdigest()!=pinned:raise ValueError('pinned manifest changed')
        manifest=json.loads(raw);names=[]
        for row in manifest['files']:
            name=str(_relative(row['path']));names.append(name)
            if _identity(_read(directory,name))!={k:row[k]for k in('bytes','sha256')}:raise ValueError('artifact changed: '+name)
        actual={str(p.relative_to(directory))for p in directory.rglob('*')if p.is_file()}
        if len(names)!=len(set(names))or actual!=set(names)|{'FILES.json'}:raise ValueError('manifest membership differs')
        return []
    except(OSError,ValueError,KeyError,TypeError)as error:return [str(directory)+': '+str(error)]


def verify_predecessors(repo:Path)->list[str]:
    errors=[]
    for path,identity in PREDECESSORS.items():errors.extend(_manifest_errors(repo/path,identity))
    return errors


def tooling_identity(repo:Path)->dict:
    paths=sorted((repo/'tools/rust_migration').glob('integration_*.py'))
    paths+=[repo/'tools/rust_migration/transformer_process.py']
    paths+=sorted((repo/'tests/rust_migration').glob('test_integration_*.py'))
    paths+=sorted(p for p in(repo/'crates/ken-models/tests/fixtures/factory-integration').rglob('*')if p.is_file())
    return {str(p.relative_to(repo)):_identity(p.read_bytes())for p in paths}


def aggregate_integration(directory:Path,repo:Path)->dict:
    result={'scope':'model-integration-matrix','passed':False,'M2_accepted':False,'errors':[]}
    try:
        def require(condition,message):
            if not condition:raise ValueError(message)
        errors=_manifest_errors(directory);require(not errors,'; '.join(errors))
        index=_json(directory/'INDEX.json')
        require(index['format']=='ken-model-integration-acceptance/1','wrong integration protocol')
        require(index['source_files']==source_identity(repo),'current native production sources changed')
        require(index['workspace_files']==workspace_identity(repo),'current workspace production sources changed')
        require(index['tooling']==tooling_identity(repo),'current integration validator/tests changed')
        require(index['predecessors']==PREDECESSORS,'complete pinned predecessor scopes required')
        errors=verify_predecessors(repo);require(not errors,'; '.join(errors))
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'original sources changed')
        require(set(index['platforms'])=={'macos','linux'},'both actual platforms required')
        expected_roles={(n,'offline')for n in('static','potion','context','reranker','expansion','fastembed')}|{('fastembed','public')}
        for system,receipt in index['platforms'].items():
            root=directory/system;build=_json(root/'BUILD.json')
            require(build['source_files']==index['source_files'],'host build source identity differs')
            require(re.fullmatch('[0-9a-f]{64}',build['native_sha256'])is not None,'invalid actual host identity')
            require(receipt['profiles']==(24 if system=='macos'else 9),'complete registered profile inventory required')
            profiles=root/'transformers/profiles'
            require({p.name for p in profiles.iterdir()if p.is_dir()}=={f'{i:02d}'for i in range(receipt['profiles'])},'missing/extra factory profile')
            for number in range(receipt['profiles']):
                folder=profiles/f'{number:02d}';require(_json(folder/'BUILD.json')==build,'profile host build differs')
                errors=replay_transformer_profile(folder,repo,system,number);require(not errors,'; '.join(errors))
            roles=root/'roles'
            require({p.name for p in roles.iterdir()if p.is_dir()}=={n+'-'+phase for n,phase in expected_roles},'missing/extra public factory role')
            for name,phase in sorted(expected_roles):
                folder=roles/(name+'-'+phase);require(_json(folder/'BUILD.json')==build,'role host build differs')
                errors=replay_role(folder,repo,system,name,phase);require(not errors,'; '.join(errors))
            gates=root/'gates'
            rust_errors=rust_gate_errors(_read(gates,'rust-list.log').decode(),_read(gates,'rust-tests.log').decode())
            require(not rust_errors,'; '.join(rust_errors))
            baseline_root=repo/'docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance'/system
            baselines=list(baseline_root.rglob('python-final.xml'));require(len(baselines)==1,'one retained original full Python baseline required')
            comparison=compare_python(baselines[0],gates/'python-full.xml')
            require(comparison['passed']and not comparison['current_failures'],'full Python regressions/omissions differ: '+str(comparison))
            full_log=_read(gates,'python-full.log').decode();require(re.search(r'\b[1-9]\d* passed\b',full_log)is not None,'complete Python raw output missing')
            clippy=_read(gates,'clippy.log').decode();require('Finished `dev` profile'in clippy and'error:'not in clippy,'current clippy gate missing/failed')
            require(_read(gates,'fmt.log')==b'','format gate failed')
            commands=_json(gates/'commands.json')
            required={'rust':['cargo','test','--offline','--locked','--workspace','--all-targets'],
                      'python':['python','-m','pytest'],'fmt':['cargo','fmt','--all','--','--check'],
                      'clippy':['cargo','clippy','--offline','--locked','--workspace','--all-targets','--','-D','warnings']}
            require(commands['invocations']==required and all(commands['exits'].get(k)==0 for k in required),'actual final command outcomes missing/failed')
            require(_read(gates,'toolchain.log').decode().startswith('rustc 1.95.0 '),'pinned toolchain missing')
            capacity=_json(gates/'capacity.json')
            require(all(type(capacity[k])is int and capacity[k]>0 for k in('free_bytes','required_bytes','allocated_bytes')),'measured capacity missing')
            require(capacity['required_bytes']>=3*1024**3 and capacity['free_bytes']>=capacity['required_bytes'],'physical preparation reserve unavailable')
            from .storage_recovery import recovery_receipt_errors
            recovery_root=gates/'storage-recovery';recovery=_json(recovery_root/'summary.json')
            binding=_json(recovery_root/'binding.json')
            require(binding['source_files']==index['workspace_files']and binding['driver_sha256']==recovery['driver_sha256'],'current-source recovery binary binding differs')
            errors=recovery_receipt_errors(recovery);require(not errors,'; '.join(errors))
            for case in recovery['cases']:
                folder=recovery_root/case['id']
                for state in('before','after','final','repeat'):
                    require(_json(folder/('original.'+state+'.json'))=={'oracle':recovery['reference_oracle'],'data':case[state]},'raw recovery original state differs')
                for execution in case['executions']:
                    name=execution['role']
                    require(_json(folder/(name+'.execution.json'))==execution,'raw recovery execution differs')
                    require(_read(folder,name+'.stdout.log').decode()==execution['stdout']and _read(folder,name+'.stderr.log').decode()==execution['stderr'],'raw recovery command output differs')
                    if system=='linux':require(len(re.findall(r'\bexecve(?:at)?\(',_read(folder,name+'.trace').decode()))==1,'unexpected recovery child exec')
        result.update(passed=True,M2_accepted=True,platforms=['macos','linux'])
    except(OSError,ValueError,KeyError,TypeError,IndexError,AttributeError)as error:result['errors'].append(str(error))
    return result


def workspace_identity(repo:Path)->dict:
    paths={repo/'Cargo.toml',repo/'Cargo.lock',repo/'rust-toolchain.toml'}
    for package in ('ken-cli','ken-core','ken-models','ken-native-model-api','ken-store'):
        root=repo/'crates'/package
        for path in root.rglob('*'):
            if path.is_file()and not any(p in('tests','target','__pycache__')for p in path.relative_to(root).parts):paths.add(path)
    return {str(p.relative_to(repo)):_identity(p.read_bytes())for p in sorted(paths)}

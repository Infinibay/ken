"""Authenticate raw source-observation processes independently of the controller."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import re
from .fastembed_process import _distinct,_nonfinite
from .source_validate import compare_source_observations


def _json(path:Path):
    raw=path.read_bytes()
    if len(raw)>8*1024*1024:raise ValueError('source JSON exceeds bound')
    return json.loads(raw,object_pairs_hook=_distinct,parse_constant=_nonfinite)


def verify_source_capture(directory:Path,reference:dict,sources:dict,native_sha256:str,
                          system:str|None=None)->list[str]:
    system=system or ('macos'if platform.system()=='Darwin'else'linux')
    try:
        def require(condition,message):
            if not condition:raise ValueError(message)
        actual=_json(directory/'observations.json')
        errors=compare_source_observations(reference,actual,sources,native_sha256)
        require(not errors,'; '.join(errors))
        def execution(folder,request,expected):
            require(_json(folder/'inputs.json')==request,'actual native request bytes differ')
            require(_json(folder/'stdout.json')==expected,'actual native response bytes differ')
            receipt=_json(folder/'execution.json');command=receipt['command'];cwd=Path(receipt['cwd'])
            require(receipt['exit']==0 and receipt['native_sha256']==native_sha256 and receipt['timeout_s']==15,
                    'actual execution failed or host/bound differs')
            require(cwd.is_absolute()and cwd.name.startswith('ken-source-process-')and Path(command[-1])==cwd/'source-probe',
                    'actual native consumer was not copied outside checkout')
            require(Path(request['root']).is_relative_to(cwd)and receipt['env']['PATH']==str(cwd/'empty-path'),
                    'native input tree or sentinel PATH differs')
            loader=(folder/'stderr.log').read_bytes()
            require(len(loader)<=16*1024*1024 and b'libpython'not in loader and b'libtorch_python'not in loader,
                    'forbidden linkage or unbounded loader output')
            if system=='linux':
                require(Path(command[0]).name=='strace'and command[1:5]==['--seccomp-bpf','-f','-e','trace=execve,execveat,connect'],
                        'actual exec/network tracer command differs')
                trace=(folder/'exec.trace').read_text()
                require(len(re.findall(r'\bexecve(?:at)?\(',trace))==1 and command[-1]in trace and not re.search(r'\bconnect\(',trace),
                        'unexpected native subprocess or network connection')
                require(receipt['env']['LD_DEBUG']=='libs'and b'calling init:'in loader,'actual native Linux loader audit missing')
            else:
                require(system=='macos'and command==[str(cwd/'source-probe')]
                    and receipt['env']['DYLD_PRINT_LIBRARIES']=='1'and b'dyld['in loader,'actual native macOS loader audit missing')
        expected_inventory={case['id']:{f'{i:02d}'for i in range(len(case['walks']))}for case in reference['cases']}
        require({p.name for p in(directory/'observations').iterdir()}==set(expected_inventory),'capture case directories differ')
        for name,indexes in expected_inventory.items():
            require(re.fullmatch('[a-z0-9-]+',name)is not None,'unsafe case identity')
            require({p.name for p in(directory/'observations'/name).iterdir()}==indexes,'capture scope directories differ')
        for row in actual['observations']:
            folder=directory/'observations'/row['case']/f"{row['scope_index']:02d}"
            execution(folder,row['request'],row['actual'])
        integrity={'format':'ken-source-observation/1','scope':'.','entries':[{'path':'valid.py','is_dir':False}],
            'errors':[{'kind':'cycle','path':'cycle'},{'kind':'outside_project','path':'external-dir'},
                      {'kind':'outside_project','path':'external-file'}]}
        require(actual['integrity']==integrity,'declared integrity correction observations differ')
        request=_json(directory/'integrity/inputs.json')
        require(request['scope']=='.'and Path(request['root']).name=='integrity','wrong integrity input')
        execution(directory/'integrity',request,integrity)
        return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return [str(error)]


def aggregate_source_matrix(directory:Path,repo:Path)->dict:
    """Authenticate this historical native source snapshot, not future M3 code."""
    result=dict(scope='source-discovery-matrix',passed=False,M3a_accepted=False,M3_accepted=False,errors=[])
    try:
        from .integration_validate import _manifest_errors,rust_gate_errors
        from .receipts import junit_states
        from .reference import verify_reference
        from .source_validate import source_identity
        import hashlib
        def require(condition,message):
            if not condition:raise ValueError(message)
        errors=_manifest_errors(directory);require(not errors,'; '.join(errors))
        index=_json(directory/'INDEX.json')
        require(index['format']=='ken-source-discovery-matrix/1','wrong source matrix format')
        predecessor='docs/validation/rust-migration-2026-10-23/m2-integration-review'
        pinned='293f1de6f3865a8f5c6c4ab489e804b77adaa18863599ef0d044741594ee76bb'
        require(index['predecessor']=={'path':predecessor,'manifest_sha256':pinned},'accepted M2 predecessor differs')
        require(hashlib.sha256((repo/predecessor/'FILES.json').read_bytes()).hexdigest()==pinned,
            'accepted M2 predecessor manifest changed')
        errors=_manifest_errors(repo/predecessor);require(not errors,'; '.join(errors))
        require(index['sources']==source_identity(directory/'native-sources'),'recorded native sources differ')
        for name,identity in index['tooling'].items():
            require(not Path(name).is_absolute()and'..'not in Path(name).parts,'unsafe tooling source identity')
            raw=(directory/'validation-sources'/name).read_bytes()
            require(identity=={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'recorded validation source differs')
        require(set(index['platforms'])=={'macos','linux'},'both actual native platforms required')
        baseline=_json(repo/'docs/validation/rust-migration-2026-10-18/baseline.json')
        owners={r['path']:r['sha256']for r in baseline['files']if r['path']in('src/ken/_paths.py','src/ken/gitignore_filter.py')}
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'original sources changed')
        originals={system:_json(directory/'originals'/(system+'.json'))for system in('macos','linux')}
        require(originals['macos']['cases']==originals['linux']['cases']and
            originals['macos']['definitions']==originals['linux']['definitions'],'original platform input/results differ')
        for system,receipt in index['platforms'].items():
            original=originals[system];runtime=original['runtime']
            require(original['sources']==owners and runtime['python']=='3.12.9'and runtime['pathspec']=='1.1.1',
                'original owner/package identity differs')
            require((runtime['system'],runtime['machine'])==(('Darwin','arm64')if system=='macos'else('Linux','aarch64')),
                'original platform identity differs')
            raw=json.loads(original['execution']['stdout'],object_pairs_hook=_distinct,parse_constant=_nonfinite)
            require(raw=={'cases':original['cases'],'runtime':runtime}and original['execution']['exit']==0,'raw original observations differ')
            require(len(original['cases'])==15 and sum(len(c['walks'])for c in original['cases'])==51,
                'complete original case inventory required')
            errors=verify_source_capture(directory/system,original,index['sources'],receipt['native_sha256'],system)
            require(not errors,'; '.join(errors))
            gates=directory/'gates'/system
            errors=rust_gate_errors((gates/'rust-list.log').read_text(),(gates/'rust-tests.log').read_text());require(not errors,'; '.join(errors))
            require(len(re.findall(r'^([^\n]+): test$',(gates/'rust-list.log').read_text(),re.M))==30,'complete current Rust cases required')
            states=junit_states(gates/'python.xml')
            discovered=set()
            for path,name in re.findall(r'^(tests/rust_migration/test_source_[^:\n]+\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M):
                discovered.add(path[:-3].replace('/','.')+'::'+name)
            require(len(discovered)==24 and set(states)==discovered and set(states.values())=={'passed'},'complete affected Python cases required')
            clippy=(gates/'clippy.log').read_text();require('Finished `dev` profile'in clippy and'error:'not in clippy and'warning:'not in clippy,'clippy failed/missing')
            require((gates/'fmt.log').read_bytes()==b'','format gate failed')
            require(re.fullmatch('[0-9a-f]{64}',receipt['native_sha256'])is not None,'invalid native identity')
        result.update(passed=True,M3a_accepted=True)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:result['errors'].append(str(error))
    return result

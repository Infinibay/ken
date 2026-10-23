"""Authenticate actual import observations without trusting passing summaries."""
from __future__ import annotations
from pathlib import Path
from .native_json import load,verify_native_json
from .import_validate import requests,compare_import_observations

def verify_import_capture(out:Path,cases:list[dict],sources:dict|None=None,native_sha256:str|None=None)->list[str]:
    try:
        def require(value,message):
            if not value:raise ValueError(message)
        errors=verify_native_json(out,'ken-import-process-');require(not errors,'; '.join(errors))
        build=load(out/'BUILD.json');execution=load(out/'execution.json')
        require(build['format']=='ken-import-build/1'and build['sources']==load(out/'SOURCES.json'),'native import source inputs differ')
        if sources is not None:require(build['sources']==sources,'native import source snapshot differs')
        require(build['native_sha256']==execution['native_sha256'],'native import binary differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned native import binary differs')
        expected,resources=requests(cases,Path(execution['cwd']))
        require(load(out/'inputs.json')==expected,'actual native import request differs/contains expectations')
        require(build['resources']==resources,'actual native project config identities differ')
        expected_owned={r['path']:{k:r[k]for k in ('bytes','sha256')}for r in resources}
        expected_owned['native-probe']=execution['owned_before']['native-probe']
        require(execution['owned_before']==expected_owned,'actual project config bytes/inventory differ')
        errors=compare_import_observations(cases,load(out/'stdout.json'));require(not errors,'; '.join(errors))
        return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]


def aggregate_import_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False)->dict:
    """Accept import resolution only; compressed source snapshots remain replayable."""
    import json,re,tarfile,tempfile
    from .integration_validate import _manifest_errors,rust_gate_errors
    from .import_reference import SCRIPT,validate_import_reference,import_owner_hashes
    from .import_validate import import_cases,source_identity,FIXTURES
    from .native_json import identity
    from .receipts import junit_states
    from .reference import verify_reference
    result=dict(passed=False,M3c_accepted=False,M3_accepted=False,migration_complete=False,errors=[])
    try:
        def require(value,message):
            if not value:raise ValueError(message)
        errors=_manifest_errors(directory);require(not errors,'; '.join(errors))
        index=load(directory/'INDEX.json')
        require(index['format']=='ken-import-matrix/1','wrong import matrix protocol')
        require(index['sources']==source_identity(snapshot/'native-sources'),'native import source snapshot differs')
        if current:require(index['sources']==source_identity(repo),'current import sources differ')
        for name,expected in index['tooling'].items():
            require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'validation source differs')
        predecessor=dict(path='docs/validation/rust-migration-2026-10-23/m3-parsers-review',sha256='c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8')
        require(index['predecessor']==predecessor,'closed parser predecessor differs')
        require(identity(repo/predecessor['path']/'FILES.json')['sha256']==predecessor['sha256']and not _manifest_errors(repo/predecessor['path']),'parser receipt changed')
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'original1066files changed')
        require(set(index['platforms'])=={'macos','linux'},'both actual platforms required')
        cases=import_cases(snapshot/'native-sources');require(len(cases)==91 and len({c['id']for c in cases})==91 and sum(len(c['input']['imports'])for c in cases)==92,'complete import inventory required')
        fixtures=snapshot/'native-sources/crates/ken-core/tests/fixtures'
        supplements={name:load(fixtures/(name+'.json'))for name in FIXTURES[1:]}
        direct_script='\n'.join('exit_code=0'if line.startswith('exit_code=pytest.main(')else line for line in SCRIPT.splitlines())+'\n'
        for name,value in supplements.items():
            require(value['format']=='ken-import-supplements/1'and value['script']==direct_script and value['owners']==import_owner_hashes(repo),'supplement script/owners differ')
            require(value['execution']['exit']==0 and json.loads(value['execution']['observations'])['cases']==value['cases'],'raw supplement original differs')
        original_cases=None
        for system,platform in index['platforms'].items():
            with tempfile.TemporaryDirectory(prefix='ken-import-replay-')as temporary:
                raw=Path(temporary)
                with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
                original=load(raw/'original/reference.json')
                require(not validate_import_reference(original)and original['owners']==import_owner_hashes(repo),'invalid original import reference')
                runtime=original['runtime'];expected=('Darwin','arm64')if system=='macos'else('Linux','aarch64')
                require((runtime['system'],runtime['machine'],runtime['python'])==(*expected,'3.12.9'),'original platform differs')
                if original_cases is None:original_cases=original['cases']
                require(original['cases']==original_cases==load(fixtures/'import-reference.json')['cases'],'original platform cases differ')
                for file,key in [('stdout.log','stdout_sha256'),('stderr.log','stderr_sha256'),('original-observations.json','observations_sha256')]:require(identity(raw/'original'/file)['sha256']==original['test_execution'][key],'raw original process bytes differ')
                observed=load(raw/'original/original-observations.json')
                require(all(original[k]==v for k,v in observed.items()),'raw original observations differ')
                require(len(junit_states(raw/'original/original-tests.xml'))==33 and set(junit_states(raw/'original/original-tests.xml').values())=={'passed'},'actual original indexer suite differs')
                for name,value in supplements.items():
                    extra=load(raw/'supplements'/(name+'.json'))
                    require(extra['cases']==value['cases']and(extra['runtime']['system'],extra['runtime']['machine'])==expected and extra['runtime']['python']=='3.12.9','independent original supplements differ')
                errors=verify_import_capture(raw/'native',cases,index['sources'],platform['native_sha256']);require(not errors,'; '.join(errors))
                execution=load(raw/'native/execution.json')
                require(execution['system']==system and execution['machine']==expected[1],'native platform differs')
                gates=raw/'gates'
                require(not rust_gate_errors((gates/'rust-list.log').read_text(),(gates/'rust-tests.log').read_text()),'complete native tests differ')
                require(len(re.findall(r'^([^\n]+): test$',(gates/'rust-list.log').read_text(),re.M))==44,'complete44native root cases required')
                states=junit_states(gates/'python.xml')
                discovered={path[:-3].replace('/','.')+'::'+name for path,name in re.findall(r'^(tests/rust_migration/test_import_(?:reference|validate|evidence)\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)}
                require(len(discovered)==33 and set(states)==discovered and set(states.values())=={'passed'},'complete33affected tooling cases required')
                clippy=(gates/'clippy.log').read_text();require('Finished `dev` profile'in clippy and'error:'not in clippy and'warning:'not in clippy,'clippy failed/missing')
                require((gates/'fmt.log').read_bytes()==b'','format failed')
        result.update(passed=True,M3c_accepted=True,per_platform=dict(Rust=44,Python=33,original_inputs=91,native_cases=182,import_requests=184))
    except(OSError,ValueError,KeyError,TypeError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
    return result

"""Authenticate every original family, the actual native process and platform gates."""
from __future__ import annotations
import hashlib,math,re,tarfile,tempfile
from pathlib import Path
from .native_json import identity,load,verify_native_json
from .selection_reference import SCRIPTS,SUITES,definitions,owners,validate_reference
from .selection_validate import FORMAT,requests,compare_observations,source_identity
from .retrieval_validate import runtime_manifest
from .index_validate import same_value,require
from .integration_validate import _manifest_errors,rust_gate_errors
from .receipts import junit_states
PREDECESSOR=dict(path='docs/validation/rust-migration-2026-10-23/m4-kernels-review',sha256='b7143128a6959650bb4bc28d0b94c21e3a12d061627ecdfc40d81745762f644e')
ORIGINAL_ROOTS=dict(text=92,owners=2,selection=8,context=14,context_selection=1,ranking=5)
RUST_ROOTS=43
PYTHON_ROOTS=38
SCOPE='native request parsing, SQL scenario preparation and complete selection/ranking, before output serialization'

def verify_original(root:Path,repo:Path,system:str,fixture_repo:Path|None=None):
    fixture_repo=fixture_repo or repo
    mac=load(fixture_repo/'crates/ken-retrieval/tests/fixtures/search-selection-reference.json')['families']
    local=mac if system=='macos'else load(fixture_repo/'crates/ken-retrieval/tests/fixtures/search-selection-reference-linux.json')['families']
    cases=[];legacy=None
    for family in SUITES:
        base=root/family;value=load(base/'reference.json');fixture=local.get(family,mac[family])
        require(not validate_reference(value,family,fixture_repo)and value['owners']==owners(repo),'original selection family/owners differ: '+family)
        expected_runtime=dict(system='Darwin'if system=='macos'else'Linux',machine='arm64'if system=='macos'else'aarch64',python='3.12.9',unicode='15.0.0')
        if family not in('text','owners'):expected_runtime['numpy']='2.4.4'
        require(value['runtime']==expected_runtime,'original selection runtime differs: '+family)
        require((base/'capture.py').read_bytes()==SCRIPTS[family].encode()and value['script_sha256']==hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),'original observer changed: '+family)
        expected_files={'capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json','original-tests.xml'}
        require(set(value['execution']['files'])==expected_files and all(identity(base/name)==record for name,record in value['execution']['files'].items()),'raw original selection execution changed: '+family)
        require(load(base/'process-exit.json')==dict(exit=0),'original process exit differs')
        raw=load(base/'observations.json');require(all(same_value(value[k],v)for k,v in raw.items()),'raw original observations differ: '+family)
        request=load(base/'request.json');require(request['suite']==SUITES[family]and same_value(request['cases'],definitions(family,fixture_repo)),'original selection requests/suite differ: '+family)
        require(value['discovered']==fixture['discovered']and len(value['discovered'])==ORIGINAL_ROOTS[family],'original suite inventory differs: '+family)
        states=junit_states(base/'original-tests.xml');expected={p[:-3].replace('/','.')+'::'+n for p,n in(node.split('::',1)for node in value['discovered'])}
        require(set(states)==expected and set(states.values())=={'passed'},'actual original suite incomplete: '+family)
        require(same_value(value['cases'],fixture['cases']),'native fixture differs from its actual original platform: '+family)
        if family=='selection':legacy=value['legacy_runtime']
        # Captured inputs remain immutable, including repeated scenarios. The wire
        # identity names the occurrence as well as the original case identifier.
        cases.extend(dict(c,id=f'{family}/{i}/{c["id"]}')for i,c in enumerate(value['cases']))
    require(len(cases)==758 and len({c['id']for c in cases})==758,'complete disjoint original selection inventory required')
    return dict(cases=cases,legacy_runtime=legacy)

def verify_capture(out:Path,reference:dict,sources:dict|None=None,native_sha256:str|None=None,*,runtime_repo:Path|None=None):
    try:
        require(not verify_native_json(out,'ken-selection-native-'),'invalid actual selection process')
        build=load(out/'BUILD.json');execution=load(out/'execution.json');actual=load(out/'stdout.json')
        require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-selection-build/1'and build['sources']==load(out/'SOURCES.json'),'selection source provenance differs')
        if sources is not None:require(build['sources']==sources,'pinned selection sources differ')
        require(build['native_sha256']==execution['native_sha256'],'selection executable differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned selection executable differs')
        require(same_value(load(out/'inputs.json'),requests(reference)),'actual input inventory changed/contains answers')
        owned={'native-probe':execution['owned_before']['native-probe']}
        if execution['system']=='linux':
            runtime=runtime_manifest(runtime_repo or Path(__file__).resolve().parents[2],execution['machine']);files=runtime['files'];owned.update({'dense-blas/'+name:record for name,record in files.items()})
            require(str(Path(execution['cwd'])/'dense-blas'/runtime['library'])in(out/'stderr.log').read_text(),'isolated pinned dense runtime not loaded')
        require(execution['owned_before']==owned,'unexpected native selection resources')
        require(set(actual)=={'format','platform','cases','metrics'}and actual['platform']==execution['system'],'native selection platform/shape differs')
        metrics=actual['metrics'];require(set(metrics)=={'elapsed_s','max_rss_bytes','scope'}and metrics['scope']==SCOPE,'selection measurement scope differs')
        require(type(metrics['elapsed_s'])in(int,float)and math.isfinite(metrics['elapsed_s'])and metrics['elapsed_s']>=0 and type(metrics['max_rss_bytes'])is int and metrics['max_rss_bytes']>0,'selection timing/RSS invalid')
        require(not compare_observations(reference,actual),'complete native selection results differ');return []
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

def verify_gates(gates:Path):
    try:
        listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==RUST_ROOTS,'complete selection Rust roots required')
        found={p[:-3].replace('/','.')+'::'+n for p,n in re.findall(r'^(tests/rust_migration/test_selection_(?:reference|probe|validate|evidence)\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)};states=junit_states(gates/'python.xml')
        require(len(found)==PYTHON_ROOTS and set(states)==found and set(states.values())=={'passed'},'complete selection tooling roots required')
        log=(gates/'clippy.log').read_text();require('Finished `dev` profile'in log and'error:'not in log and'warning:'not in log,'selection clippy failed/missing')
        require((gates/'fmt.log').read_bytes()==b'','selection formatting failed');return []
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

def aggregate_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False):
    from .reference import verify_reference
    result=dict(passed=False,M4b_accepted=False,M4_accepted=False,migration_complete=False,errors=[])
    try:
        require(not _manifest_errors(directory),'selection evidence file manifest differs');index=load(directory/'INDEX.json')
        require(index['format']=='ken-selection-matrix/1'and index['predecessor']==PREDECESSOR,'selection predecessor differs')
        require(identity(repo/PREDECESSOR['path']/'FILES.json')['sha256']==PREDECESSOR['sha256']and not _manifest_errors(repo/PREDECESSOR['path']),'accepted M4a predecessor changed')
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'preserved1066originals changed')
        require(index['sources']==source_identity(snapshot/'native-sources'),'selection source snapshot differs')
        if current:require(index['sources']==source_identity(repo),'current selection sources differ')
        for name,expected in index['tooling'].items():require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'selection validation source differs')
        require(set(index['platforms'])=={'macos','linux'},'both actual selection platforms required')
        measurements={}
        for system in('macos','linux'):
            with tempfile.TemporaryDirectory(prefix='ken-selection-replay-')as temporary:
                raw=Path(temporary)
                with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
                reference=verify_original(raw/'original',repo,system,snapshot/'native-sources')
                require(not verify_capture(raw/'native',reference,index['sources'],index['platforms'][system]['native_sha256'],runtime_repo=snapshot/'native-sources'),'actual native selection proof differs')
                execution=load(raw/'native/execution.json');require((execution['system'],execution['machine'])==(system,'arm64'if system=='macos'else'aarch64'),'selection execution platform differs')
                require(not verify_gates(raw/'gates'),'complete selection gates differ')
                measurements[system]=load(raw/'native/stdout.json')['metrics']
        review=index['review'];require(review['status']in('pending','complete'),'selection review state differs')
        if review['status']=='complete':
            require(review['critical_remaining']==0 and review['important_remaining']==0 and identity(directory/'REVIEW.md')['sha256']==review['report_sha256'],'final selection review/fix evidence differs')
        result.update(passed=True,M4b_accepted=review['status']=='complete',per_platform=dict(Rust=RUST_ROOTS,Python=PYTHON_ROOTS,original_tests=sum(ORIGINAL_ROOTS.values()),cases=758),measurements=measurements)
    except(OSError,KeyError,TypeError,ValueError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
    return result

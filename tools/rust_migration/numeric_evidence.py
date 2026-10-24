"""Authenticate numerical originals, isolated native resources and complete gates."""
from __future__ import annotations
import hashlib,math,re,tarfile,tempfile
from pathlib import Path
from .index_validate import require,same_value
from .native_json import identity,load,tree,verify_native_json
from .numeric_reference import SCRIPTS,SUITES,REUSED_SUITE_PARENTS,definitions,validate_reference
from .numeric_validate import FORMAT,PREFIX,SCOPE,requests,compare_observations,source_identity
from .selection_reference import owners
from .retrieval_validate import runtime_manifest
from .receipts import junit_states
from .integration_validate import _manifest_errors,rust_gate_errors
from .retrieval_reference import digest
PREDECESSOR=dict(path='docs/validation/rust-migration-2026-10-23/m4-selection-review',sha256='502522eb0af6e3136be30114c5509314593785e94604ff1c70303f721a33a10b')
COUNTS={'forest':318,'forest-edges':28,'stems':74,'alignment':245,'alignment-edges':22,'features':76,'features-edges':7,'features-math-edges':3,'owner-ranking':70,'production':16,'production-paths':2}
ORIGINAL_ROOTS={'forest':4,'stems':5,'alignment':2,'features':11,'owner-ranking':12,'production':1}
RUST_ROOTS=80
def expected_owners(repo,family):
    expected=owners(repo)
    if family=='production':
        for name in ['src/ken/embedder/static_head.py','src/ken/embedder/data/ken__static-qwen3-r512-v2.npz']:expected[name]=identity(repo/name)['sha256']
    return expected
def suite(base,value):
    states=junit_states(base/'original-tests.xml');expected={p[:-3].replace('/','.')+'::'+n for p,n in(node.split('::',1)for node in value['discovered'])}
    require(set(states)==expected and set(states.values())=={'passed'},'actual original numeric tests incomplete/skipped')
def raw_original(base,value):
    files=value['execution']['files'];required={'capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json'}
    if 'reused_suite'not in value:required.add('original-tests.xml')
    require(set(files)==required and all(identity(base/name)==record for name,record in files.items()),'raw original numeric execution changed')
    require(load(base/'process-exit.json')==dict(exit=0),'original numeric process failed')
    observed=load(base/'observations.json');require(all(same_value(value[k],v)for k,v in observed.items()),'raw original numeric results differ')
    return load(base/'request.json')
def verify_original(root:Path,repo:Path,system:str,fixture_repo:Path|None=None):
    fixture_repo=fixture_repo or repo;cases=[]
    for family in SCRIPTS:
        base=root/family;value=load(base/'reference.json')
        fixture=fixture_repo/f'crates/ken-retrieval/tests/fixtures/numeric-reference-{family}{"-linux"if system=="linux"else""}.json'
        if not fixture.exists():fixture=fixture_repo/f'crates/ken-retrieval/tests/fixtures/numeric-reference-{family}.json'
        fixture=load(fixture)
        require(not validate_reference(value,family,fixture_repo)and value['owners']==expected_owners(repo,family),'original numeric family/owners differ: '+family)
        runtime=dict(system='Darwin'if system=='macos'else'Linux',machine='arm64'if system=='macos'else'aarch64',python='3.12.9',unicode='15.0.0')
        runtime['snowball'if family=='stems'else'numpy']='3.0.1'if family=='stems'else'2.4.4'
        require(value['runtime']==runtime,'original numeric runtime differs: '+family)
        require((base/'capture.py').read_bytes()==SCRIPTS[family].encode(),'original numeric observer changed: '+family)
        request=raw_original(base,value)
        require(same_value(request['cases'],definitions(family,fixture_repo))and request['family']==family and request.get('suite',[])==SUITES.get(family,[]),'original numeric request inventory differs: '+family)
        require(len(value['cases'])==COUNTS[family]and same_value(value['cases'],fixture['cases'])and value['discovered']==fixture['discovered'],'numeric original fixture differs from actual platform: '+family)
        parent=REUSED_SUITE_PARENTS.get(family)
        if family=='production'and system=='macos':parent='production-prior-suite'
        if parent:
            previous=load(root/parent/'reference.json');pin=value['reused_suite'];path_matches=request['cached_suite']==pin['path']
            if family=='forest-edges'and not Path(pin['path']).is_absolute():path_matches=tuple(Path(request['cached_suite']).parts[-len(Path(pin['path']).parts):])==Path(pin['path']).parts
            require(pin['sha256']==identity(root/parent/'reference.json')['sha256']and path_matches,'original numeric reused suite binding differs')
            require(value['discovered']==previous['discovered']and value['test_states']==previous['test_states']and len(value['discovered'])==ORIGINAL_ROOTS['production'if parent=='production-prior-suite'else parent],'reused original test inventory differs')
            if parent=='production-prior-suite':
                require(fixture['reused_suite']['sha256']==pin['sha256']and previous['owners']==expected_owners(repo,'production')and previous['corpus_sha256']==digest(previous['cases']),'invalid prior production suite provenance')
                raw_original(root/parent,previous);require(identity(root/parent/'capture.py')['sha256']==previous['script_sha256'],'prior production observer differs');suite(root/parent,previous)
        else:
            require(len(value['discovered'])==ORIGINAL_ROOTS[family],'original numeric scoped test inventory differs');suite(base,value)
        if family=='stems':
            from .snowball_provenance import validate_original,SCRIPT as STEM_DEPENDENCY_SCRIPT
            dependency=load(base/'SNOWBALL-REFERENCE.json');require(not validate_original(dependency)and dependency['runtime']==dict(system=runtime['system'],machine=runtime['machine']),'original Snowball dependency differs')
            require((base/'snowball-capture.py').read_bytes()==STEM_DEPENDENCY_SCRIPT.encode()and dependency['execution']['exit']==0 and all(identity(base/name)==record for name,record in dependency['execution']['files'].items()),'actual Snowball dependency capture differs')
        cases.extend(dict(c,id=f'{family}/{i}/{c["id"]}',family=family)for i,c in enumerate(value['cases']))
    require(len(cases)==861 and len({c['id']for c in cases})==861,'complete numeric original inventory required')
    return dict(cases=cases)
def verify_capture(out:Path,reference:dict,sources:dict|None=None,native_sha256:str|None=None,*,runtime_repo:Path|None=None):
    try:
        repo=runtime_repo or Path(__file__).resolve().parents[2]
        require(not verify_native_json(out,PREFIX),'invalid actual numeric process')
        build=load(out/'BUILD.json');execution=load(out/'execution.json');actual=load(out/'stdout.json')
        require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-numeric-build/1'and build['sources']==load(out/'SOURCES.json'),'numeric source provenance differs')
        if sources is not None:require(build['sources']==sources,'pinned numeric sources differ')
        require(build['native_sha256']==execution['native_sha256'],'numeric executable differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned numeric executable differs')
        require(same_value(load(out/'inputs.json'),requests(reference,dict(ranking='ranking',static='static.npz'))),'actual numeric inputs changed/contain answers')
        owned={'native-probe':execution['owned_before']['native-probe'],'static.npz':identity(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz')}
        owned.update({'ranking/'+name:record for name,record in tree(repo/'crates/ken-retrieval/resources/ranking').items()})
        if execution['system']=='linux':
            runtime=runtime_manifest(repo,execution['machine'])
            owned.update({'dense-blas/'+name:record for name,record in runtime['files'].items()})
            require(str(Path(execution['cwd'])/'dense-blas'/runtime['library'])in(out/'stderr.log').read_text(),'isolated pinned numeric BLAS not loaded')
        require(execution['owned_before']==owned,'unexpected or stale numeric resources/runtime')
        require(set(actual)=={'format','platform','cases','metrics'}and actual['platform']==execution['system'],'numeric native platform/shape differs')
        metrics=actual['metrics'];require(set(metrics)=={'elapsed_s','max_rss_bytes','scope'}and metrics['scope']==SCOPE,'numeric measurement scope differs')
        require(type(metrics['elapsed_s'])in(int,float)and math.isfinite(metrics['elapsed_s'])and metrics['elapsed_s']>=0 and type(metrics['max_rss_bytes'])is int and metrics['max_rss_bytes']>0,'numeric timing/RSS invalid')
        require(not compare_observations(reference,actual),'complete numeric native results/calls differ');return[]
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

PYTHON_ROOTS=92
TEST_FILES=['tests/rust_migration/test_'+name+'.py'for name in ['numeric_reference','numeric_validate','numeric_probe','numeric_evidence','selection_reference','selection_validate','selection_probe','selection_evidence','snowball_provenance']]
def verify_gates(gates:Path):
    try:
        listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==RUST_ROOTS,'complete numeric Rust roots required')
        found=[]
        for line in(gates/'python-list.log').read_text().splitlines():
            if not any(line.startswith(name+'::')for name in TEST_FILES):continue
            p,n=line.split('::',1);found.append(p[:-3].replace('/','.')+'::'+n)
        states=junit_states(gates/'python.xml')
        require(len(found)==len(set(found))==PYTHON_ROOTS and set(states)==set(found)and set(states.values())=={'passed'},'complete numeric tooling roots required')
        log=(gates/'clippy.log').read_text();require('Finished `dev` profile'in log and'error:'not in log and'warning:'not in log,'numeric clippy failed/missing')
        require((gates/'fmt.log').read_bytes()==b'','numeric formatting failed');return[]
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

def aggregate_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False):
    from .reference import verify_reference
    from .selection_evidence import verify_original as selection_original,verify_capture as selection_capture
    result=dict(passed=False,M4c1_accepted=False,M4_accepted=False,migration_complete=False,errors=[])
    try:
        require(not _manifest_errors(directory),'numeric evidence file manifest differs');index=load(directory/'INDEX.json')
        require(index['format']=='ken-numeric-matrix/1'and index['predecessor']==PREDECESSOR,'numeric predecessor differs')
        require(identity(repo/PREDECESSOR['path']/'FILES.json')['sha256']==PREDECESSOR['sha256']and not _manifest_errors(repo/PREDECESSOR['path']),'accepted M4b predecessor changed')
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'preserved1066originals changed')
        native=snapshot/'native-sources';require(index['sources']==source_identity(native),'numeric source snapshot differs')
        if current:require(index['sources']==source_identity(repo),'current numeric sources differ')
        for name,expected in index['tooling'].items():require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'numeric validation source differs')
        require(set(index['platforms'])=={'macos','linux'},'both actual numeric platforms required')
        measurements={}
        for system in('macos','linux'):
            with tempfile.TemporaryDirectory(prefix='ken-numeric-replay-')as temporary:
                raw=Path(temporary)
                with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
                reference=verify_original(raw/'original',repo,system,native)
                require(not verify_capture(raw/'native',reference,index['sources'],index['platforms'][system]['native_sha256'],runtime_repo=native),'actual numeric native proof differs')
                execution=load(raw/'native/execution.json');require((execution['system'],execution['machine'])==(system,'arm64'if system=='macos'else'aarch64'),'numeric execution platform differs')
                require(not verify_gates(raw/'gates'),'complete numeric gates differ')
                old=selection_original(raw/'selection-original',repo,system,native)
                require(not selection_capture(raw/'selection-native',old,index['sources'],index['platforms'][system]['selection_sha256'],runtime_repo=native),'previous selection observations regressed')
                measurements[system]=load(raw/'native/stdout.json')['metrics']
        review=index['review'];require(review['status']in('pending','complete'),'numeric review state differs')
        if review['status']=='complete':require(review['critical_remaining']==0 and review['important_remaining']==0 and identity(directory/'REVIEW.md')['sha256']==review['report_sha256'],'numeric final review/fix evidence differs')
        result.update(passed=True,M4c1_accepted=review['status']=='complete',per_platform=dict(Rust=RUST_ROOTS,Python=PYTHON_ROOTS,original_tests=sum(ORIGINAL_ROOTS.values()),cases=861,previous_selection_cases=758,differential_cases=854,source_admission_contracts=7),measurements=measurements)
    except(OSError,KeyError,TypeError,ValueError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
    return result

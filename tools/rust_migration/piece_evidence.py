"""Authenticate original source pieces, native process records and full gates."""
from __future__ import annotations
import json,math,re
from pathlib import Path
from .index_validate import require,same_value,source_identity
from .native_json import identity,load,tree,verify_native_json
from .piece_reference import SCRIPTS,SUITES,definitions,validate_reference
from .piece_validate import FORMAT,PREFIX,SCOPE,requests,compare_observations
from .numeric_evidence import raw_original,suite
from .receipts import junit_states
from .retrieval_validate import runtime_manifest
from .selection_reference import owners
from .integration_validate import rust_gate_errors
COUNTS={'catalog':38,'assembly':45,'ranking':84,'ranking-edges':13,'ranking-empty-declaration':1,'cards':60,'evidence':86,'evidence-edges':2,'presentation':117}
# Root discovery excludes the health test's nested child-harness execution.
NATIVE_ROOTS={'Linux':126,'Darwin':125}
ROOTS={'catalog':4,'assembly':3,'ranking':9,'cards':3,'evidence':19,'presentation':9}
PARENTS={'ranking-edges':'ranking','ranking-empty-declaration':'ranking','evidence-edges':'evidence'}
PREDECESSOR=dict(path='docs/validation/rust-migration-2026-10-23/m4-numeric-owner',sha256='9058d60199da6ef080991203bf0b6351361a5c27c2d5e6358bf31c3f3e4d1a6e')
def relative(name):
    path=Path(name)
    require(not path.is_absolute()and path.parts and all(p not in('.','..')for p in path.parts),'unsafe piece evidence path')
    return path
def normalized(reference):return dict(reference,cases=[dict(c,family=reference['family'])for c in reference['cases']])
def checked_suite(base,value,packet,family,seen=None):
    seen=set()if seen is None else seen
    fingerprint=identity(base/'reference.json')['sha256'];require(fingerprint not in seen,'cyclic reused piece suite');seen.add(fingerprint)
    require(len(value['discovered'])==ROOTS[family],'original scoped piece test count differs')
    if'reused_suite'not in value:
        suite(base,value);return
    pin=value['reused_suite'];request=load(base/'request.json')
    require(request['cached_suite']==pin['path'],'reused piece suite request differs')
    candidates=[p.parent for p in(packet/'originals').rglob('reference.json')if identity(p)['sha256']==pin['sha256']]
    require(candidates,'reused piece suite predecessor missing');previous_base=candidates[0];previous=load(previous_base/'reference.json')
    prior_request=raw_original(previous_base,previous)
    require(previous['owners']==value['owners']and prior_request['suite']==SUITES[family]and previous['runtime']==value['runtime'],'reused piece suite source/runtime differs')
    require(identity(previous_base/'capture.py')['sha256']==previous['script_sha256'],'reused piece observer identity differs')
    require(value['discovered']==previous['discovered']and value['test_states']==previous['test_states'],'reused original discovery differs')
    checked_suite(previous_base,previous,packet,family,seen)
def verify_capture(out:Path,reference:dict,*,repo:Path,sources:dict|None=None,native_sha256:str|None=None):
    try:
        require(not verify_native_json(out,PREFIX),'invalid actual source-piece process')
        build=load(out/'BUILD.json');execution=load(out/'execution.json');actual=load(out/'stdout.json')
        require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-piece-build/1'and build['sources']==load(out/'SOURCES.json'),'piece source provenance differs')
        if sources is not None:require(build['sources']==sources,'pinned piece sources differ')
        require(build['native_sha256']==execution['native_sha256'],'piece executable binding differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned piece executable differs')
        require(same_value(load(out/'inputs.json'),requests(reference,dict(ranking='ranking',static='static.npz'))),'piece actual inputs changed/contain answers')
        owned={'native-probe':execution['owned_before']['native-probe'],'static.npz':identity(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz')}
        owned.update({'ranking/'+name:record for name,record in tree(repo/'crates/ken-retrieval/resources/ranking').items()})
        if execution['system']=='linux':
            manifest=runtime_manifest(repo,execution['machine']);owned.update({'dense-blas/'+name:record for name,record in manifest['files'].items()})
            # Source-only families legitimately never enter BLAS. Numeric piece
            # families must load the authenticated copy inside the owned runtime.
            if reference['family'].startswith('ranking'):
                require(str(Path(execution['cwd'])/'dense-blas'/manifest['library'])in(out/'stderr.log').read_text(),'isolated pinned piece BLAS not loaded')
        require(execution['owned_before']==owned,'unexpected or stale piece runtime resources')
        require(actual['platform']==execution['system']and actual['machine']==execution['machine'],'piece execution architecture differs')
        require(not compare_observations(normalized(reference),actual),'complete piece results/calls differ')
        return[]
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]
def original_references(packet:Path,repo:Path):
    preparation=load(packet/'PREPARATION.json');system=preparation['runtime']['system'];machine=preparation['runtime']['machine'];references={};bases={}
    require((system,machine)in{('Darwin','arm64'),('Linux','aarch64')},'actual two-ARM original platforms required')
    require(preparation['M4c2_accepted']is False and preparation['M4_accepted']is False and preparation['migration_complete']is False,'preparation cannot claim acceptance')
    capsule=repo/'docs/validation/rust-migration-2026-10-23/handoff/PORTABLE.json'
    require(identity(capsule)==preparation['capsule'],'portable original capsule differs')
    for row in load(capsule)['sdd_files']:
        require(identity(packet/'originals/preserved-progress'/relative(row['path']))=={k:row[k]for k in('bytes','sha256')},'preserved original suite capsule changed')
    for name,record in preparation['files'].items():require(identity(packet/'originals'/relative(name))==record,'original piece file inventory changed')
    for family,count in COUNTS.items():
        row=preparation['originals'][family];name=Path(row['path']).relative_to('.ken/rust-migration/piece-platform');base=packet/relative(str(name));value=load(base/'reference.json');bases[family]=base
        require(identity(base/'reference.json')==row['reference']and row['cases']==count,'original piece reference binding differs')
        require(not validate_reference(value,family,repo)and len(value['cases'])==count,'original piece definition/observer differs: '+family)
        require(value['owners']==owners(repo),'original piece owners differ')
        require(value['runtime']['system']==system and value['runtime']['machine']==machine and value['runtime']['python']=='3.12.9'and value['runtime']['unicode']=='15.0.0','original piece runtime differs')
        if'numpy'in value['runtime']:require(value['runtime']['numpy']=='2.4.4','original piece NumPy differs')
        require((base/'capture.py').read_bytes()==SCRIPTS[family].encode(),'original piece observer bytes differ')
        request=raw_original(base,value)
        require(request['family']==family and same_value(request['cases'],definitions(family,repo))and request['suite']==SUITES[family],'original piece actual requests differ')
        if family not in PARENTS:
            checked_suite(base,value,packet,family)
        references[family]=value
    for family,parent in PARENTS.items():
        value=references[family];prior=references[parent];base=bases[family];request=load(base/'request.json')
        require(value['reused_suite']['sha256']==identity(bases[parent]/'reference.json')['sha256']and request['cached_suite']==value['reused_suite']['path'],'reused piece suite binding differs')
        require(value['discovered']==prior['discovered']and value['test_states']==prior['test_states'],'reused original piece discovery differs')
    require(sum(len(v['cases'])for v in references.values())==446,'complete source-piece original inventory required')
    return references
TEST_NAMES=['portable_reference','reference','numeric_evidence','numeric_reference','dense_runtime','translation_build','piece_reference','retrieval_validate','retrieval_evidence','selection_evidence','piece_validate','piece_probe','piece_evidence']
TEST_FILES=['tests/rust_migration/test_'+name+'.py'for name in TEST_NAMES]
LINT_COMMANDS={
    'fmt':['cargo','fmt','--all','--check'],
    'clippy':['cargo','clippy','--locked','--offline','-p','ken-core','-p','ken-retrieval','--all-targets','--','-D','warnings'],
}
def run_lint_gates(gates:Path):
    from .command_gates import run_lint_gates as run
    run(gates,LINT_COMMANDS)

def verify_gates(gates:Path,*,rust_roots:int,python_roots:int):
    try:
        listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==rust_roots,'complete piece Rust roots required')
        discovered=[]
        for line in(gates/'python-list.log').read_text().splitlines():
            if any(line.startswith(name+'::')for name in TEST_FILES):
                path,node=line.split('::',1);discovered.append(path[:-3].replace('/','.')+'::'+node)
        states=junit_states(gates/'python.xml')
        require(len(discovered)==python_roots and len(set(discovered))==python_roots and set(discovered)==set(states)and set(states.values())=={'passed'},'complete piece tooling roots required')
        from .command_gates import lint_gate_errors
        require(not lint_gate_errors(gates,LINT_COMMANDS),'piece format/lint receipt failed')
        return[]
    except(OSError,KeyError,TypeError,ValueError)as error:return[str(error)]
def verify_snapshot(packet:Path,snapshot:Path):
    """Check a previously extracted safe snapshot against its immutable inventory."""
    expected=load(packet/'SNAPSHOT.json')
    for name,record in expected.items():require(identity(snapshot/relative(name))==record,'piece archived source/tooling differs: '+name)
    require(source_identity(snapshot)==load(packet/'SOURCES.json'),'piece archived Rust source inventory differs')
    validation=load(packet/'VALIDATION-SOURCES.json')
    require(validation and all(expected.get(name)==record for name,record in validation.items()),'piece validator snapshot missing')
    require(identity(snapshot/PREDECESSOR['path']/'FILES.json')['sha256']==PREDECESSOR['sha256'],'accepted M4c1 predecessor differs')
def verify_platform(packet:Path,repo:Path):
    """Replay all source-piece observations and full gates, without claiming M4."""
    try:
        preparation=load(packet/'PREPARATION.json');references=original_references(packet,repo);sources=load(packet/'SOURCES.json')
        require(sources==source_identity(repo),'piece acceptance source snapshot differs')
        binary=identity(packet/'bin/source_piece_probe');require(binary==load(packet/'PROBE.json'),'piece archived executable differs')
        for family in COUNTS:
            errors=verify_capture(packet/'native'/family,references[family],repo=repo,sources=sources,native_sha256=binary['sha256'])
            require(not errors,family+': '+str(errors))
        system=preparation['runtime']['system'];require(not verify_gates(packet/'gates',rust_roots=NATIVE_ROOTS[system],python_roots=174),'complete source-piece gates failed')
        return[]
    except(OSError,KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]
def aggregate_matrix(directory:Path,repo:Path,*,review:Path|None=None):
    reports=[]
    for name,system,machine in [('source-pieces-Linux-ARM64','Linux','aarch64'),('source-pieces-macOS-ARM64','Darwin','arm64')]:
        packet=directory/name;preparation=load(packet/'PREPARATION.json')
        require((preparation['runtime']['system'],preparation['runtime']['machine'])==(system,machine),'actual source-piece platform missing')
        errors=verify_platform(packet,repo);require(not errors,str(errors))
        reports.append(dict(system=system,machine=machine,commit=preparation['commit'],sources=load(packet/'SOURCES.json'),native=identity(packet/'bin/source_piece_probe')))
    require(reports[0]['commit']==reports[1]['commit']and reports[0]['sources']==reports[1]['sources'],'source-piece platforms ran different candidate sources')
    accepted=False
    if review is not None:
        record=load(review)
        require(record['format']=='ken-source-piece-review/1'and record['whole_plan']is True and record['critical_open']==[]and record['important_open']==[],'whole-plan review still has blocking findings')
        require(record['accepted_sources']==reports[0]['sources']and isinstance(record['reviewer'],str)and record['reviewer'],'review is not bound to accepted sources')
        require(identity(review.parent/relative(record['raw_review']['path']))==record['raw_review']['identity'],'raw final review changed')
        accepted=True
    return dict(format='ken-source-piece-acceptance/1',platforms=reports,cases_per_platform=446,differentials_per_platform=433,explicit_source_guards_per_platform=13,predecessor=PREDECESSOR,M4c2_accepted=accepted,M4_accepted=False,migration_complete=False)
def extract_snapshot(packet:Path,destination:Path):
    from .native_snapshot import extract_source_snapshot
    required=dict(load(packet/'SOURCES.json'));required.update(load(packet/'VALIDATION-SOURCES.json'))
    extract_source_snapshot(packet,destination,required=required)
    verify_snapshot(packet,destination)
    return destination

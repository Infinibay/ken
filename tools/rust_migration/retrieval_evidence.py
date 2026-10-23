"""Authenticate actual original/native kernels and complete affected platform gates."""
from __future__ import annotations
import hashlib,json,math,re,tarfile,tempfile
from pathlib import Path
from .native_json import identity,load,verify_native_json
from .retrieval_reference import SCRIPT,definitions,owners,validate_reference
from .retrieval_validate import FORMAT,requests,compare_observations,source_identity,ERROR_KINDS
from .index_validate import same_value,require
from .integration_validate import _manifest_errors,rust_gate_errors
from .receipts import junit_states
PREDECESSOR=dict(path='docs/validation/rust-migration-2026-10-23/m3-index-review',sha256='5216c937b4537dd940f3d43c71181e7ce44c4b2987b53d6e6d2699877f7414a9')
RUST_ROOTS=41
PYTHON_ROOTS=40

def verify_capture(out:Path,reference:dict,sources:dict|None=None,native_sha256:str|None=None)->list[str]:
    try:
        require(not validate_reference(reference),'invalid original kernel reference')
        require(not verify_native_json(out,'ken-retrieval-native-'),'invalid actual native kernel execution')
        build=load(out/'BUILD.json');execution=load(out/'execution.json');actual=load(out/'stdout.json')
        require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-retrieval-build/1'and build['sources']==load(out/'SOURCES.json'),'native retrieval source inputs differ')
        if sources is not None:require(build['sources']==sources,'pinned retrieval sources differ')
        require(build['native_sha256']==execution['native_sha256'],'retrieval executable differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned retrieval executable differs')
        require(same_value(load(out/'inputs.json'),requests(reference['cases'])),'actual retrieval input inventory rewritten/contains answers')
        require(execution['owned_before']=={'native-probe':execution['owned_before']['native-probe']},'unexpected native retrieval resource')
        require(set(actual)=={'format','platform','cases','metrics'}and actual['platform']==execution['system'],'native retrieval platform/shape differs')
        metrics=actual['metrics'];require(set(metrics)=={'elapsed_s','max_rss_bytes','scope'}and metrics['scope']=='native request parsing and all kernels, before output serialization','kernel measurement scope differs')
        require(type(metrics['elapsed_s'])in(int,float)and math.isfinite(metrics['elapsed_s'])and metrics['elapsed_s']>=0 and type(metrics['max_rss_bytes'])is int and metrics['max_rss_bytes']>0,'invalid kernel timing/RSS')
        errors=compare_observations(reference,actual);require(not errors,'; '.join(errors));return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_gates(gates:Path)->list[str]:
    try:
        listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==RUST_ROOTS,'complete affected kernel Rust roots required')
        discovered={p[:-3].replace('/','.')+'::'+n for p,n in re.findall(r'^(tests/rust_migration/test_retrieval_(?:reference|probe|validate|evidence)\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)};states=junit_states(gates/'python.xml')
        require(len(discovered)==PYTHON_ROOTS and set(states)==discovered and set(states.values())=={'passed'},'complete kernel tooling inventory/execution required')
        clippy=(gates/'clippy.log').read_text();require('Finished `dev` profile'in clippy and'error:'not in clippy and'warning:'not in clippy,'affected kernel clippy failed/missing')
        require((gates/'fmt.log').read_bytes()==b'','kernel format check failed');return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_original(root:Path,repo:Path,system:str,fixture_repo:Path|None=None)->dict:
    value=load(root/'reference.json');require(not validate_reference(value)and value['owners']==owners(repo),'original kernel observations/owners differ')
    require(value['runtime']==dict(system='Darwin'if system=='macos'else'Linux',machine='arm64'if system=='macos'else'aarch64',python='3.12.9',numpy='2.4.4'),'original kernel platform differs')
    require((root/'capture.py').read_bytes()==SCRIPT.encode()and value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'original kernel observer changed')
    for name,key in [('stdout.log','stdout_sha256'),('stderr.log','stderr_sha256'),('observations.json','observations_sha256')]:require(identity(root/name)['sha256']==value['execution'][key],'raw original kernel execution bytes differ')
    require(all(same_value(value[k],v)for k,v in load(root/'observations.json').items()),'actual original kernel observations differ')
    require(same_value(load(root/'request.json')['cases'],definitions()),'actual original kernel inputs differ')
    expected={p[:-3].replace('/','.')+'::'+n for p,n in(node.split('::',1)for node in value['discovered'])};states=junit_states(root/'original-tests.xml')
    require(len(expected)==13 and set(states)==expected and set(states.values())=={'passed'},'actual original kernel suites incomplete')
    fixture=load((fixture_repo or repo)/'crates/ken-retrieval/tests/fixtures/kernel-reference.json')
    require(fixture['owners']==value['owners']and not validate_reference(fixture),'native kernel fixture provenance differs')
    records=[]
    for expected,observed in zip(fixture['cases'],value['cases'],strict=True):
        record={k:v for k,v in observed.items()if k!='input'}
        if 'error'in record:
            require(expected.get('error',{}).get('type')==record['error']['type'],'original kernel failure class changed')
            record['error']=dict(kind=ERROR_KINDS[record['error']['type']],message=record['error']['message'])
        records.append(record)
    comparable=dict(format=FORMAT,cases=records)
    require(not compare_observations(fixture,comparable),'actual original kernel cases differ from native fixture')
    return value

def aggregate_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False)->dict:
    from .reference import verify_reference
    result=dict(passed=False,M4a_accepted=False,M4_accepted=False,migration_complete=False,errors=[])
    try:
        require(not _manifest_errors(directory),'retrieval evidence file manifest differs');index=load(directory/'INDEX.json')
        require(index['format']=='ken-retrieval-kernel-matrix/1'and index['predecessor']==PREDECESSOR,'kernel matrix/predecessor differs')
        require(identity(repo/PREDECESSOR['path']/'FILES.json')['sha256']==PREDECESSOR['sha256']and not _manifest_errors(repo/PREDECESSOR['path']),'accepted M3 source-index predecessor changed')
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'preserved1066originals changed')
        require(index['sources']==source_identity(snapshot/'native-sources'),'retrieval source snapshot differs')
        if current:require(index['sources']==source_identity(repo),'current retrieval sources differ')
        for name,expected in index['tooling'].items():require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'retrieval validation source differs')
        require(set(index['platforms'])=={'macos','linux'},'both actual native kernel platforms required')
        for system in ('macos','linux'):
            platform=index['platforms'][system]
            with tempfile.TemporaryDirectory(prefix='ken-retrieval-replay-')as temporary:
                raw=Path(temporary)
                with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
                original=verify_original(raw/'original',repo,system,snapshot/'native-sources')
                require(not verify_capture(raw/'native',original,index['sources'],platform['native_sha256']),'actual native kernel results/provenance differ')
                execution=load(raw/'native/execution.json');require((execution['system'],execution['machine'])==(system,'arm64'if system=='macos'else'aarch64'),'actual native kernel platform differs')
                require(not verify_gates(raw/'gates'),'complete affected kernel gates differ')
        result.update(passed=True,M4a_accepted=True,per_platform=dict(Rust=RUST_ROOTS,Python=PYTHON_ROOTS,original_tests=13,kernel_cases=292))
    except(OSError,ValueError,KeyError,TypeError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
    return result

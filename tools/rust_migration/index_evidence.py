"""Authenticate native indexing, original observations and complete affected gates."""
from __future__ import annotations
import copy,hashlib,json,math,re,tarfile,tempfile
from pathlib import Path
from .native_json import identity,load,verify_native_json
from .index_validate import compare_scenarios,requests,source_identity,require,same_value,close_vectors,f32_blob
from .index_scenarios import validate_scenario_reference,scenario_definitions
from .integration_validate import rust_gate_errors,_manifest_errors
from .receipts import junit_states

PREDECESSOR=dict(path='docs/validation/rust-migration-2026-10-23/m3-program-review',sha256='20737c5dced1e23df625b2a1c1220536c0f9b9bdb38354b51094daf6bdc0f461')
TOOLING_TESTS=43

def verify_index_capture(out:Path,reference:dict,sources:dict|None=None,native_sha256:str|None=None)->list[str]:
    try:
        require(not validate_scenario_reference(reference),'invalid original indexing reference')
        require(not verify_native_json(out,'ken-index-native-'),'invalid actual native execution')
        build=load(out/'BUILD.json');execution=load(out/'execution.json');inputs=load(out/'inputs.json');actual=load(out/'stdout.json')
        require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-index-build/1'and build['sources']==load(out/'SOURCES.json'),'native indexing source inputs differ')
        if sources is not None:require(build['sources']==sources,'pinned indexing source snapshot differs')
        require(build['native_sha256']==execution['native_sha256'],'native indexing executable differs')
        if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned native indexing executable differs')
        require(same_value(inputs,requests(reference['definitions'],inputs['legacy_runtime'],Path(inputs['grammar_manifest']))),'native indexing request rewritten/contains expectations')
        require(execution['owned_before']=={'native-probe':execution['owned_before']['native-probe']},'unexpected native indexing resource')
        require(set(actual)=={'format','platform','cases','metrics'}and actual['platform']==execution['system'],'native indexing platform/output shape differs')
        metrics=actual['metrics'];require(set(metrics)=={'elapsed_s','max_rss_bytes','scope'},'indexing measurements incomplete')
        require(type(metrics['elapsed_s'])in(int,float)and math.isfinite(metrics['elapsed_s'])and metrics['elapsed_s']>=0 and type(metrics['max_rss_bytes'])is int and metrics['max_rss_bytes']>0,'invalid native indexing timing/RSS')
        require(metrics['scope']=='whole native process, all requested histories and grammar caches','indexing measurement scope differs')
        require(not compare_scenarios(reference,actual),'native indexing results or side effects differ');return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_index_gates(gates:Path)->list[str]:
    try:
        listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==43,'complete43affected Rust roots required')
        discovery={path[:-3].replace('/','.')+'::'+name for path,name in re.findall(r'^(tests/rust_migration/test_index_(?:reference|validate|probe|evidence)\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)};states=junit_states(gates/'python.xml')
        require(len(discovery)==TOOLING_TESTS and set(states)==discovery and set(states.values())=={'passed'},'complete affected tooling inventory/execution required')
        clippy=(gates/'clippy.log').read_text();require('Finished `dev` profile'in clippy and'error:'not in clippy and'warning:'not in clippy,'affected clippy failed/missing')
        require((gates/'fmt.log').read_bytes()==b'','affected format check failed');return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_original_capture(root:Path,snapshot:Path,repo:Path,system:str)->dict:
    from .index_reference import SOURCE_SCRIPT,STORAGE_SCRIPT,PUBLICATION_SCRIPT,PROJECTION_SCRIPT,SOURCE_SUITE
    from .index_scenarios import SCRIPT,HISTORY_SCRIPT,INITIAL_SCRIPT,SUITE
    baseline=load(repo/'docs/validation/rust-migration-2026-10-18/baseline.json');expected_system='Darwin'if system=='macos'else'Linux'
    source_owners={r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/retrieval/','src/ken/nametokens.py','src/ken/parsers/'))or r['path']in SOURCE_SUITE+['tests/conftest.py']}
    scenario_owners={r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/retrieval/','src/ken/indexer.py','src/ken/nametokens.py','src/ken/db.py','src/ken/schema.sql','src/ken/parsers/'))or r['path']in SUITE+['tests/conftest.py']}
    values={}
    for name,script,prefix in [('source',SOURCE_SCRIPT,''),('storage',STORAGE_SCRIPT,'storage-'),('publication',PUBLICATION_SCRIPT,'publication-'),('projection',PROJECTION_SCRIPT,'projection-')]:
        value=load(root/(name+'-reference.json'));values[name]=value
        require(value['format']==f'ken-index-{name}-reference/1'and value['runtime']['system']==expected_system and value['runtime']['python']=='3.12.9','original indexing boundary/platform differs')
        require(value['script_sha256']==hashlib.sha256(script.encode()).hexdigest()and (root/(prefix+'capture.py')).read_bytes()==script.encode(),'original boundary observer changed')
        require(value['execution']['exit']==0,'original boundary execution failed')
        for suffix,key in [('stdout','stdout_sha256'),('stderr','stderr_sha256')]:require(identity(root/(prefix+suffix))['sha256']==value['execution'][key],'raw original boundary output changed')
    source=values['source'];require(source['owners']==source_owners and source['original_test_exit']==0 and len(source['vocabulary'])==195 and len(source['passages'])==496 and source['unicode_version']=='15.0.0','original vocabulary/passages/owners incomplete')
    require(source['runtime']['machine']=='arm64'if system=='macos'else source['runtime']['machine']=='aarch64','original source machine differs')
    for value,xml,count in [(source,root/'original-source.xml',22)]:_verify_original_tests(value,xml,count)
    require(len(values['storage']['cases'])==26 and len(values['publication']['cases'])==31 and len(values['publication']['intents'])==18 and len(values['projection']['cases'])==93,'original storage/publication/projection inventory incomplete')
    for name,parent in [('storage','source'),('publication','source'),('projection','publication')]:require(values[name]['source_sha256']==identity(root/(parent+'-reference.json'))['sha256'],'original boundary dependency changed')
    fixture_paths={'source':'crates/ken-retrieval/tests/fixtures/source-reference.json','storage':'crates/ken-retrieval/tests/fixtures/storage-reference.json','publication':'crates/ken-index/tests/fixtures/publication-reference.json','projection':'crates/ken-retrieval/tests/fixtures/projection-reference.json'}
    for name,path in fixture_paths.items():
        fixture=load(snapshot/path);value=values[name]
        for key in ('vocabulary','passages','casefold','cases','intents'):
            if key in value:
                left=copy.deepcopy(value[key]);right=copy.deepcopy(fixture[key])
                if name=='projection'and key=='cases':
                    require(len(left)==len(right),'original projection inventory changed')
                    for a,b in zip(left,right,strict=True):
                        x=a['result']['tables']['ci_retrieval_embeddings'];y=b['result']['tables']['ci_retrieval_embeddings'];require(len(x)==len(y),'original projection artifact inventory differs')
                        for u,v in zip(x,y,strict=True):close_vectors(f32_blob(u[5]),f32_blob(v[5]));u[5]=v[5]=None
                require(same_value(left,right),'actual original '+name+' cases differ from native fixture')
    original=load(root/'scenario-reference.json');require(not validate_scenario_reference(original)and original['owners']==scenario_owners,'original full histories/owners differ')
    require(original['definitions']==scenario_definitions(snapshot)and len(original['cases'])==12,'original full history inputs differ')
    require(original['runtime']['system']==expected_system and original['runtime']['machine']==('arm64'if system=='macos'else'aarch64')and original['runtime']['python']=='3.12.9','original full history platform differs')
    script=HISTORY_SCRIPT if original.get('suite_reuse')else SCRIPT;require((root/'scenario-capture.py').read_bytes()==script.encode(),'actual history observer changed')
    for suffix,key in [('stdout','stdout_sha256'),('stderr','stderr_sha256')]:require(identity(root/('scenario-'+suffix))['sha256']==original['execution'][key],'raw original history bytes differ')
    if original.get('suite_reuse'):
        prior=original['suite_reuse']['reference'];require(load(root/'suite-reuse/scenario-reference.json')==prior and (root/'suite-reuse/scenario-capture.py').read_bytes()==INITIAL_SCRIPT.encode(),'original suite reuse differs')
        for suffix,key in [('stdout','stdout_sha256'),('stderr','stderr_sha256')]:require(identity(root/('suite-reuse/scenario-'+suffix))['sha256']==prior['execution'][key],'raw reused suite bytes differ')
        _verify_original_tests(prior,root/'suite-reuse/original-index.xml',27)
    else:_verify_original_tests(original,root/'original-index.xml',27)
    return original

def _verify_original_tests(value:dict,xml:Path,count:int):
    expected={p[:-3].replace('/','.')+'::'+n for p,n in (node.split('::',1)for node in value['discovered'])};states=junit_states(xml)
    require(len(expected)==count and set(states)==expected and set(states.values())=={'passed'},'actual original indexing suite incomplete')
    require({v['nodeid']for v in value['test_states']}==set(value['discovered'])and all(v['when']=='call'and v['outcome']=='passed'for v in value['test_states']),'original indexing call outcomes differ')

def verify_model_smoke(path:Path):
    value=load(path);require(value['format']=='ken-index-model-smoke/1'and value['dimension']==256 and len(value['texts'])==3 and value['token_counts']==[13,15,12],'real accepted indexing model integration missing')
    require(value['model']['model_id']=='minishlab/potion-code-16M-v2'and value['model']['revision']=='358803c97ebfa214e3cc325cfb1c8d0e4ceaf38d060676a7c2e40f9204c1589e','accepted indexing model changed')
    for key in ('vectors','stored_vectors'):
        require(len(value[key])==3,'real model output missing')
        for row in value[key]:
            require(len(row)==256 and all(type(n)in(int,float)and math.isfinite(n)for n in row)and sum(n*n for n in row)>0,'real model vector invalid')
            if key=='stored_vectors':require(abs(math.sqrt(sum(n*n for n in row))-1)<1e-6,'stored model vector not normalized')

def aggregate_index_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False)->dict:
    from .reference import verify_reference
    result=dict(passed=False,M3e_accepted=False,M3_accepted=False,migration_complete=False,errors=[])
    try:
        require(not _manifest_errors(directory),'indexing receipt file manifest differs');index=load(directory/'INDEX.json')
        require(index['format']=='ken-index-matrix/1'and index['predecessor']==PREDECESSOR,'indexing matrix/predecessor differs')
        require(identity(repo/PREDECESSOR['path']/'FILES.json')['sha256']==PREDECESSOR['sha256']and not _manifest_errors(repo/PREDECESSOR['path']),'accepted program predecessor changed')
        require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'preserved1066originals changed')
        require(index['sources']==source_identity(snapshot/'native-sources'),'indexing source snapshot differs')
        if current:require(index['sources']==source_identity(repo),'current indexing sources differ')
        for name,expected in index['tooling'].items():require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'indexing validation source differs')
        require(set(index['platforms'])=={'macos','linux'},'both actual indexing platforms required')
        for system in ('macos','linux'):
            platform=index['platforms'][system]
            with tempfile.TemporaryDirectory(prefix='ken-index-replay-')as temporary:
                raw=Path(temporary)
                with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
                original=verify_original_capture(raw/'original',snapshot/'native-sources',repo,system)
                require(not verify_index_capture(raw/'native',original,index['sources'],platform['native_sha256']),'actual complete native indexing capture differs')
                execution=load(raw/'native/execution.json');require((execution['system'],execution['machine'])==(system,'arm64'if system=='macos'else'aarch64'),'actual native indexing platform differs')
                inputs=load(raw/'native/inputs.json');runtime=load(snapshot/f'native-sources/crates/ken-models/tests/fixtures/profile-identity/{system}.json')['legacy_runtime'];require(inputs['legacy_runtime']==runtime and Path(inputs['grammar_manifest']).name=='manifest.json'and Path(inputs['grammar_manifest']).parent.name=='sdk-'+system,'native runtime/grammar resource selection differs')
                require(not verify_index_gates(raw/'gates'),'complete affected indexing gates differ');verify_model_smoke(raw/'model-smoke.json')
        result.update(passed=True,M3e_accepted=True,per_platform=dict(Rust=43,Python=TOOLING_TESTS,original_tests=49,vocabulary_inputs=195,passages=496,storage_histories=26,publication_histories=31,projection_histories=93,index_histories=12))
    except(OSError,ValueError,KeyError,TypeError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
    return result

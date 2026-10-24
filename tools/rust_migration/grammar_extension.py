"""Authenticate added-host syntax without borrowing whole-project acceptance."""
from __future__ import annotations
import base64,gzip,hashlib,json,re,struct
from pathlib import Path
from .fastembed_process import _distinct,_nonfinite
from .native_json import identity,load
from .parser_reference import validate_parser_reference,parser_owner_hashes,SUITE,LANGUAGES,PACKAGES
from .parser_validate import parser_cases,source_identity,LIMIT
from .parser_evidence import verify_parser_capture,parser_rust_gate_errors
from .receipts import junit_states
from .command_gates import lint_gate_errors
HOSTS={'linux-x86_64':('Linux','x86_64'),'linux-aarch64':('Linux','aarch64'),'macos-arm64':('Darwin','arm64')}
TEST_FILES=['tests/rust_migration/test_'+name+'.py'for name in ('grammar_prepare','parser_validate','parser_reference','parser_evidence','parser_matrix','command_gates','grammar_extension')]
LINT_COMMANDS={'fmt':['cargo','fmt','--all','--check'],'clippy':['cargo','clippy','--locked','--offline','-p','ken-syntax','--all-targets','--','-D','warnings']}
RUST_COMMANDS={
 'rust-list':['cargo','test','--locked','--offline','-p','ken-syntax','--all-targets','--','--list'],
 'rust-tests':['cargo','test','--locked','--offline','-p','ken-syntax','--all-targets','--no-fail-fast'],
 'doc-list':['cargo','test','--locked','--offline','-p','ken-syntax','--doc','--','--list'],
 'doc-tests':['cargo','test','--locked','--offline','-p','ken-syntax','--doc'],
 'probe-build':['cargo','build','--locked','--offline','-p','ken-syntax','--example','parser_probe'],
}
PYTHON_ROOTS=79
ORIGINAL_FILES=("reference.json","request.json","stdout.log","stderr.log","original-observations.json","original-tests.xml")
PREDECESSOR_FILES_SHA="c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8"

def require(value,message):
    if not value:raise ValueError(message)

def _reference_payload(path:Path):
    require(path.stat().st_size<=LIMIT,'compressed reference exceeds bound')
    opener=gzip.open if path.suffix=='.gz'else open
    with opener(path,'rb')as stream:raw=stream.read(LIMIT+1)
    require(len(raw)<=LIMIT,'parser reference exceeds32MiB')
    return json.loads(raw,object_pairs_hook=_distinct,parse_constant=_nonfinite)

def read_reference(path:Path):
    value=_reference_payload(path)
    if value.get('format')=='ken-parser-oracle-fixture/1':value=value['reference']
    require(not validate_parser_reference(value),'invalid complete parser reference')
    require(len(value['cases'])==215 and len(value['discovered'])==124,'original parser inventory differs')
    return value

def restore_fixture_original(path:Path,destination:Path):
    payload=_reference_payload(path)
    require(set(payload)=={'format','reference','files'}and payload['format']=='ken-parser-oracle-fixture/1','original fixture transport format differs')
    names=set(ORIGINAL_FILES)
    require(set(payload['files'])==names,'unsafe or incomplete original fixture members')
    data={}
    for name,row in payload['files'].items():
        require(set(row)=={'bytes','sha256','base64'}and type(row['bytes'])is int and 0<=row['bytes']<=LIMIT,'original fixture member bound differs')
        raw=base64.b64decode(row['base64'],validate=True)
        require(len(raw)==row['bytes']and hashlib.sha256(raw).hexdigest()==row['sha256'],'original fixture member bytes differ');data[name]=raw
    reference=read_reference(path)
    require(json.loads(data['reference.json'])==reference,'original fixture reference differs')
    require(not destination.is_symlink(),'original fixture destination is a symlink')
    if destination.exists():
        require(destination.is_dir()and all((destination/name).is_file()and not(destination/name).is_symlink()and(destination/name).read_bytes()==raw for name,raw in data.items()),'existing original fixture differs')
    else:
        destination.mkdir(parents=True)
        for name,raw in data.items():(destination/name).write_bytes(raw)
    return reference

def native_cases(reference,repo:Path):
    cases=parser_cases(repo);known={case['id']:case for case in cases}
    for case in reference['cases']:
        prior=known.get(case['id']);require(prior is not None,'new original parser input differs')
        require(all(case[key]==prior[key]for key in ('input','parsed','syntax')),'actual host parser semantics differ')
    require(len(cases)==249,'complete syntax compatibility inventory required')
    return cases

def _original(packet:Path,reference,repo:Path):
    original=packet/'original';value=load(original/'reference.json')
    require(value==reference and value['owners']==parser_owner_hashes(repo),'original owner/reference binding differs')
    request=load(original/'request.json')
    require(request['suite']==SUITE and tuple(request['languages'])==LANGUAGES and request['packages']==PACKAGES,'actual original request differs')
    execution=value['test_execution']
    for name,key in [('stdout.log','stdout_sha256'),('stderr.log','stderr_sha256'),('original-observations.json','observations_sha256')]:
        require(identity(original/name)['sha256']==execution[key],'raw original process differs')
    raw=load(original/'original-observations.json')
    require(all(value[key]==item for key,item in raw.items()),'raw original observations differ')
    states=junit_states(original/'original-tests.xml')
    require(len(states)==124 and set(states.values())=={'passed'},'complete original parser suite required')

def _binary_host(path:Path,host:str):
    with path.open('rb')as stream:header=stream.read(32)
    if host.startswith('linux-'):
        require(header[:6]==b'\x7fELF\x02\x01'and len(header)>=20,'native64bit Linux binary required')
        require(struct.unpack('<H',header[18:20])[0]==(62 if host=='linux-x86_64' else 183),'native binary architecture differs')
    else:require(header[:4]==b'\xcf\xfa\xed\xfe'and len(header)>=8 and struct.unpack('<I',header[4:8])[0]==0x0100000c,'native arm64 macOS binary required')

def verify_grammar_capture(packet:Path,repo:Path):
    try:
        host=load(packet/'HOST.json');require(set(host)=={'format','platform','system','machine','python','rustc','commit'}and host['format']=='ken-grammar-host/1','grammar host schema differs')
        require(host['platform']in HOSTS and(host['system'],host['machine'])==HOSTS[host['platform']],'grammar host platform differs')
        require(host['python']=='3.12.9'and host['rustc'].startswith('rustc 1.95.0 '),'pinned grammar development runtime differs')
        reference=read_reference(packet/'reference.json.gz')
        require((reference['runtime']['system'],reference['runtime']['machine'],reference['runtime']['python'])==(host['system'],host['machine'],'3.12.9'),'actual original host differs')
        _original(packet,reference,repo)
        if host['platform']=='linux-x86_64':
            require(reference==read_reference(repo/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz'),'registered actual x86oracle differs')
        else:
            import tarfile
            manifest=packet/'PREDECESSOR-FILES.json';require(identity(manifest)['sha256']==PREDECESSOR_FILES_SHA,'accepted parser predecessor differs')
            filename=('linux'if host['system']=='Linux'else'macos')+'-capture.tar.gz'
            pinned=next(row for row in load(manifest)['files']if row['path']==filename)
            archive=packet/'original-source.tar.gz';require(identity(archive)=={key:pinned[key]for key in('bytes','sha256')},'accepted original parser archive differs')
            with tarfile.open(archive,'r:gz')as original:
                for name in ORIGINAL_FILES:
                    member=original.getmember('original/'+name);require(member.isfile()and member.size<=LIMIT,'original archive member differs')
                    require(original.extractfile(member).read()==(packet/'original'/name).read_bytes(),'preserved ARM original changed')
        sources=load(packet/'SOURCES.json');require(sources==source_identity(repo),'grammar source snapshot differs')
        binary=packet/'bin/parser-probe';_binary_host(binary,host['platform'])
        execution=load(packet/'native/execution.json')
        require(execution['manifest']['platform']==host['platform'],'native grammar resource target differs')
        errors=verify_parser_capture(packet/'native',native_cases(reference,repo),sources,identity(binary)['sha256'],load(repo/'crates/ken-syntax/grammars.lock.json'))
        require(not errors,'; '.join(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError)as error:return[str(error)]

def verify_grammar_gates(gates:Path,*,python_roots:int=PYTHON_ROOTS):
    try:
        commands=load(gates/'COMMANDS.json')
        require(set(commands)==set(RUST_COMMANDS)|{'python-list','python-tests'},'complete syntax command inventory required')
        for name,row in commands.items():
            require(set(row)=={'command','exit','log'}and type(row['exit'])is int and row['exit']==0 and row['log']==identity(gates/(name+'.log')),'actual grammar command exit/log differs')
            if name in RUST_COMMANDS:require(row['command']==RUST_COMMANDS[name],'scoped syntax command differs')
            else:
                argv=row['command'];require(Path(argv[0]).name in('python','python3','python3.12')and argv[1:-1]==['-m','pytest','-o','addopts=','-q',*TEST_FILES],'scoped grammar tooling command differs')
                if name=='python-list':require(argv[-1]=='--collect-only','tooling discovery command differs')
                else:require(argv[-1].startswith('--junitxml=')and Path(argv[-1].split('=',1)[1]).name=='python.xml','tooling result command differs')
        listed=(gates/'rust-list.log').read_text()+(gates/'doc-list.log').read_text()
        output=(gates/'rust-tests.log').read_text()+(gates/'doc-tests.log').read_text()
        require(len(re.findall(r'^([^\n]+): test$',listed,re.M))==33 and not parser_rust_gate_errors(listed,output),'complete33native syntax/doc roots required')
        discovered=[]
        for line in(gates/'python-list.log').read_text().splitlines():
            if any(line.startswith(name+'::')for name in TEST_FILES):
                path,node=line.split('::',1);discovered.append(path[:-3].replace('/','.')+'::'+node)
        states=junit_states(gates/'python.xml')
        require(len(discovered)==len(set(discovered))==python_roots and set(discovered)==set(states)and set(states.values())=={'passed'},'complete scoped grammar tooling roots required')
        errors=lint_gate_errors(gates,LINT_COMMANDS);require(not errors,'; '.join(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_grammar_packet(packet:Path,repo:Path):
    errors=verify_grammar_capture(packet,repo)
    return errors or verify_grammar_gates(packet/'gates')

def extract_grammar_snapshot(packet:Path,destination:Path):
    from .native_snapshot import extract_source_snapshot
    sources=load(packet/'SOURCES.json');tooling=load(packet/'VALIDATION-SOURCES.json')
    require(bool(tooling),'grammar validator snapshot missing')
    required=dict(sources);required.update(tooling)
    extract_source_snapshot(packet,destination,required=required)
    require(source_identity(destination)==sources,'archived grammar sources differ')
    for name,row in tooling.items():require(identity(destination/name)==row,'archived grammar validator differs')
    return destination

def aggregate_grammar_hosts(directory:Path,repo:Path,review:Path|None=None):
    result=dict(format='ken-grammar-extension/1',gates_passed=False,Grammar_x86_64_accepted=False,Index_x86_64_accepted=False,M3_accepted=False,M4_accepted=False,migration_complete=False,errors=[],platforms=[])
    try:
        for platform in HOSTS:
            packet=directory/platform;host=load(packet/'HOST.json');require(host['platform']==platform,'actual grammar host missing')
            errors=verify_grammar_packet(packet,repo);require(not errors,platform+': '+str(errors))
            result['platforms'].append(dict(platform=platform,commit=host['commit'],sources=load(packet/'SOURCES.json'),native=identity(packet/'bin/parser-probe')))
        rows=result['platforms'];require(re.fullmatch('[0-9a-f]{40}',rows[0]['commit'])and all(row['commit']==rows[0]['commit']and row['sources']==rows[0]['sources']for row in rows),'grammar hosts ran different candidate sources')
        result['gates_passed']=True
        if review is not None:
            value=load(review);require(value['format']=='ken-grammar-extension-review/1'and value['whole_plan']is True and value['critical_open']==[]and value['important_open']==[]and value['accepted_sources']==rows[0]['sources'],'whole-plan grammar review not closed/source-bound')
            name=Path(value['raw_review']['path']);require(not name.is_absolute()and'..'not in name.parts and identity(review.parent/name)==value['raw_review']['identity'],'raw grammar review differs')
            result['Grammar_x86_64_accepted']=True
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:result['errors'].append(str(error))
    return result

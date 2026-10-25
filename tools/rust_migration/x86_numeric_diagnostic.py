"""Same-machine numerical observations; successful capture is never model acceptance."""
from pathlib import Path
import argparse,gzip,hashlib,json,math,os,platform,re,shutil,signal,subprocess,sys
from .native_json import identity,load,same_value

MODULE='tools.rust_migration.x86_numeric_diagnostic'
BASELINE='49bf56ce2dedc4df327ff1c99942438e0ddf0e3a'
CONTEXT='crates/ken-models/tests/fixtures/context/linux-x86_64-original.json'
ALIGNMENT='crates/ken-retrieval/tests/fixtures/numeric-reference-alignment-linux-x86_64.json.gz'
CONTEXT_SHA='b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733'
ALIGNMENT_SHA='b4821c3ef9ade8966e8681698367ec1dd473255eedf0c71cc52da36da142e754'
IDS=['empty-query','passage-boundary511','passage-boundary512']
ALIGNMENT_ID='product-float32-float32-float64-4-128-3'
OBSERVERS=['alignment-'+mode+'-'+language for mode in('native','haswell')for language in('python','rust')]+['context-native','context-adapter','context-file-1','context-file-2','context-memory-1','context-memory-2']
SOURCE_PATHS=['crates/ken-models','crates/ken-native-model-api','crates/ken-retrieval/src/alignment.rs','crates/ken-retrieval/src/dense_math.rs','crates/ken-retrieval/tests/alignment.rs','Cargo.toml','Cargo.lock','rust-toolchain.toml']
SUITES=[who+'-'+kind for who in('candidate','baseline')for kind in('context-full','context-filtered','alignment')]
ENV_KEYS=('OPENBLAS_CORETYPE','OPENBLAS_NUM_THREADS','KEN_DENSE_BLAS_DIR','KEN_ORT_LIBRARY','KEN_CONTEXT_SNAPSHOT','CARGO_TARGET_DIR','RUST_TEST_THREADS','CARGO_BUILD_JOBS')

def require(ok,message):
    if not ok:raise ValueError(message)
def save(path:Path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()
def inputs_from(context,alignment):
    return dict(context=[row for row in context['cases']if row['id']in IDS],alignment=next(dict(id=row['id'],family='alignment',kind=row['kind'],input=row['input'])for row in alignment['cases']if row['id']==ALIGNMENT_ID))
def fixed_inputs(repo:Path):
    require(identity(repo/CONTEXT)['sha256']==CONTEXT_SHA,'context reference changed')
    require(identity(repo/ALIGNMENT)['sha256']==ALIGNMENT_SHA,'alignment reference changed')
    return inputs_from(load(repo/CONTEXT),json.loads(gzip.decompress((repo/ALIGNMENT).read_bytes())))

def record(out:Path,name:str,command:list[str],*,cwd:Path,request=None,env=None,timeout=600):
    require(bool(re.fullmatch('[a-z][a-z0-9-]{0,80}',name)),'invalid command name')
    paths={suffix:out/(name+'.'+suffix)for suffix in('stdout','stderr','record.json','input.json')}
    if any(path.exists()for path in paths.values()):raise FileExistsError(name)
    environment=os.environ.copy()if env is None else env.copy()
    command=list(map(str,command));executable=Path(shutil.which(command[0],path=environment.get('PATH'))or command[0]).resolve()
    require(executable.is_file(),'command executable missing');binary=identity(executable)
    raw=None if request is None else(json.dumps(request,allow_nan=False)+'\n').encode()
    if raw is not None:paths['input.json'].write_bytes(raw)
    timed_out=False
    with paths['stdout'].open('xb')as stdout,paths['stderr'].open('xb')as stderr:
        child=subprocess.Popen(command,cwd=cwd,env=environment,stdin=subprocess.PIPE if raw is not None else subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
        try:child.communicate(raw,timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True;os.killpg(child.pid,signal.SIGKILL);child.wait()
    require(identity(executable)==binary,'command executable changed')
    row=dict(name=name,command=command,cwd=str(cwd.resolve()),executable=dict(path=str(executable),**binary),environment={key:environment[key]for key in ENV_KEYS if key in environment},exit=child.returncode,timed_out=timed_out,timeout_s=timeout,stdout=identity(paths['stdout']),stderr=identity(paths['stderr']),input=None if raw is None else identity(paths['input.json']))
    save(paths['record.json'],row);return row

def verify_record(out:Path,row:dict):
    try:
        require(set(row)=={'name','command','cwd','executable','environment','exit','timed_out','timeout_s','stdout','stderr','input'},'command fields differ')
        name=row['name'];require(isinstance(name,str)and bool(re.fullmatch('[a-z][a-z0-9-]{0,80}',name)),'command name differs')
        require(same_value(load(out/(name+'.record.json')),row),'record transport differs')
        require(type(row['exit'])is int and row['timed_out']is False,'command timed out or exit malformed')
        require(isinstance(row['command'],list)and row['command']and all(isinstance(x,str)for x in row['command']),'command missing')
        require(Path(row['cwd']).is_absolute()and Path(row['executable']['path']).is_absolute(),'command locations differ')
        require(set(row['environment'])<=set(ENV_KEYS),'unexpected environment values')
        for suffix,key in [('stdout','stdout'),('stderr','stderr'),('input.json','input')]:
            if row[key]is not None:require(identity(out/(name+'.'+suffix))==row[key],'raw '+suffix+' differs')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def vector_difference(actual,expected):
    valid=lambda v:isinstance(v,list)and bool(v)and all(type(x)in(int,float)and math.isfinite(x)for x in v)
    require(valid(actual)and valid(expected)and len(actual)==len(expected),'finite aligned vectors required')
    return dict(max_abs=max(abs(x-y)for x,y in zip(actual,expected,strict=True)),exact=same_value(actual,expected),within_frozen_tolerance=all(abs(x-y)<=2e-6+1e-5*abs(y)for x,y in zip(actual,expected,strict=True)))

def comparison(out:Path):
    frozen=load(out/'original-context.json');wanted={c['id']:r for c,r in zip(frozen['cases'],frozen['results'],strict=True)}
    native=load(out/'context-native.stdout');require([c['id']for c in native['results']]==IDS,'native context membership differs')
    native_vectors={row['id']:row['calls'][1]if row['id']=='empty-query'else row['calls'][1][0]for row in native['results']}
    context=[]
    for name in OBSERVERS[5:]:
        value=load(out/(name+'.stdout'));require([r['id']for r in value['cases']]==IDS,'Python context membership differs')
        for row,native_row in zip(value['cases'],native['results'],strict=True):
            require(same_value(row['tokens'],native_row['calls'][0]),'native/Python token inputs differ')
            expected=wanted[row['id']]['calls'][1];expected=expected if row['id']=='empty-query'else expected[0]
            require(len(row['vectors'])==(1 if name=='context-adapter'else 2),'context repeats missing')
            for index,vector in enumerate(row['vectors']):
                context.append(dict(observer=name,case=row['id'],repeat=index,python_native=vector_difference(vector,native_vectors[row['id']]),python_frozen=vector_difference(vector,expected)))
    original=json.loads(gzip.decompress((out/'original-alignment.json.gz').read_bytes()));expected=next(c['result']for c in original['cases']if c['id']==ALIGNMENT_ID)
    alignment=[]
    for mode in('native','haswell'):
        python=load(out/('alignment-'+mode+'-python.stdout'));rust=load(out/('alignment-'+mode+'-rust.stdout'))
        require(len(rust['cases'])==1 and rust['cases'][0]['id']==ALIGNMENT_ID,'native alignment membership differs')
        result=rust['cases'][0]['result'];similarities=[x for row in python['similarities']for x in row]
        require(set(python['coverage'])==set(result['coverage'])==set(expected['coverage']),'alignment coverage differs')
        alignment.append(dict(mode=mode,blas=python['blas'],similarities=vector_difference(similarities,result['values']),python_weighted=python['coverage']['weighted'],native_weighted=result['coverage']['weighted'],frozen_weighted=expected['coverage']['weighted'],weighted_native_difference=abs(python['coverage']['weighted']-result['coverage']['weighted']),weighted_frozen_difference=abs(python['coverage']['weighted']-expected['coverage']['weighted'])))
    return dict(context=context,alignment=alignment,cpu_cause_established=False,note='Same-host parity, frozen differences, and kernel intervention are separate observations. This report grants no model acceptance.')

def suite_commands():
    context=['cargo','test','--locked','--offline','-p','ken-models','--test','context_encoder']
    return {'context-full':[*context,'--no-fail-fast'],'context-filtered':[*context,'registered_context_matches_all_twenty_local_frozen_histories','--','--exact','--nocapture'],'alignment':['cargo','test','--locked','--offline','-p','ken-retrieval','--test','alignment','--no-fail-fast']}

def verify_report(out:Path):
    try:
        value=load(out/'report.json');require(set(value)=={'format','complete_observations','model_acceptance','suites','environment','inputs_sha256','records','comparison'},'diagnostic report fields differ')
        require(value['format']=='ken-x86-numeric-diagnostic/1'and value['complete_observations']is True and value['model_acceptance']is False and type(value['suites'])is bool,'capture is not model acceptance')
        require(identity(out/'original-context.json')['sha256']==CONTEXT_SHA and identity(out/'original-alignment.json.gz')['sha256']==ALIGNMENT_SHA,'frozen transport differs')
        fixed=inputs_from(load(out/'original-context.json'),json.loads(gzip.decompress((out/'original-alignment.json.gz').read_bytes())))
        require(same_value(load(out/'inputs.json'),fixed)and value['inputs_sha256']==digest(fixed),'fixed inputs contain answers or differ')
        wanted=OBSERVERS+(SUITES if value['suites']else[])
        require([r['name']for r in value['records']]==wanted,'complete observer/suite inventory required')
        for row in value['records']:
            require(not verify_record(out,row),'raw command differs: '+row['name'])
            if row['name']in OBSERVERS:
                name=row['name'];argv=row['command'];require(row['exit']==0,'observer failed: '+name)
                if name=='context-native' or name.endswith('-rust'):
                    require(len(argv)==1 and Path(argv[0]).name==('context_probe'if name=='context-native'else'numeric_owner_probe'),'native observer command differs')
                else:
                    kind='python-alignment'if name.startswith('alignment-')else'python-context'
                    expected=['-B','-m',MODULE,kind,'--repo',row['cwd']]
                    if kind=='python-context':
                        mode='adapter'if name=='context-adapter'else name.split('-')[1];threads='1'if name=='context-adapter'else name.split('-')[2]
                        expected+=['--mode',mode,'--threads',threads]
                    require(Path(argv[0]).name in('python','python3','python3.12')and argv[1:]==expected,'Python observer command differs')
            else:
                kind=row['name'].split('-',1)[1];require(row['command']==suite_commands()[kind],'numerical suite command differs')
                stdout=(out/(row['name']+'.stdout')).read_text();states=re.findall(r'^test (\S+) \.\.\. (ok|FAILED)$',stdout,re.M)
                count=8 if row['name'].endswith('context-full')else 1 if row['name'].endswith('context-filtered')else 4
                require(len(states)==len({name for name,_ in states})==count,'suite did not execute complete scope')
                require(row['exit']==(101 if any(state=='FAILED'for _,state in states)else 0),'suite exit disagrees with states')
        for mode in('native','haswell'):
            row=next(r for r in value['records']if r['name']=='alignment-'+mode+'-rust')
            request=load(out/(row['name']+'.input.json'));require(same_value(request,dict(format='ken-numeric-owner-probe/1',resources={},cases=[fixed['alignment']])),'native alignment request contains answers')
            if mode=='haswell':require(row['environment'].get('OPENBLAS_CORETYPE')=='Haswell','intervention environment missing')
        request=load(out/'context-native.input.json');require(same_value(request['cases'],fixed['context'])and set(request)=={'registration','snapshot','runtime_registration','library','cases'},'context request contains answers')
        for row in value['records']:
            name=row['name']
            if name.startswith('alignment-')and name.endswith('-python'):
                require(same_value(load(out/(name+'.input.json')),fixed['alignment']),'Python alignment request differs')
                if name=='alignment-haswell-python':require(row['environment'].get('OPENBLAS_CORETYPE')=='Haswell','Python intervention environment missing')
            elif name.startswith('context-')and name!='context-native'and name in OBSERVERS:
                require(same_value(load(out/(name+'.input.json')),request),'Python context request differs')
        require(same_value(request['registration'],load(out/'original-context.json')['definition']),'context registration differs')
        candidate=value['environment']['candidate'];require(isinstance(candidate,str)and bool(re.fullmatch('[0-9a-f]{40}',candidate)),'candidate commit differs')
        sources=value['environment']['identical_sources']
        require(set(sources)==set(SOURCE_PATHS),'baseline source inventory differs')
        for path,identities in sources.items():
            require(set(identities)=={BASELINE,candidate}and len(set(identities.values()))==1 and all(isinstance(v,str)and bool(re.fullmatch('[0-9a-f]{40}',v))for v in identities.values()),'baseline source identity differs: '+path)

        require(same_value(value['comparison'],comparison(out)),'diagnostic conclusions differ from raw measurements')
        require(value['environment']['machine']=='x86_64'and value['environment']['baseline']==BASELINE,'diagnostic target/baseline differs')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration)as error:return[str(error)]

def run(repo:Path,out:Path,sdk:Path,snapshot:Path,*,suites:bool):
    from .context_reference import snapshot_state
    from .context_host import context_request
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    fixed=fixed_inputs(repo);shutil.copyfile(repo/CONTEXT,out/'original-context.json');shutil.copyfile(repo/ALIGNMENT,out/'original-alignment.json.gz');save(out/'inputs.json',fixed)
    ready=load(sdk/'PREPARATION.json');definition=load(repo/'src/ken/embedder/data/code-context-int8.json');snapshot_state(snapshot,definition)
    context=context_request(repo,dict(definition=definition,cases=fixed['context']),out)
    context['snapshot']=str(snapshot.resolve());context['library']=ready['prepared']['onnx_library']
    alignment=dict(format='ken-numeric-owner-probe/1',resources={},cases=[fixed['alignment']]);records=[]
    env=os.environ|{'PYTHONPATH':str(repo)+os.pathsep+str(repo/'src'),'KEN_ORT_LIBRARY':context['library'],'KEN_CONTEXT_SNAPSHOT':str(snapshot.resolve()),'CARGO_TARGET_DIR':str(repo/'target'),'RUST_TEST_THREADS':'1'}
    env.pop('OPENBLAS_CORETYPE',None)
    for mode in('native','haswell'):
        child_env=env|({'OPENBLAS_CORETYPE':'Haswell'}if mode=='haswell'else{})
        records.append(record(out,'alignment-'+mode+'-python',[sys.executable,'-B','-m',MODULE,'python-alignment','--repo',str(repo)],cwd=repo,request=fixed['alignment'],env=child_env))
        records.append(record(out,'alignment-'+mode+'-rust',[str(repo/'target/debug/examples/numeric_owner_probe')],cwd=repo,request=alignment,env=child_env))
    records.append(record(out,'context-native',[str(repo/'target/debug/examples/context_probe')],cwd=repo,request=context,env=env))
    for mode,threads in [('adapter',1),('file',1),('file',2),('memory',1),('memory',2)]:
        name='context-'+mode+(''if mode=='adapter'else'-'+str(threads))
        records.append(record(out,name,[sys.executable,'-B','-m',MODULE,'python-context','--repo',str(repo),'--mode',mode,'--threads',str(threads)],cwd=repo,request=context,env=env))
    candidate=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();identities={}
    for path in SOURCE_PATHS:
        identities[path]={sha:subprocess.check_output(['git','rev-parse',sha+':'+path],cwd=repo,text=True).strip()for sha in(BASELINE,candidate)}
        require(len(set(identities[path].values()))==1,'baseline numerical source differs: '+path)
    environment=dict(system=platform.platform(),machine=platform.machine(),cpuinfo=Path('/proc/cpuinfo').read_text(),candidate=candidate,baseline=BASELINE,identical_sources=identities,artifacts=snapshot_state(snapshot,definition))
    if suites:
        baseline=out.parent/(out.name+'-baseline');subprocess.run(['git','worktree','add','--detach',str(baseline),BASELINE],cwd=repo,check=True)
        for who,source in [('candidate',repo),('baseline',baseline)]:
            for kind in('context-full','context-filtered','alignment'):
                command=suite_commands()[kind]
                records.append(record(out,who+'-'+kind,command,cwd=source,env=env))
    for row in records:
        if row['name']in OBSERVERS:require(row['exit']==0,'observer failed: '+row['name']+' (see raw stderr)')
    value=dict(format='ken-x86-numeric-diagnostic/1',complete_observations=True,model_acceptance=False,suites=suites,environment=environment,inputs_sha256=digest(fixed),records=records,comparison=comparison(out))
    save(out/'report.json',value);errors=verify_report(out);require(not errors,str(errors));return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['run','verify','python-alignment','python-context']);parser.add_argument('--repo',type=Path,default=Path.cwd());parser.add_argument('--out',type=Path);parser.add_argument('--sdk',type=Path);parser.add_argument('--snapshot',type=Path);parser.add_argument('--suites',action='store_true');parser.add_argument('--mode',default='adapter');parser.add_argument('--threads',type=int,default=1);args=parser.parse_args()
    if args.command=='python-alignment':
        from .x86_numeric_alignment import observe
        print(json.dumps(observe(json.load(sys.stdin),args.repo),allow_nan=False))
    elif args.command=='python-context':
        from .x86_numeric_context import observe
        print(json.dumps(observe(json.load(sys.stdin),args.repo,args.mode,args.threads),allow_nan=False))
    elif args.command=='run':
        value=run(args.repo,args.out,args.sdk,args.snapshot,suites=args.suites);print(json.dumps(value['comparison'],indent=2))
    else:
        errors=verify_report(args.out);require(not errors,str(errors));print('PASS diagnostic raw replay; no model acceptance')
if __name__=='__main__':main()

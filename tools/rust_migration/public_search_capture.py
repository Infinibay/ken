"""Audit the native public caller, its declared CLI children and native threads."""
from pathlib import Path
import json,os,platform,re,shutil,signal,subprocess,tempfile
from .native_json import identity,load,tree,same_value
from .native_binary import check_native_architecture
from .public_search_resources import stage,relative

PREFIX='ken-public-search-'
APPLICATIONS=29
TRACE='trace=execve,execveat,connect,clone,clone3,fork,vfork'

def require(condition,message):
    if not condition:raise ValueError(message)

def _syscalls(raw):
    pending={}
    for line in raw.splitlines():
        resumed=re.match(r'^<\.\.\. (\w+) resumed>(.*)$',line)
        if resumed:
            name,suffix=resumed.groups()
            require(name in pending,'unmatched resumed process syscall')
            line=pending.pop(name)+suffix
        if '<unfinished ...>'in line:
            name=re.match(r'^(\w+)\(',line)
            require(name is not None and name[1]not in pending,'ambiguous unfinished process syscall')
            pending[name[1]]=line.split('<unfinished ...>',1)[0]
            continue
        yield line
    require(not pending,'incomplete process syscall trace')

def _hex_path(value):
    require(re.fullmatch(r'(?:\\x[0-9a-f]{2})+',value)is not None,'strace must retain complete hexadecimal executable paths')
    return bytes(int(value[i+2:i+4],16)for i in range(0,len(value),4)).decode()

def process_errors(directory,root,*,applications):
    """Only the caller may create CLI processes; CLI code may create threads."""
    try:
        directory,root=map(Path,(directory,root));records={}
        for file in directory.glob('trace.*'):
            suffix=file.name.removeprefix('trace.')
            require(suffix.isdigit()and int(suffix)>0,'unexpected process trace name')
            records[int(suffix)]=list(_syscalls(file.read_text()))
        require(records,'actual per-process trace required')
        executables={};parents={}
        for pid,lines in records.items():
            for line in lines:
                require(re.search(r'\bconnect\(',line)is None,'public search attempted a network connection')
                if line.startswith('execveat('):raise ValueError('unexpected execveat in public caller')
                if line.startswith('execve('):
                    match=re.match(r'execve\("([^"\n]*)",',line)
                    require(match is not None and re.search(r'\)\s*=\s*0$',line)is not None,'failed or incomplete executable trace')
                    require(pid not in executables,'process executed more than one program')
                    executables[pid]=_hex_path(match[1])
                if re.match(r'^(clone3?|fork|vfork)\(',line):
                    returned=re.search(r'=\s*([0-9]+)$',line)
                    if returned is None:
                        require(re.search(r'=\s*-1\s+\w+',line)is not None,'unresolved process creation')
                        continue
                    child=int(returned[1]);require(child>0 and child not in parents,'duplicate process ancestry')
                    parents[child]=(pid,'CLONE_THREAD'in line)
        callers=[pid for pid,path in executables.items()if path==str(root/'native-caller')]
        require(len(callers)==1,'one actual copied native caller required');caller=callers[0]
        require(caller not in parents,'native caller cannot be a CLI descendant')
        require(type(applications)is int and applications>0,'declared application process count required')
        require(len(executables)==applications+1 and set(executables.values())=={str(root/'native-caller'),str(root/'ken-rs')},'foreign or missing executable in public execution')
        groups={caller:caller}
        def group(pid,visiting=None):
            if pid in groups:return groups[pid]
            visiting=set()if visiting is None else visiting
            require(pid in records and pid in parents and pid not in visiting,'missing or cyclic process ancestry')
            visiting.add(pid);parent,thread=parents[pid]
            owner=group(parent,visiting)
            groups[pid]=owner if thread else pid
            visiting.remove(pid);return groups[pid]
        for pid in records:group(pid)
        for child,(parent,thread)in parents.items():
            require(child in records,'process trace omitted')
            if not thread:
                require(group(parent)==caller and executables.get(child)==str(root/'ken-rs'),'CLI created a child process or caller ownership differs')
        for pid,path in executables.items():
            if pid!=caller:require(pid in parents and not parents[pid][1]and group(pid)==pid,'application lacks caller-owned process ancestry')
        return[]
    except(OSError,ValueError,KeyError,TypeError,UnicodeError)as error:return[str(error)]


def evidence_errors(directory,root,applications):
    """Bind each application's raw streams and loader record to an actual PID."""
    try:
        directory,root=map(Path,(directory,root))
        found={int(p.name.removeprefix('app-'))for p in directory.glob('app-*')if p.is_dir()}
        require(found==applications,'retained public streams differ from traced applications')
        for pid in applications:
            app=directory/f'app-{pid}';record=load(app/'invocation.json')
            require(record['pid']==pid and record['program']==str(root/'ken-rs')
                and Path(record['cwd']).is_relative_to(root/'work'),'public process inputs belong to another execution')
            require(isinstance(record['args'],list)and all(isinstance(v,str)for v in record['args']),'actual public process arguments required')
            for name in ('stdin','stdout','stderr'):require((app/name).is_file(),'actual application stream missing')
            require((app/'exit').read_text()in('0','1','2'),'actual public process exit missing')
            loader=(directory/f'loader.{pid}').read_bytes()
            require(b'calling init:'in loader and b'libpython'not in loader and b'libtorch_python'not in loader,'actual native application loader audit missing or Python loaded')
        for file in directory.glob('loader.*'):
            loader=file.read_bytes()
            require(b'libpython'not in loader and b'libtorch_python'not in loader,'Python loaded by public caller')
        return[]
    except(OSError,ValueError,KeyError,TypeError,UnicodeError)as error:return[str(error)]


def environment_for(root,inputs):
    environment={name:str(root/relative(path))for name,path in inputs['environment'].items()}
    environment.update(PATH=str(root/'empty-path'),HOME=str(root/'home'),TMPDIR=str(root/'work'),
        LANG='C.UTF-8',LC_ALL='C.UTF-8',KEN_PUBLIC_NATIVE=str(root/'ken-rs'),
        KEN_PUBLIC_EVIDENCE=str(root/'evidence'),LD_DEBUG='libs',LD_DEBUG_OUTPUT=str(root/'evidence/loader'))
    return environment


def command_for(tracer,root,out):
    return[str(tracer),'--seccomp-bpf','-ff','-xx','-s','4096','-e',TRACE,
        '-o',str(out/'traces/trace'),str(root/'native-caller'),'--test-threads=1']


def immutable_files(root):
    return{name:row for name,row in tree(root,strict=True).items()
        if Path(name).parts[0]not in('work','home','evidence')}


def capture(out,repo,caller,application,inputs):
    """Keep the sandbox and all raw observations, including failed executions."""
    out,repo,caller,application=map(Path,(out,repo,caller,application))
    require((platform.system(),platform.machine())==('Linux','x86_64'),'Linux x86 public caller required')
    for binary in(caller,application):
        check_native_architecture(binary,('linux','x86_64'))
        require(os.access(binary,os.X_OK),'executable native binary required')
    tracer=shutil.which('strace');require(tracer,'actual public process auditing required')
    out.mkdir(parents=True);(out/'traces').mkdir()
    root=Path(tempfile.mkdtemp(prefix=PREFIX)).resolve()
    require(not root.is_relative_to(repo.resolve()),'public execution must be outside checkout')
    for name in('work','home','empty-path','evidence'):(root/name).mkdir()
    shutil.copy2(caller,root/'native-caller');shutil.copy2(application,root/'ken-rs')
    stage(inputs,root)
    before=immutable_files(root);environment=environment_for(root,inputs)
    command=command_for(tracer,root,out.resolve());timed_out=False
    with(out/'stdout').open('wb')as stdout,(out/'stderr').open('wb')as stderr:
        process=subprocess.Popen(command,cwd=root,env=environment,stdin=subprocess.DEVNULL,
            stdout=stdout,stderr=stderr,start_new_session=True)
        try:process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
    shutil.copytree(root/'evidence',out/'evidence')
    receipt=dict(format='ken-public-search-execution/1',cwd=str(root),command=command,
        env=environment,exit=process.returncode,timed_out=timed_out,timeout_s=600,
        immutable_before=before,immutable_after=immutable_files(root),
        streams={name:identity(out/name)for name in('stdout','stderr')},
        evidence=tree(out/'evidence',strict=True),traces=tree(out/'traces',strict=True))
    (out/'execution.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return root


def verify_execution(out,repo,inputs,*,caller,application):
    try:
        out,repo=map(Path,(out,repo));receipt=load(out/'execution.json');root=Path(receipt['cwd'])
        require(set(receipt)=={'format','cwd','command','env','exit','timed_out','timeout_s',
            'immutable_before','immutable_after','streams','evidence','traces'},'unexpected public execution receipt fields')
        require(receipt['format']=='ken-public-search-execution/1'and type(receipt['exit'])is int
            and receipt['exit']==0 and receipt['timed_out']is False and receipt['timeout_s']==600,'public caller did not complete')
        require(root.is_absolute()and'..'not in root.parts and root.name.startswith(PREFIX)
            and not root.is_relative_to(repo.resolve()),'copied public caller is not outside checkout')
        command=receipt['command']
        # The trace path belongs to the original packet location; replay may move it.
        require(len(command)==12 and Path(command[0]).name=='strace'
            and Path(command[9]).is_absolute()and Path(command[9]).name=='trace'
            and Path(command[9]).parent.name=='traces','actual public trace command required')
        recorded=Path(command[9]).parent.parent
        require(command==command_for(command[0],root,recorded),'public process command differs')
        require(same_value(receipt['env'],environment_for(root,inputs)),'public environment contains undeclared inputs')
        wanted={name:row['artifact']for name,row in inputs['files'].items()}
        translation=dict(inputs['translation'])
        for key in('module_path','core_root'):translation[key]=str(root/relative(translation[key]))
        raw=(json.dumps(translation,indent=2)+'\n').encode()
        import hashlib
        wanted[inputs['environment']['KEN_CT2_PREPARATION']]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        wanted.update({'native-caller':caller,'ken-rs':application})
        require(same_value(receipt['immutable_before'],wanted)
            and same_value(receipt['immutable_after'],wanted),'public data-only resource closure changed')
        require(receipt['streams']=={name:identity(out/name)for name in('stdout','stderr')}
            and receipt['evidence']==tree(out/'evidence',strict=True)
            and receipt['traces']==tree(out/'traces',strict=True),'actual public streams/traces differ')
        require(not process_errors(out/'traces',root,applications=APPLICATIONS),'public process ancestry/network differs')
        pids=set();caller_pid=None
        for file in(out/'traces').glob('trace.*'):
            for line in _syscalls(file.read_text()):
                match=re.match(r'execve\("([^"\n]*)",',line)
                if match and _hex_path(match[1])==str(root/'ken-rs'):pids.add(int(file.name.removeprefix('trace.')))
                if match and _hex_path(match[1])==str(root/'native-caller'):caller_pid=int(file.name.removeprefix('trace.'))
        errors=evidence_errors(out/'evidence',root,pids);require(not errors,str(errors))
        require(caller_pid is not None and b'calling init:'in(out/'evidence'/f'loader.{caller_pid}').read_bytes(),'caller loader missing')
        from .integration_validate import rust_gate_errors
        names=re.findall(r'^test (\S+) \.\.\. ok$',(out/'stdout').read_text(),re.M)
        require(len(names)==10 and len(set(names))==10
            and not rust_gate_errors('\n'.join(name+': test'for name in names),(out/'stdout').read_text()),'complete native public caller assertions required')
        return[]
    except(OSError,ValueError,KeyError,TypeError,UnicodeError,IndexError,StopIteration)as error:return[str(error)]

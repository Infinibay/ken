"""One bounded native JSON process with reusable outside-checkout execution audit."""
from __future__ import annotations
import hashlib,json,os,platform,re,shutil,signal,stat,subprocess,tempfile
from pathlib import Path,PurePosixPath
from .fastembed_process import _distinct,_nonfinite

LIMIT=16*1024*1024
MACOS_CONFINEMENT='(version 1)(allow default)(deny network*)(deny process-fork)(deny process-exec (require-not (require-any (literal (param "NATIVE")) (literal "/usr/bin/env"))))'
def macos_confined_command(native:Path):
    # sandbox-exec is platform protected: pass DYLD through env's arguments so
    # SIP does not strip the loader audit before the native executable starts.
    return ['/usr/bin/sandbox-exec','-D','NATIVE='+str(native),'-p',MACOS_CONFINEMENT,'/usr/bin/env','DYLD_PRINT_LIBRARIES=1',str(native)]
def identity(path:Path)->dict:
    with path.open('rb')as stream:return dict(bytes=path.stat().st_size,sha256=hashlib.file_digest(stream,'sha256').hexdigest())
def load(path:Path):
    with path.open('rb')as stream:raw=stream.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError('native JSON exceeds16MiB')
    return json.loads(raw,object_pairs_hook=_distinct,parse_constant=_nonfinite)
def tree(root:Path,*,strict:bool=False)->dict:
    if strict:
        for path in root.rglob('*'):
            mode=path.lstat().st_mode
            if not(stat.S_ISREG(mode)or stat.S_ISDIR(mode)):raise ValueError('nonregular owned resource')
    return {str(p.relative_to(root)):identity(p)for p in sorted(root.rglob('*'))if p.is_file()}

def generated_contract(files):
    if files is None:return None
    if not isinstance(files,dict)or not files:raise ValueError('nonempty generated files contract required')
    result={}
    for name,record in files.items():
        if not isinstance(name,str):raise ValueError('unsafe generated path')
        path=PurePosixPath(name)
        if(not name or path.is_absolute()or'..'in path.parts or str(path)!=name or path.parts[0]in('native-probe','empty-path','home')):raise ValueError('unsafe generated path')
        if(not isinstance(record,dict)or set(record)!={'bytes','sha256'}or type(record['bytes'])is not int or record['bytes']<0 or not isinstance(record['sha256'],str)or not re.fullmatch('[0-9a-f]{64}',record['sha256'])):raise ValueError('invalid generated file identity')
        result[name]=dict(record)
    if any(left!=right and right.startswith(left+'/')for left in result for right in result):raise ValueError('overlapping generated paths')
    return result

def same_value(left,right):
    """JSON equality preserves scalar types (Python's True equals integer 1)."""
    if type(left)is not type(right):return False
    if isinstance(left,dict):return left.keys()==right.keys()and all(same_value(value,right[key])for key,value in left.items())
    if isinstance(left,list):return len(left)==len(right)and all(same_value(a,b)for a,b in zip(left,right,strict=True))
    return left==right

class NativeJsonCapture:
    def __init__(self,probe:Path,out:Path,*,repo:Path,prefix:str,macos_confinement:bool=False,generated_files:dict|None=None):
        self.probe,self.out,self.repo,self.prefix=probe.resolve(),out.resolve(),repo.resolve(),prefix
        self.macos_confinement=macos_confinement
        self.generated_files=generated_contract(generated_files)
    def __enter__(self):
        with self.probe.open('rb')as stream:magic=stream.read(4)
        if magic not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe')or not os.access(self.probe,os.X_OK):raise ValueError('native executable required; interpreter scripts rejected')
        self.out.mkdir(parents=True,exist_ok=False)
        self.temporary=tempfile.TemporaryDirectory(prefix=self.prefix);self.root=Path(self.temporary.name).resolve()
        try:
            if self.root.is_relative_to(self.repo):raise ValueError('native process must run outside checkout')
            self.native=self.root/'native-probe';shutil.copy2(self.probe,self.native)
            self.binary=identity(self.probe)
            (self.root/'empty-path').mkdir();(self.root/'home').mkdir()
            return self
        except BaseException:self.temporary.cleanup();raise
    def run(self,request:dict)->dict:
        raw=(json.dumps(request,ensure_ascii=True,allow_nan=False)+'\n').encode()
        if len(raw)>8*1024*1024:raise ValueError('native request exceeds8MiB')
        generated=self.generated_files
        (self.out/'inputs.json').write_bytes(raw);before=tree(self.root,strict=generated is not None)
        if generated is not None and any(name in before for name in generated):raise ValueError('generated files overlap existing inputs')
        env=dict(PATH=str(self.root/'empty-path'),HOME=str(self.root/'home'),LANG='C.UTF-8',LC_ALL='C.UTF-8')
        system='macos'if platform.system()=='Darwin'else'linux'
        command=[str(self.native)]
        if system=='linux':
            tracer=shutil.which('strace')
            if not tracer:raise ValueError('actual Linux exec/connect audit required')
            command=[tracer,'--seccomp-bpf','-f','-e','trace=execve,execveat,connect','-o',str(self.out/'exec.trace'),*command];env['LD_DEBUG']='libs'
        else:
            env['DYLD_PRINT_LIBRARIES']='1'
            if self.macos_confinement:command=macos_confined_command(self.native)
        with(self.out/'stdout.json').open('wb')as stdout,(self.out/'stderr.log').open('wb')as stderr:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,cwd=self.root,env=env,start_new_session=True)
            try:process.communicate(raw,timeout=600 if generated is not None else 60)
            except BaseException:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait();raise
        receipt=dict(format='ken-native-json-execution/2'if generated is not None else'ken-native-json-execution/1',command=command,cwd=str(self.root),env=env,system=system,machine=platform.machine(),exit=process.returncode,timeout_s=600 if generated is not None else 60,native_sha256=self.binary['sha256'],request_sha256=identity(self.out/'inputs.json')['sha256'],stdout_sha256=identity(self.out/'stdout.json')['sha256'],stderr_sha256=identity(self.out/'stderr.log')['sha256'],owned_before=before,owned_after=tree(self.root,strict=generated is not None))
        if generated is not None:receipt['generated_files']=generated
        (self.out/'execution.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if identity(self.probe)!=self.binary or identity(self.native)!=self.binary:raise ValueError('native executable changed during execution')
        errors=verify_native_json(self.out,self.prefix,macos_confinement=self.macos_confinement,generated_files=generated)
        if errors:raise ValueError(errors)
        return load(self.out/'stdout.json')
    def __exit__(self,*args):self.temporary.cleanup()

def verify_native_json(out:Path,prefix:str,*,macos_confinement:bool=False,generated_files:dict|None=None)->list[str]:
    try:
        def require(value,message):
            if not value:raise ValueError(message)
        generated=generated_contract(generated_files)
        receipt=load(out/'execution.json');root=Path(receipt['cwd']);command=receipt['command'];env=receipt['env']
        fields={'format','command','cwd','env','system','machine','exit','timeout_s','native_sha256','request_sha256','stdout_sha256','stderr_sha256','owned_before','owned_after'}
        if generated is not None:fields.add('generated_files')
        require(set(receipt)==fields,'unexpected execution fields/fabricated passing summary')
        require(receipt['format']==('ken-native-json-execution/2'if generated is not None else'ken-native-json-execution/1')and receipt['exit']==0 and receipt['timeout_s']==(600 if generated is not None else 60),'native exit/timeout/protocol differs')
        require(root.is_absolute()and root.name.startswith(prefix)and command[-1]==str(root/'native-probe'),'native executable not copied outside checkout')
        require(env['PATH']==str(root/'empty-path')and env['HOME']==str(root/'home'),'native isolated environment differs')
        if generated is not None:
            require(same_value(receipt['generated_files'],generated),'generated contract differs')
            require(not any(name in receipt['owned_before']for name in generated),'generated files overlap existing inputs')
            require(same_value(receipt['owned_after'],receipt['owned_before']|generated),'native wrote/changed owned files')
        else:require(receipt['owned_before']==receipt['owned_after'],'native wrote/changed owned files')
        require(receipt['owned_before']['native-probe']['sha256']==receipt['native_sha256'],'native binary identity differs')
        for name,key in [('inputs.json','request_sha256'),('stdout.json','stdout_sha256'),('stderr.log','stderr_sha256')]:require(identity(out/name)['sha256']==receipt[key],'raw native execution bytes differ')
        loader=(out/'stderr.log').read_bytes()
        require(len(loader)<=LIMIT and b'libpython'not in loader and b'libtorch_python'not in loader,'forbidden native linkage/oversized loader log')
        if receipt['system']=='linux':
            require(len(command)==8 and Path(command[0]).name=='strace'and command[1:5]==['--seccomp-bpf','-f','-e','trace=execve,execveat,connect'],'actual exec/connect audit command differs')
            trace=(out/'exec.trace').read_text()
            require(len(re.findall(r'\bexecve(?:at)?\(',trace))==1 and command[-1]in trace and not re.search(r'\bconnect\(',trace),'unexpected native subprocess/network')
            require(env['LD_DEBUG']=='libs'and b'calling init:'in loader,'actual Linux loader audit missing')
        else:
            expected=macos_confined_command(root/'native-probe')if macos_confinement else[str(root/'native-probe')]
            require(receipt['system']=='macos'and command==expected and env['DYLD_PRINT_LIBRARIES']=='1'and b'dyld['in loader,'actual macOS loader audit/confinement missing')
        load(out/'inputs.json');load(out/'stdout.json')
        return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

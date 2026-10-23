"""One bounded native NDJSON process, outside checkout, with actual exec witness."""
from __future__ import annotations
import hashlib,json,math,os,platform,re,selectors,shlex,shutil,signal,subprocess,tempfile,time
from pathlib import Path
from .fastembed_reference import RAW_LIMIT

ROOT=Path(__file__).resolve().parents[2]
MODEL_TIMEOUT=1800
VALIDATION_DEADLINE_ENV='KEN_FASTEMBED_VALIDATION_DEADLINE'


def digest(path:Path)->str:
    with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _distinct(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate native JSON field')
        result[key]=value
    return result


def _nonfinite(value):raise ValueError('nonfinite native JSON scalar')


def decode_frames(raw:str)->list[dict]:
    if not raw or len(raw.encode())>RAW_LIMIT:raise ValueError('native output exceeds bound or is empty')
    result=[]
    for line in raw.splitlines():
        row=json.loads(line,object_pairs_hook=_distinct,parse_constant=_nonfinite)
        if type(row)is not dict:raise ValueError('native frame object required')
        result.append(row)
    return result


class NativeProbeProcess:
    """Own the process/copies; source mutation is only an external controller action."""
    def __init__(self,probe:Path,registry:Path,sources:Path,library:Path,model:str,out:Path):
        self.probe,self.registry,self.sources,self.library,self.model,self.out=probe,registry,sources,library,model,out
        self.requests=[];self.frames=[];self.process=None;self.started=None
        self.out.mkdir(parents=True,exist_ok=False)
        self.temporary=tempfile.TemporaryDirectory(prefix='ken-fastembed-native-')
        self.root=Path(self.temporary.name);self.work=self.root/'work';self.work.mkdir()
        self.copied=self.root/'fastembed-probe';self.core=self.root/'native-core';self.catalog=self.root/'registry.json'
        self.stdout=self.out/'native.stdout.ndjson';self.stderr=self.out/'native.stderr.log'
        self.output=self.stdout.open('wb');self.errors=self.stderr.open('wb')
        self.selector=selectors.DefaultSelector()

    def __enter__(self):
        try:
            for path in (self.probe,self.registry,self.sources,self.library):
                if not isinstance(path,Path)or not path.is_absolute():raise ValueError('explicit absolute native inputs required')
            if not self.probe.is_file()or not os.access(self.probe,os.X_OK):raise ValueError('native executable required')
            with self.probe.open('rb')as stream:
                if stream.read(4)not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):raise ValueError('interpreter scripts rejected')
            shutil.copy2(self.probe,self.copied);shutil.copy2(self.library,self.core);shutil.copy2(self.registry,self.catalog)
            self.identities={key:digest(path)for key,path in [('native_sha256',self.probe),('core_sha256',self.library),('registry_sha256',self.registry)]}
            sentinels=self.root/'sentinel-path';sentinels.mkdir();self.children=self.root/'children.log'
            for name in ('python','python3','ken','sh','bash','zsh'):
                path=sentinels/name;path.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(self.children))}\nexit 97\n");path.chmod(0o755)
            self.command=[str(self.copied),'--registry',str(self.catalog),'--sources',str(self.sources),'--work',str(self.work),'--runtime-library',str(self.core),'--model',self.model]
            if platform.system()=='Linux':
                tracer=shutil.which('strace')
                if not tracer:raise ValueError('actual Linux exec trace required')
                self.command=[tracer,'-f','-e','trace=execve,execveat','-o',str(self.out/'native-exec.trace'),*self.command]
            if self.root.is_relative_to(ROOT):raise ValueError('process workspace must be outside checkout')
            self.started=time.monotonic_ns();self.deadline=time.monotonic()+MODEL_TIMEOUT
            parent=os.environ.get(VALIDATION_DEADLINE_ENV)
            if parent is not None:
                bound=float(parent)
                if not math.isfinite(bound):raise ValueError('finite parent native validation deadline required')
                self.deadline=min(self.deadline,bound)
                self._remaining()
            self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,cwd=self.root,env={'PATH':str(sentinels),'HOME':str(self.root),'TOKENIZERS_PARALLELISM':'false'},bufsize=0,start_new_session=True)
            os.set_blocking(self.process.stdin.fileno(),False)
            os.set_blocking(self.process.stdout.fileno(),False)
            self.selector.register(self.process.stdout,selectors.EVENT_READ)
            return self
        except BaseException:
            self.__exit__(None,None,None);raise

    def send(self,request:dict)->dict:
        encoded=(json.dumps(request,ensure_ascii=True,allow_nan=False)+'\n').encode('utf8')
        if len(encoded)>RAW_LIMIT:raise ValueError('oversized native request')
        self.requests.append(request)
        pending=memoryview(encoded);raw=bytearray()
        self.selector.register(self.process.stdin,selectors.EVENT_WRITE)
        while pending or not raw.endswith(b'\n'):
            for key,_ in self._events():
                if key.fileobj is self.process.stdin:
                    try:written=os.write(self.process.stdin.fileno(),pending[:65536])
                    except BlockingIOError:continue
                    pending=pending[written:]
                    if not pending:self.selector.unregister(self.process.stdin)
                else:
                    chunk=self._read()
                    if chunk is None:continue
                    if not chunk:raise ValueError('missing or incomplete native frame')
                    raw.extend(chunk)
                    if len(raw)>RAW_LIMIT:raise ValueError('oversized native frame')
                    if b'\n' in raw and (not raw.endswith(b'\n') or raw.count(b'\n')!=1):
                        raise ValueError('unexpected extra native frame')
        rows=decode_frames(raw.decode('utf8'))
        if len(rows)!=1 or rows[0].get('id')!=request.get('id'):raise ValueError('native request/frame identity mismatch')
        self.frames.append(rows[0]);return rows[0]

    def _remaining(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('native model process deadline')
        return remaining

    def _events(self):
        events=self.selector.select(self._remaining())
        if not events:raise TimeoutError('native model process deadline')
        return events

    def _read(self):
        try:chunk=os.read(self.process.stdout.fileno(),65536)
        except BlockingIOError:return None
        if chunk:self.output.write(chunk);self.output.flush()
        return chunk

    def _terminate(self):
        # A separate session owns both strace and its native tracee on Linux.
        # Kill that group, not just the tracer, and reap our direct child.
        try:os.killpg(self.process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:self.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            self.process.wait(timeout=0.5)
        finally:
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def __exit__(self,kind,value,traceback):
        failure=None
        try:
            if self.process is not None:
                if kind is not None:
                    self._terminate()
                    return
                self.process.stdin.close()
                while True:
                    self._events();extra=self._read()
                    if extra is None:continue
                    if extra:raise ValueError('native process emitted extra output')
                    break
                self.process.wait(timeout=self._remaining())
                ended=time.monotonic_ns()
                self.output.flush();self.errors.flush()
                children=self.children.read_text().splitlines()if self.children.exists()else[]
                attempts=None
                if platform.system()=='Linux':
                    lines=[line for line in (self.out/'native-exec.trace').read_text().splitlines()if re.search(r'\bexecve(?:at)?\(',line)]
                    attempts=len(lines)
                    if attempts!=1 or str(self.copied)not in lines[0]:raise ValueError('only initial native exec allowed')
                if self.process.returncode or children:raise ValueError('native process failed or executed a child')
                for original,copied,key in [(self.probe,self.copied,'native_sha256'),(self.library,self.core,'core_sha256'),(self.registry,self.catalog,'registry_sha256')]:
                    if digest(original)!=self.identities[key]or digest(copied)!=self.identities[key]:raise ValueError('native executable/core/registry changed')
                owned=list(self.work.iterdir())
                if owned:raise ValueError('native session left owned temporary files after exit')
                self.report={**self.identities,'native_exit':self.process.returncode,'native_process_wall_ns':ended-self.started,'outside_checkout':True,'native_children':children,'exec_attempts':attempts,'owned_after_exit':[],'command':self.command}
        except BaseException as error:
            failure=error
            if self.process is not None:self._terminate()
        finally:
            if self.process is not None:
                self.process.stdin.close();self.process.stdout.close()
            self.selector.close();self.output.close();self.errors.close();self.temporary.cleanup()
        if kind is None and failure is not None:raise failure

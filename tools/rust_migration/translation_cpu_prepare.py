"""Publish pinned CT2 CPU libraries and headers without a Python model import."""
from pathlib import Path,PurePosixPath
from contextlib import contextmanager
import hashlib,json,os,platform,shutil,stat,tarfile,tempfile,zipfile
from .native_core_prepare import verified_archive
from .native_binary import check_native_architecture
from .native_json import identity,load

REGISTRY='tools/rust_migration/data/translation-cpu-core.json'

def relative(name):
    path=PurePosixPath(name)
    if not name or path.is_absolute()or'..'in path.parts or str(path)!=name:
        raise ValueError('unsafe translation SDK member')
    return Path(name)

def registration(repo):
    value=load(Path(repo)/REGISTRY)
    if (value.get('format'),value.get('os'),value.get('arch'),value.get('version'),value.get('abi'))!=('ken-translation-cpu-core/1','linux','x86_64','4.8.2',1):
        raise ValueError('registered Linux x86 translation CPU core required')
    core=load(Path(repo)/relative(value['runtime_registration']))
    if core['format']!='ken-native-translation-core/1':raise ValueError('native translation core registry differs')
    rows=[row for row in core['runtimes']if(row['os'],row['arch'],row['version'])==('linux','x86_64','4.8.2')]
    if len(rows)!=1:raise ValueError('one registered native translation core required')
    value['libraries']=rows[0]['libraries']
    for name in value['libraries']:
        if len(relative(name).parts)!=1:raise ValueError('native core basename required')
    for name,row in value['header_files'].items():relative(name);relative(row['member'])
    return value

def expected_files(record):
    files={'lib/'+name:row for name,row in record['libraries'].items()}
    for name,row in record['header_files'].items():
        if name in files:raise ValueError('duplicate translation SDK destination')
        files[name]={key:row[key]for key in('bytes','sha256')}
    return files

@contextmanager
def opened_archive(path,wanted):
    if path.is_symlink():raise ValueError('native SDK source cannot be a symlink')
    with path.open('rb')as stream:
        if os.fstat(stream.fileno()).st_size!=wanted['bytes']or hashlib.file_digest(stream,'sha256').hexdigest()!=wanted['sha256']:
            raise ValueError('native SDK source changed before extraction')
        stream.seek(0);yield stream

def copy_member(source,destination,wanted):
    destination.parent.mkdir(parents=True,exist_ok=True);count=0;digest=hashlib.sha256()
    with destination.open('xb')as output:
        while chunk:=source.read(1024*1024):
            count+=len(chunk)
            if count>wanted['bytes']:raise ValueError('oversized translation SDK member')
            digest.update(chunk);output.write(chunk)
    if dict(bytes=count,sha256=digest.hexdigest())!={key:wanted[key]for key in('bytes','sha256')}:
        raise ValueError('translation SDK member differs from registered source')

def verify_sdk(out,repo):
    try:
        out=Path(out);record=registration(repo);expected=expected_files(record);saved=load(out/'PREPARATION.json')
        wanted=dict(format='ken-translation-cpu-sdk/1',os='linux',arch='x86_64',version='4.8.2',
                    source_wheel=record['wheel'],source_headers=record['headers'],files=expected,python_runtime_imported=False)
        if saved!=wanted:raise ValueError('translation SDK manifest differs from registered sources')
        paths={p.relative_to(out).as_posix()for p in out.rglob('*')if p.is_file()or p.is_symlink()}
        if paths!=set(expected)|{'PREPARATION.json'}:raise ValueError('translation SDK inventory differs')
        for name,wanted in expected.items():
            path=out/relative(name)
            if path.is_symlink()or identity(path)!=wanted:raise ValueError('translation SDK bytes differ: '+name)
        for name in record['libraries']:check_native_architecture(out/'lib'/name,('linux','x86_64'))
        return[]
    except(OSError,ValueError,KeyError,TypeError)as error:return[str(error)]

def prepare(repo,cache,out):
    repo,cache,out=map(Path,(repo,cache,out))
    if out.exists()or out.is_symlink():raise ValueError('fresh translation SDK destination required')
    if (platform.system(),platform.machine())!=('Linux','x86_64'):
        raise ValueError('Linux x86 translation SDK host required')
    if any(not p.is_absolute()for p in(repo,cache,out)):raise ValueError('absolute translation SDK paths required')
    record=registration(repo);wheel=verified_archive(record['wheel'],cache);headers=verified_archive(record['headers'],cache)
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.translation-sdk-',dir=out.parent)as directory:
        stage=Path(directory)/'ready';stage.mkdir()
        with opened_archive(wheel,record['wheel'])as archive,zipfile.ZipFile(archive)as stream:
            for name,wanted in record['libraries'].items():
                members=[m for m in stream.infolist()if m.filename=='ctranslate2.libs/'+name]
                if len(members)!=1 or members[0].is_dir()or stat.S_ISLNK(members[0].external_attr>>16):
                    raise ValueError('one regular native translation library required')
                with stream.open(members[0])as source:copy_member(source,stage/'lib'/name,wanted)
        with opened_archive(headers,record['headers'])as archive,tarfile.open(fileobj=archive,mode='r:gz')as stream:
            members=stream.getmembers()
            for name,wanted in record['header_files'].items():
                matches=[m for m in members if m.name==wanted['member']]
                if len(matches)!=1 or not matches[0].isfile():raise ValueError('one regular translation header/license required')
                with stream.extractfile(matches[0])as source:copy_member(source,stage/relative(name),wanted)
        saved=dict(format='ken-translation-cpu-sdk/1',os='linux',arch='x86_64',version='4.8.2',
                   source_wheel=record['wheel'],source_headers=record['headers'],files=expected_files(record),python_runtime_imported=False)
        (stage/'PREPARATION.json').write_text(json.dumps(saved,indent=2)+'\n')
        if errors:=verify_sdk(stage,repo):raise ValueError('; '.join(errors))
        if out.exists()or out.is_symlink():raise ValueError('translation SDK destination already exists')
        stage.rename(out)
    return saved

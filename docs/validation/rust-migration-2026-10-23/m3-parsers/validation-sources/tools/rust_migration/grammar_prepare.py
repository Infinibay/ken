"""Prepare authenticated C grammar resources; native parsing never calls this."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
import platform,shutil,subprocess,tarfile,tempfile,urllib.request


def native_platform()->str:
    system={'Darwin':'macos','Linux':'linux'}.get(platform.system())
    machine={'arm64':'arm64'if system=='macos'else'aarch64','aarch64':'aarch64','x86_64':'x86_64'}.get(platform.machine())
    if system is None or machine is None:raise ValueError('unsupported native grammar platform')
    return system+'-'+machine


def _identity(path:Path,expected:dict)->bool:
    return path.is_file()and not path.is_symlink()and path.stat().st_size==expected['bytes']and hashlib.sha256(path.read_bytes()).hexdigest()==expected['sha256']


def _manifest(lock:dict,system:str)->dict:
    pack=lock['pack'];bundle=pack['bundles'][system];libraries=[]
    for language,row in sorted(bundle['libraries'].items()):
        filename=row['file']
        if not isinstance(filename,str)or Path(filename).name!=filename or filename in {'.','..'}:
            raise ValueError('unsafe grammar filename')
        libraries.append(dict(language=language,file=filename,bytes=row['bytes'],sha256=row['sha256']))
    if len({r['file']for r in libraries})!=len(libraries):raise ValueError('duplicate grammar filename')
    return dict(format='ken-native-grammars/1',platform=system,pack_version=pack['version'],pack_revision=pack['revision'],libraries=libraries)


def prepare_grammars(lock:dict,cache:Path,destination:Path)->dict:
    """Verify the complete bundle before streaming only selected members to staging."""
    if lock['format']!='ken-grammar-lock/1':raise ValueError('wrong grammar lock format')
    system=native_platform();expected=_manifest(lock,system);bundle=lock['pack']['bundles'][system]
    rows=bundle['libraries']
    if destination.exists():
        path=destination/'manifest.json'
        if destination.is_symlink()or not path.is_file()or json.loads(path.read_bytes())!=expected:
            raise ValueError('prepared grammar manifest differs')
        for language,row in rows.items():
            license=destination/'licenses'/(language+'.txt')
            if not _identity(destination/row['file'],row)or not license.is_file()or license.read_text()!=row['license']['text']:
                raise ValueError('prepared grammar bytes differ: '+language)
        return expected
    cache.mkdir(parents=True,exist_ok=True)
    archive=cache/Path(bundle['url']).name
    if not archive.exists():
        if not 0<bundle['bytes']<=128*1024*1024:raise ValueError('bundle size exceeds bound')
        with urllib.request.urlopen(bundle['url'],timeout=30)as response:raw=response.read(bundle['bytes']+1)
        if len(raw)!=bundle['bytes']or hashlib.sha256(raw).hexdigest()!=bundle['sha256']:raise ValueError('bundle identity differs')
        temporary=cache/(archive.name+'.part')
        try:temporary.write_bytes(raw);temporary.replace(archive)
        finally:temporary.unlink(missing_ok=True)
    if not _identity(archive,bundle):raise ValueError('bundle identity differs')
    zstd=shutil.which('zstd')
    if zstd is None:raise ValueError('grammar preparation requires the native zstd build tool')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.ken-grammars-',dir=destination.parent))
    try:
        wanted={row['file']:language for language,row in rows.items()};seen=set()
        with subprocess.Popen([zstd,'-q','-d','-c',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)as process:
            try:
                with tarfile.open(fileobj=process.stdout,mode='r|')as tar:
                    for member in tar:
                        name=Path(member.name).name
                        if name not in wanted:continue
                        if name in seen:raise ValueError('ambiguous grammar archive member: '+name)
                        language=wanted[name];row=rows[language]
                        if not member.isfile()or member.size!=row['bytes']:raise ValueError('grammar member identity differs: '+name)
                        stream=tar.extractfile(member)
                        if stream is None:raise ValueError('missing grammar payload: '+name)
                        raw=stream.read(row['bytes']+1)
                        if len(raw)!=row['bytes']or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('grammar member identity differs: '+name)
                        (stage/name).write_bytes(raw);seen.add(name)
                # Drain tar's record padding before waiting for the decompressor.
                while process.stdout.read(65536):pass
                stderr=process.stderr.read(16384)
                if process.wait(timeout=30):raise ValueError('native decompression failed: '+stderr.decode(errors='replace'))
            finally:
                if process.poll()is None:process.kill();process.wait(timeout=10)
        if seen!=set(wanted):raise ValueError('missing grammar archive members')
        licenses=stage/'licenses';licenses.mkdir()
        for language,row in rows.items():(licenses/(language+'.txt')).write_text(row['license']['text'])
        (stage/'NOTICE.json').write_text(json.dumps({g:{k:row[k]for k in ('revision','license')}for g,row in sorted(rows.items())},indent=2)+'\n')
        (stage/'manifest.json').write_text(json.dumps(expected,indent=2)+'\n')
        stage.rename(destination)
        return expected
    finally:
        if stage.exists():shutil.rmtree(stage)

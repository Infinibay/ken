"""Content identity of the installed Snowball dependency used by the original."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from .native_json import load,identity
from .reference import Reference,reference_env
ORIGINAL_FILES={
 'english_stemmer.py':dict(bytes=23731,sha256='5a70f664d5bcc3a3f0e241d63dc00aa2c8e6549f8d002fa5f8bc4ed45e239130'),
 'basestemmer.py':dict(bytes=8164,sha256='40b1347f08eafdca080bb8358c4c56f94f06af63d4610fde84e64f17ba34d0ec'),
 'among.py':dict(bytes=404,sha256='ebed9da6bee0a46b48be26c92714a09d2d903e40a3006e70f2c90fdccf41e7eb')}
SCRIPT=r'''
import hashlib,importlib.metadata,json,pathlib,platform,snowballstemmer
root=pathlib.Path(snowballstemmer.__file__).parent
value=dict(format='ken-original-snowball/2',distribution=importlib.metadata.version('snowballstemmer'),python=platform.python_version(),files={name:dict(bytes=(root/name).stat().st_size,sha256=hashlib.sha256((root/name).read_bytes()).hexdigest())for name in ['english_stemmer.py','basestemmer.py','among.py']},factory=dict(path=str(root/'__init__.py'),bytes=(root/'__init__.py').stat().st_size,sha256=hashlib.sha256((root/'__init__.py').read_bytes()).hexdigest()),runtime=dict(system=platform.system(),machine=platform.machine()))
print(json.dumps(value,sort_keys=True))
'''
ORIGINAL_FACTORY=dict(bytes=2932,sha256="c49181c971ec472ca30d6bb1cfa1ab4507c52a69d6bf7e5d9d587eb313a0e261")
def validate_original(value:dict)->list[str]:
    return []if(value.get('format')=='ken-original-snowball/2'and value.get('distribution')=='3.0.1'and value.get('python')=='3.12.9'and value.get('files')==ORIGINAL_FILES and all(value.get('factory',{}).get(k)==v for k,v in ORIGINAL_FACTORY.items()))else['original Snowball sources/runtime differ']
def capture_original(reference:Reference,out:Path):
    target=out/'SNOWBALL-REFERENCE.json'
    if target.exists():
        value=load(target)
        if validate_original(value):raise ValueError('original Snowball dependency differs')
        return value
    (out/'snowball-capture.py').write_text(SCRIPT)
    proc=subprocess.run([str(reference.python),str(out/'snowball-capture.py')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'snowball-stdout.json').write_bytes(proc.stdout);(out/'snowball-stderr.log').write_bytes(proc.stderr);(out/'snowball-exit.json').write_text(json.dumps(dict(exit=proc.returncode)))
    if proc.returncode:raise ValueError('original Snowball dependency process failed')
    value=json.loads(proc.stdout);errors=validate_original(value)
    if errors:raise ValueError(errors)
    value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),execution=dict(exit=proc.returncode,files={n:identity(out/n)for n in ['snowball-capture.py','snowball-stdout.json','snowball-stderr.log','snowball-exit.json']}))
    target.write_text(json.dumps(value,indent=2)+'\n');return value

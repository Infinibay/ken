"""Complete original import comparison and actual two-mode native acquisition."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from .native_json import NativeJsonCapture,identity,load
FIXTURES=('import-reference','import-alias-edges','import-alias-surrogates','import-language-edges','import-review-regressions')

def source_identity(repo:Path)->dict:
    files=[repo/p for p in ('Cargo.toml','Cargo.lock','rust-toolchain.toml')]
    files+=sorted(p for crate in ('ken-core','ken-text') for p in(repo/'crates'/crate).rglob('*')if p.is_file())
    return {str(p.relative_to(repo)):identity(p)for p in files}

def import_cases(repo:Path)->list[dict]:
    cases=[]
    for name in FIXTURES:
        for row in load(repo/'crates/ken-core/tests/fixtures'/(name+'.json'))['cases']:
            cases.append(dict(id=name+':'+row['id'],input=row['input'],**{k:row[k]for k in ('error','results')if k in row}))
    return cases

def compare_import_observations(cases:list[dict],actual:dict)->list[str]:
    try:
        def require(value,message):
            if not value:raise ValueError(message)
        require(set(actual)=={'format','cases'}and actual['format']=='ken-import-observation/1','wrong import observation protocol')
        expected=[(mode+':'+case['id'],case)for case in cases for mode in ('inputs','project')]
        require(len(actual['cases'])==len(expected),'missing/duplicate native import cases')
        for row,(name,case)in zip(actual['cases'],expected,strict=True):
            require(row['id']==name,'native import identity/order differs')
            if'error'in case:
                error=row.get('error',{})
                require(set(row)=={'id','error'}and case['error']['type']=='AttributeError'and set(error)=={'kind','path','reason'}and error['kind']=='invalid_config'and error['path']in case['input']['configs']and type(error['reason'])is str and bool(error['reason']),'original config failure differs/swallowed')
            else:require(set(row)=={'id','results'}and row['results']==case['results'],'complete ordered import targets/classifications differ: '+name)
        return []
    except(ValueError,KeyError,TypeError)as error:return[str(error)]

def requests(cases:list[dict],root:Path)->tuple[dict,list[dict]]:
    rows=[];resources=[]
    for index,case in enumerate(cases):
        data=case['input'];rows.append(dict(id='inputs:'+case['id'],files=data['files'],imports=data['imports'],source=dict(kind='inputs',configs=data['configs'])))
        project=None
        if data['configs']is not None:
            project=root/'projects'/f'{index:04d}'
            for name,hex in data['configs'].items():
                path=Path(name)
                if path.is_absolute()or'..'in path.parts:raise ValueError('safe relative original config identity required')
                raw=bytes.fromhex(hex)
                resources.append(dict(path=str((project/path).relative_to(root)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        rows.append(dict(id='project:'+case['id'],files=data['files'],imports=data['imports'],source=dict(kind='project',root=str(project)if project is not None else None)))
    return dict(cases=rows),sorted(resources,key=lambda r:r['path'])

def run_import_capture(repo:Path,probe:Path,cases:list[dict],out:Path)->dict:
    before=source_identity(repo)
    with NativeJsonCapture(probe,out,repo=repo,prefix='ken-import-process-')as process:
        request,resources=requests(cases,process.root)
        for index,case in enumerate(cases):
            if case['input']['configs']is None:continue
            project=process.root/'projects'/f'{index:04d}';project.mkdir(parents=True)
            for name,hex in case['input']['configs'].items():
                path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(bytes.fromhex(hex))
        (out/'SOURCES.json').write_text(json.dumps(before,indent=2)+'\n')
        actual=process.run(request)
        build=dict(format='ken-import-build/1',sources=before,native_sha256=process.binary['sha256'],resources=resources)
        (out/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
        if source_identity(repo)!=before:raise ValueError('native import sources changed during execution')
    from .import_evidence import verify_import_capture
    errors=verify_import_capture(out,cases)
    if errors:raise ValueError(errors)
    return build

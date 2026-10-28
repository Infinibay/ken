"""Authenticate the independently observed Linux x86 translation histories."""
from pathlib import Path
from dataclasses import replace
from importlib.metadata import version
import gzip,hashlib,json,platform,sys,unicodedata

from .execution_profiles import authenticate_frozen,FP
from .translation_reference import capture as observe,_CHILD,translation_cases

FIXTURE='crates/ken-models/tests/fixtures/translation-linux-x86_64.json.gz'
REFERENCE_ID={'bytes':12338,'sha256':'97815693b2aef5441f887685623025260360fdfb6c8d888637f8b1582b7a7f00'}
OBSERVER_SHA='b4f0d0c95d7172296ac999ae7fc0a70f27f9bd770958b859c9af82a04df55809'
DEFINITION_SHA='1af342f7677e9f51477171000e5aa6e6527590a715f064bd64679c1aa491a9f0'
MODULE_HASHES={
    'ken.model_assets':'a1ee77827cc4dc48e10f28b93f8deab9d3644e13edae4b2d22971dfbe81679fe',
    'ken.retrieval.query_expansion':'aa148e5337038b6a32bbc09ef08cd5c59b1dab5ec8dbf2e085b88c58a49b09b7',
    'ken.retrieval.translation_preparation':'677dada3a32969617b1febaa3fd89750975ad8ae2900b407acd0f37d5ab2faed',
}
RUNTIME={'ctranslate2':'4.8.2','sentencepiece':'0.2.1'}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def validate(value):
    def require(condition,message):
        if not condition:raise ValueError(message)
    try:
        require(value['format']=='ken-translation-oracle/1','oracle format differs')
        require((value['platform'],value['architecture'])==('Linux','x86_64'),'oracle is not Linux x86_64')
        require(value['reference_fingerprint']==FP,'frozen source fingerprint differs')
        oracle=value['oracle']
        require(oracle['frozen_import']is True and oracle['module_hashes']==MODULE_HASHES,'frozen translation modules differ')
        require(oracle['runtime']==RUNTIME and oracle['unicode']=='15.0.0'and oracle['stderr']=='','original runtime differs')
        require(value['observer_sha256']==OBSERVER_SHA,'original observer differs')
        definition=value['definition']
        require(digest(definition)==DEFINITION_SHA and value['recipe_sha256']==DEFINITION_SHA,'translation definition/recipe differs')
        require(value['source_artifacts']==definition['source']['artifacts'],'source artifact inventory differs')
        require(value['prepared_artifacts']==definition['derived']['artifacts'],'prepared artifact inventory differs')
        cases=translation_cases()
        require(value['cases']==cases,'translation inputs differ')
        rows=value['results']
        require([r['id']for r in rows]==[c['id']for c in cases],'missing, duplicate or reordered histories')
        require(value['results_sha256']==digest(rows),'translation observations differ')
        for case,row in zip(cases,rows,strict=True):
            require(set(row)=={'id','calls','constructor_ns','identity','revision','actual_runtime'},'foreign history fields')
            require(len(row['calls'])==len(case['queries']),'translation call count differs')
            runtime=row['actual_runtime']
            if runtime:
                require(set(runtime)=={'device','compute_type','replicas'}and runtime['device']=='cpu'
                        and runtime['compute_type']in('int8','int8_float32')and runtime['replicas']==1,'original CPU int8 runtime differs')
            for call in row['calls']:
                require(type(call['runtime_loaded'])is bool and isinstance(call['trace'],dict),'invalid translation trace')
                require(('output'in call)^('error'in call),'one translation output or error required')
                require(type(call['wall_ns'])is int and call['wall_ns']>0,'invalid translation measurement')
        return[]
    except(KeyError,TypeError,ValueError,AttributeError)as error:
        return[str(error)]

def load(repo):
    path=Path(repo)/FIXTURE
    try:
        raw=path.read_bytes()
        identity=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        if identity!=REFERENCE_ID:raise ValueError('identity differs')
        value=json.loads(gzip.decompress(raw))
        if errors:=validate(value):raise ValueError('; '.join(errors))
        return value
    except(OSError,ValueError,EOFError)as error:
        raise ValueError('preserved x86 translation reference required: '+str(error))from error

def capture(reference,source,out):
    out=Path(out)
    if out.exists()or out.is_symlink():raise FileExistsError(out)
    if (platform.system(),platform.machine())!=('Linux','x86_64'):
        raise ValueError('Linux x86_64 original observer required')
    if platform.python_version()!='3.12.9'or unicodedata.unidata_version!='15.0.0'or {p:version(p)for p in RUNTIME}!=RUNTIME:
        raise ValueError('pinned original translation runtime required')
    if hashlib.sha256(_CHILD.encode()).hexdigest()!=OBSERVER_SHA:
        raise ValueError('registered original observer differs')
    authenticate_frozen(reference)
    out.mkdir(parents=True,exist_ok=False)
    (out/'capture.py').write_text(_CHILD)
    definition=json.loads((reference.root/'src/ken/embedder/data/es-en-ct2-int8.json').read_bytes())
    if digest(definition)!=DEFINITION_SHA:raise ValueError('registered translation definition differs')
    (out/'inputs.json').write_text(json.dumps(dict(cases=translation_cases(),definition=definition,source=str(Path(source).absolute()),reference_fingerprint=FP),indent=2)+'\n')
    # The frozen manifest's old executable can be a different local venv. The
    # declared interpreter above owns this observation; frozen contents stay intact.
    observed=observe(replace(reference,python=Path(sys.executable).absolute()),Path(source),out/'observations.json',journal=out/'records.jsonl')
    observed.update(observer_sha256=OBSERVER_SHA,results_sha256=digest(observed['results']))
    if [json.loads(line)for line in(out/'records.jsonl').read_text().splitlines()]!=observed['results']:
        raise ValueError('immediate original journal differs')
    if errors:=validate(observed):raise ValueError('; '.join(errors))
    (out/'reference.json').write_text(json.dumps(observed,ensure_ascii=True,indent=2)+'\n')
    return observed

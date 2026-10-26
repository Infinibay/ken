"""Select immutable original data by descriptor, without consulting native answers."""
from pathlib import Path
import argparse,gzip,json
from .native_json import identity,load,same_value
from .execution_profiles import verify_capture,fingerprint,require,FP
INDEX='crates/ken-models/tests/fixtures/execution-profiles/index.json'
LEGACY_CONTEXT='crates/ken-models/tests/fixtures/context/linux-x86_64-original.json'
LEGACY_ALIGNMENT='crates/ken-retrieval/tests/fixtures/numeric-reference-alignment-linux-x86_64.json.gz'
def semantic(kind,original):
    if kind=='alignment':return original['cases']
    keys=('definition','artifacts','dimension','spec','spec_key','tokenizer_revision','cases','tolerances')
    return {key:original[key]for key in keys}|dict(results=[dict(id=r['id'],calls=r['calls'])for r in original['results']])
def read_reference(repo,reference):
    path=Path(reference['path']);require(bool(reference['path'])and not path.is_absolute()and'..'not in path.parts,'unsafe reference path')
    require(identity(repo/path)=={k:reference[k]for k in('bytes','sha256')},'reference bytes differ')
    raw=(repo/path).read_bytes()
    if reference['encoding']=='gzip':raw=gzip.decompress(raw)
    else:require(reference['encoding']=='json','reference encoding differs')
    return json.loads(raw)
def select(repo,kind,descriptor):
    registry=load(repo/INDEX);require(registry['format']=='ken-execution-reference-registry/1','registry format differs')
    entries=[entry for entry in registry['families'].get(kind,[])if same_value(entry['descriptor'],descriptor)]
    require(len(entries)==1,'unregistered or ambiguous '+kind+' execution profile')
    entry=entries[0];require(entry['id']==fingerprint(descriptor),'descriptor identity differs')
    return entry,read_reference(repo,entry['reference'])
def register(repo,captures):
    path=repo/INDEX;require(not path.exists(),'registry already exists')
    grouped={'context':{},'alignment':{}}
    for directory in captures:
        errors=verify_capture(directory,repo);require(not errors,str(errors));manifest=load(directory/'CAPTURE.json')
        for kind,profiles in grouped.items():
            ident=manifest['ids'][kind];original=load(directory/(kind+'.json'))
            origin=dict(candidate=manifest['candidate'],capture=identity(directory/'CAPTURE.json'),original=identity(directory/(kind+'.json')),reference_fingerprint=FP)
            if ident in profiles:
                require(same_value(semantic(kind,profiles[ident]['original']),semantic(kind,original)),'conflicting original observations for '+ident)
                profiles[ident]['origins'].append(origin)
            else:profiles[ident]=dict(descriptor=manifest['descriptors'][kind],original=original,origins=[origin])
    legacy={'context':load(repo/LEGACY_CONTEXT),'alignment':json.loads(gzip.decompress((repo/LEGACY_ALIGNMENT).read_bytes()))}
    path.parent.mkdir(parents=True,exist_ok=True);registry=dict(format='ken-execution-reference-registry/1',families={})
    for kind,profiles in grouped.items():
        entries=[]
        for ident,value in sorted(profiles.items()):
            if same_value(semantic(kind,value['original']),semantic(kind,legacy[kind])):
                relative=LEGACY_CONTEXT if kind=='context'else LEGACY_ALIGNMENT
            else:
                relative=str(Path(INDEX).parent/(kind+'-'+ident+('.json'if kind=='context'else'.json.gz')))
                raw=(json.dumps(value['original'],ensure_ascii=True,indent=2,allow_nan=False)+'\n').encode()
                (repo/relative).write_bytes(raw if kind=='context'else gzip.compress(raw,mtime=0))
            resource=dict(path=relative,encoding='json'if kind=='context'else'gzip',**identity(repo/relative))
            entries.append(dict(id=ident,descriptor=value['descriptor'],reference=resource,origins=value['origins']))
        registry['families'][kind]=entries
    path.write_text(json.dumps(registry,indent=2)+'\n');return registry
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,default=Path.cwd());parser.add_argument('captures',type=Path,nargs='+');args=parser.parse_args();registry=register(args.repo,args.captures);print({kind:len(entries)for kind,entries in registry['families'].items()})

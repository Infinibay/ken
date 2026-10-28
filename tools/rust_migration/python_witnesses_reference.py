"""Independent Python3.12 operation observations; never executes original pytest roots."""
from pathlib import Path
import dataclasses,gzip,hashlib,json,subprocess,sys
from .reference import Reference,reference_env
from .execution_profiles import authenticate_frozen,FP
from .native_json import load,same_value,identity
FIXTURE='crates/ken-retrieval/tests/fixtures/python-witnesses-reference.json.gz'
def cases():
    rows=[]
    def add(name,body,header='def selected():',path='sample.py',manual=None):
        source=header+'\n'+''.join('    '+line+'\n'for line in body.split('\n'))
        rows.append(dict(id=name,files={path:source},manual=manual))
    basic=[('empty','pass'),('call','return action()'),('stored','return action'),('lambda','return lambda: action()'),('nested-function','def later(x=action()):\n    return action()\nreturn later'),('nested-class','class Later:\n    x = action()\nreturn Later'),('nested-async','async def later():\n    return action()\nreturn later'),('generator','return (action(x) for x in items)'),('comprehension','return [action(x) for x in items]'),('refresh','return flag or (flag := action())'),('refresh-three','return flag or (flag := action()) or other'),('refresh-nested-or','return flag or ((flag := action()) or other)'),('refresh-grouped','return (flag or (flag := action()))'),('refresh-member','return state.flag or (flag := action())'),('refresh-other','return flag or (other := action())'),('refresh-nocall','return flag or (flag := value)'),('refresh-and','return flag and (flag := action())'),('cause','raise ValueError() from error'),('cause-none','raise ValueError() from None'),('cause-zero','raise ValueError() from 0'),('cause-attribute','raise errors.ValueError() from error'),('cause-uncalled','raise ValueError from error'),('cause-nested','def later():\n    raise TypeError() from error\nreturn later')]
    for prefix,header in(('function','def selected():'),('async','async def selected():'),('class','class selected:')):
        for name,body in basic:add(prefix+'-'+name,body,header)
    keys=[('quotes',"'key'",'"key"'),('parentheses','(key)','key'),('hex','0x10','16'),('octal','0o20','16'),('binary','0b10000','16'),('float','1e0','1.0'),('complex','1e0j','1.0j'),('big-int','0xffffffffffffffffffffffff','79228162514264337593543950335'),('name-nfkc','K','K'),('member-nfkc','obj.K','obj.K'),('unicode-escape',"'\\u0061'","'a'"),('named-character',"'\\N{LATIN SMALL LETTER A}'","'a'"),('adjacent',"'a' 'b'","'ab'"),('raw-string',"r'\\n'","'\\\\n'"),('surrogate',"'\\ud800'","'\\ud800'"),('surrogate-different',"'\\ud800'","'\\ud801'"),('surrogate-replacement',"'\\ud800'","'�'"),('u-kind',"u'a'","'a'"),('u-kind-same',"u'a'","u'\\x61'"),('bytes',"b'\\x61'","b'a'"),('bytes-string',"b'a'","'a'"),('bool-int','True','1'),('int-float','1','1.0'),('tuple','(a,b)','a,b'),('list','[a,b]','[a,b]'),('dict',"{'a':1}",'{"a":0x1}'),('set','{0x1,0x2}','{1,2}'),('binop','a + 0x1','a+1'),('boolop','a or b','(a or b)'),('bool-nested','a or (b or c)','a or b or c'),('compare','a < b <= c','(a<b<=c)'),('call','f(0x10, x="a")',"f(16,x='a')"),('if','a if c else b','(a if c else b)'),('lambda','lambda x=0x10:x','lambda x=16:x'),('listcomp','[x for x in xs if x]','[x for x in xs if x]'),('dictcomp','{x:y for x,y in xs}','{x:y for x,y in xs}'),('setcomp','{x for x in xs}','{x for x in xs}'),('generator','(x for x in xs)','(x for x in xs)'),('subscript','m[(a,b)]','m[a,b]'),('slice','m[1:2:3]','m[0x1:0x2:0x3]'),('ellipsis','...','...'),('none','None','None'),('fstring',"f'{x}'",'f"{x}"'),('fstring-debug',"f'{x=}'","f'x={x!r}'"),('fstring-format',"f'{x:{w}}'",'f"{x:{w}}"'),('fstring-constant',"f'abc'","'abc'"),('fstring-surrogate',"f'\\ud800{x}'","f'\\ud801{x}'"),('fstring-nested-quotes','f"{m["key"]}"',"f'{m[\"key\"]}'")]
    for name,left,right in keys:
        add('snapshot-'+name,f'old = mapping.get({left}, None)\nmapping[{right}] = new\nlog.append((mapping, {right}, old))')
    triple='old = mapping.get(key, None)\nmapping[key] = new\nlog.append((mapping,key,old))'
    for name,prefix in(('body',''),('if','if cond:'),('else','if cond:\n    pass\nelse:'),('for','for x in xs:'),('for-else','for x in xs:\n    pass\nelse:'),('while','while cond:'),('with','with manager:'),('try','try:'),('except','try:\n    pass\nexcept Error:'),('finally','try:\n    pass\nfinally:'),('match','match value:\n    case _:')):
        body=triple if not prefix else prefix+'\n'+''.join(('        'if name=='match'else'    ')+l+'\n'for l in triple.splitlines()).rstrip()
        if name=='try':body+='\nfinally:\n    pass'
        add('block-'+name,body)
    for name,body in [('comments',triple.replace('\n','\n# independent comment\n')),('intervening-pass',triple.replace('\n','\npass\n',1)),('semicolon','; '.join(triple.splitlines())),('chained-read',triple.replace('old =','a = old =',1)),('different-map',triple.replace('mapping[key] =','other[key] =')),('wrong-record',triple.replace(',old)',',other)')),('tuple-record',triple.replace('((mapping,key,old))','([mapping,key,old])')),('keyword-get',triple.replace('get(key, None)','get(key=key)')),('star-get',triple.replace('get(key, None)','get(*keys)')),('multiple-triples',triple+'\n'+triple),('unicode-flag','return K or (K := action())'),('signature-default','return value')]:
        add('edge-'+name,body,header='def selected(value=action()):'if name=='signature-default'else'def selected():')
    # Explicit owners make invalid/otherwise unextracted syntax observable without replacing the observer.
    for name,source in [('invalid','def selected():\n    action(\n'),('null','def selected():\n    action()\n\0'),('unrelated-invalid','def selected():\n    action()\n???\n'),('future-template','def selected():\n    return t"{action()}"\n'),('future-type-default','def selected[T=int]():\n    action()\n'),('unicode-new','\u1c89 = 1\ndef selected():\n    action()\n'),('duplicate-parameters','def selected(x,x):\n    action()\n'),('return-outside','return 1\ndef selected():\n    action()\n')]:
        lines=source.splitlines();start=2 if name=='unicode-new'else 1;end=start+1
        rows.append(dict(id='admission-'+name,files={'sample.py':source},manual=[dict(name='selected',start=start,end=end)]))
    for name,source,key,start,end in [('nfkc-raw','def K():\n    action()\n','K',1,2),('nfkc-normalized','def K():\n    action()\n','K',1,2),('cropped','def selected():\n    action()\n# tail\n','selected',2,2),('expanded','def selected():\n    action()\n# tail\n','selected',1,3),('ambiguous','class selected:\n    class selected:\n        action()\n','selected',1,3)]:
        rows.append(dict(id='owner-'+name,files={'sample.py':source},manual=[dict(name=key,start=start,end=end)]))
    add('stub-call','return action()',path='sample.pyi',manual=[dict(name='selected',start=1,end=2)])
    return rows
SCRIPT=r'''
import dataclasses,hashlib,json,pathlib,platform,sys
import ken.retrieval.source_operations as original
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.model import Span,EntityKey,Passage
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
records=[]
for case in request['cases']:
 directory=pathlib.Path(request['catalog_root'])/case['id'];directory.mkdir(parents=True)
 if case['manual']is None:catalog=make_catalog(directory,case['files'])
 else:
  owners={};path,source=next(iter(case['files'].items()));(directory/path).write_text(source)
  for row in case['manual']:
   key=EntityKey(path,'function',row['name']);span=Span(row['start'],row['end'])
   owners[key]=[Passage(key,span,{},hashlib.sha256(source.encode()).hexdigest(),span,'python')]
  catalog=SourceCatalog(directory,owners)
 physical=dict(files={name:list(source.encode())for name,source in case['files'].items()},owners=[dict(key=dataclasses.asdict(key),passages=[dataclasses.asdict(p)for p in passages])for key,passages in catalog.owners.items()])
 for name in case['files']:(directory/name).write_text('changed after catalog construction\n')
 observer=original.OperationWitnesses(catalog);observed=[]
 for key in catalog.owners:
  cold=observer.for_owner(key);warm=observer.for_owner(key)
  observed.append(dict(key=dataclasses.asdict(key),cold=sorted(cold),warm=sorted(warm)))
 records.append(dict(id=case['id'],input=physical,result=observed))
value=dict(format='ken-python-witnesses-reference/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()),original_source_sha256=hashlib.sha256(pathlib.Path(original.__file__).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def digest(value):return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def case_inputs(case_set):
    if case_set=="main":return cases()
    if case_set=="compat":
        from .python_witnesses_compat import compatibility_cases
        return compatibility_cases()
    if case_set=="review":
        from .python_witnesses_review import review_cases
        return review_cases()
    raise ValueError("unknown case set")
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        inputs=case_inputs(value.get('case_set','main'))
        require(value['format']=='ken-python-witnesses-reference/1','format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'observer differs')
        require(value['reference_fingerprint']==FP,'frozen source differs')
        require(value['original_source_sha256']=='5c0317d362d15902e66663cfac66764a94f7bbd6526c0a9ee367cfd7d0c8ef15','original implementation differs')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9'),'runtime differs')
        require(value['inputs_sha256']==hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest(),'inputs differ')
        require([c['id']for c in value['cases']]==[c['id']for c in inputs],'cases differ')
        for record,case in zip(value['cases'],inputs,strict=True):
            require(set(record)=={'id','input','result'}and set(record['input'])=={'files','owners'},'physical input contains foreign fields')
            require(record['input']['files']=={p:list(s.encode())for p,s in case['files'].items()},'source bytes differ')
            require([r['key']for r in record['result']]==[o['key']for o in record['input']['owners']]and all(r['cold']==r['warm']for r in record['result']),'membership/cache differs')
        require(value['observations_sha256']==digest(value),'observation bytes differ')
        return[]
    except(KeyError,TypeError,ValueError)as e:return[str(e)]
def capture(reference:Reference,out:Path,*,case_set="main"):
    if out.exists():raise FileExistsError(out)
    inputs=case_inputs(case_set)
    authenticate_frozen(reference);out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    request=dict(reference=str(reference.root),cases=inputs,catalog_root=str(out/'catalogs'),result=str(out/'observations.json'))
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    python=Path(sys.executable).absolute()
    child=subprocess.run([str(python),'-B',str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=180)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError('original observation failed: '+child.stderr.decode(errors='replace'))
    authenticate_frozen(reference)
    value=load(out/'observations.json');value.update(case_set=case_set,script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=FP,inputs_sha256=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest());value['observations_sha256']=digest(value)
    if validate_reference(value):raise ValueError(validate_reference(value))
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value

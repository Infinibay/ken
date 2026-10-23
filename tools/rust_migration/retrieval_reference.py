"""Capture actual frozen-original retrieval kernels before their Rust implementation."""
from __future__ import annotations
import hashlib,json,math,random,subprocess
from pathlib import Path
from .reference import Reference,reference_env
SUITE=['tests/retrieval/test_lexical.py','tests/retrieval/test_dense.py','tests/retrieval/test_proposals.py']
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
def passage(name='read',line=1,path='client.py',source_hash='a'*64,signals=None):
    entity=dict(path=path,kind='function',qualname=name,owner=None,definition_ordinal=0);span=dict(start_line=line,end_line=line+2)
    return dict(entity=entity,span=span,fields=dict(identity='function '+name,signature='def '+name+'():',documentation='Read stored source.',body='def '+name+'():\n    return 1\n',path=path),source_hash=source_hash,entity_span=span,language='python',role='definition',split_reason=None,signals=signals or{},implementation_start_line=line+1)
def candidate(name='read',line=1,**signals):
    p=passage(name,line,signals=signals);return dict(entity=p['entity'],passages=[p],signals=signals,owned_regions=[p['span']])
def definitions()->list[dict]:
    cases=[];rng=random.Random(71)
    def add(kind,data):cases.append(dict(id=f'{kind}:{len(cases)}:'+digest(data),kind=kind,input=data))
    for text in ['find code','COOKIE_JAR_CONFLICT','no eliminar clearAuth','𐐀😀','\ud800','x\udc00y','\x00','', ' ', '\t\r\n','\x1c\x1f','\u200b','\u0085','\u2028','\u2029','\u3000','\u2007']:
        add('request',dict(query=text))
    for key,values in [('target',['file','symbol','passage','other']),('purpose',['auto','implementation','usage','tests','documentation','other']),('limit',[-1,0,1,100]),('max_chars',[-1,0,1,20000]),('piece_kind',[None,'class','module','symbol','file','other'])]:
        for value in values:add('request',dict(query='read index',**{key:value}))
    for spans in [[],[[1,1]],[[1,3],[3,7],[8,9]],[[10,12],[1,2],[1,2],[4,7]],[[0,1]],[[2,1]]]+[[[rng.randrange(1,20),25]for _ in range(n)]for n in range(1,18)]:add('spans',spans)
    fields=['identity','signature','documentation','body','path']
    for n in range(80):
        frequencies={field:rng.randrange(0,9)for field in fields if rng.randrange(3)}
        add('bm25f',dict(frequencies=frequencies,lengths={f:rng.randrange(0,100)for f in fields},averages={f:rng.choice([0.,1.,7.,50.])for f in fields},document_frequency=n%11,documents=10,k1=1.2,weights=None if n%2 else{f:(i+1)/2 for i,f in enumerate(fields)}))
    for df,documents in [(-1,10),(11,10),(0,0),(2,0)]:add('bm25f',dict(frequencies={'body':3},lengths={'body':20},averages={'body':10.},document_frequency=df,documents=documents))
    for n in range(60):
        rows=[]
        for pid in range(1,2+n%7):
            for term in ['cookie','read','not'][:1+n%3]:
                for field in fields[:1+n%5]:
                    if rng.randrange(3):rows.append([pid,field,term,rng.randrange(1,6),rng.randrange(1,30)])
        if n%4==0:rows+=rows[:3]
        add('postings',dict(rows=rows,documents=12,averages={f:7. for f in fields}))
    for n in range(14):
        count=600 if n==0 else 20+n;dim=8
        matrix=[[rng.uniform(-1,1)for _ in range(dim)]for _ in range(count)]
        matrix=[[v/math.sqrt(sum(x*x for x in row))for v in row]for row in matrix]
        if n==0:matrix[10:15]=[matrix[9][:]for _ in range(5)]
        ids=list(range(100,100+count));ps=[passage('function_'+str(i%17),i+1)for i in range(count)]
        query=[rng.uniform(-1,1)for _ in range(dim)]
        if n==1:query=matrix[9]
        elif n==2:query=[0.]*dim
        elif n==3:query=[1.]
        elif n==4:query=['nan']+[0.]*(dim-1)
        elif n==5:query=['inf']+[0.]*(dim-1)
        add('dense',dict(passages=[[pid,p]for pid,p in zip(ids,ps)],ids=ids,matrix=matrix,query=query,view='behavior'if n%2 else'identity',limit=[6,100,1,0,-1,-100][n%6]))
    for n in range(70):
        channels=[]
        for channel in range(1+n%3):
            cs=[]
            for i in range(1+n%6):
                name='f'+str(i%3);c=candidate(name,1+3*(i%2),cosine_behavior=(i+1)/10,**({'exact':1.}if n%7==0 and i==1 else{}))
                if n%8==0:cs.append(json.loads(json.dumps(c)))
                cs.append(c)
            channels.append(['channel_'+str(channel),cs])
        if n in (3,4):channels[0][1][0]['passages'][0]['source_hash']='b'*64
        elif n==5:channels[0][1][0]['passages']=[]
        elif n==6:channels[0][1][0]['passages'][0]['entity']['qualname']='foreign'
        add('fusion',dict(channels=channels,limit=0 if n==7 else 1+n%8,rrf_k=0 if n==8 else 60))
    return cases
SCRIPT=r'''
import dataclasses,hashlib,importlib,json,math,pathlib,platform,sys
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import SearchRequest,Span,Passage,EntityKey,Candidate,merge_spans
from ken.retrieval.lexical import bm25f_score,score_postings
from ken.retrieval.dense import DenseView
from ken.retrieval.embedding_store import VectorView
from ken.retrieval.proposals import fuse_proposals
for name in ['model','lexical','dense','proposals']:
 module=importlib.import_module('ken.retrieval.'+name)
 if not pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original module')
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
 if isinstance(value,dict):return {str(k):clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [clean(v)for v in value]
 if isinstance(value,(float,np.floating))and not math.isfinite(value):return {'float':str(float(value))}
 if isinstance(value,np.generic):return value.item()
 return value
def p(value):
 value=dict(value);value['entity']=EntityKey(**value['entity']);value['span']=Span(**value['span']);value['entity_span']=Span(**value['entity_span']);return Passage(**value)
def c(value):return Candidate(EntityKey(**value['entity']),[p(v)for v in value['passages']],value['signals'],tuple(Span(**s)for s in value['owned_regions']))
records=[]
for case in request['cases']:
 data=case['input'];kind=case['kind']
 try:
  if kind=='request':result=SearchRequest(**data)
  elif kind=='spans':result=merge_spans(Span(*s)for s in data)
  elif kind=='bm25f':result=bm25f_score(**data)
  elif kind=='postings':result=score_postings(data['rows'],documents=data['documents'],averages=data['averages'])
  elif kind=='dense':result=DenseView({pid:p(v)for pid,v in data['passages']},VectorView(tuple(data['ids']),np.asarray(data['matrix'],dtype=np.float32),'provided-input-matrix')).search(np.asarray(data['query'],dtype=np.float32),data['view'],data['limit'])
  elif kind=='fusion':result=fuse_proposals({name:[c(v)for v in values]for name,values in data['channels']},limit=data['limit'],rrf_k=data['rrf_k'])
  else:raise ValueError('unknown kernel')
  record=dict(id=case['id'],kind=kind,input=data,result=clean(result))
 except Exception as error:record=dict(id=case['id'],kind=kind,input=data,error=dict(type=type(error).__name__,message=str(error)))
 records.append(record)
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-retrieval-kernel-reference/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
def owners(repo:Path)->dict:
    baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    return {r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/retrieval/','src/ken/embedder/','src/ken/parsers/'))or r['path']in SUITE+['tests/conftest.py','tests/retrieval/test_ranking.py','src/ken/db.py','src/ken/schema.sql','src/ken/indexer.py','src/ken/nametokens.py','src/ken/search.py','src/ken/vectors.py']}
def validate_reference(value:dict)->list[str]:
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-retrieval-kernel-reference/1','wrong original kernel format')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest()and value['execution']['exit']==0,'original kernel observer/exit differs')
        inputs=[{k:c[k]for k in ('id','kind','input')}for c in value['cases']];require(inputs==definitions(),'original kernel input inventory differs')
        require(all(('result'in c)^('error'in c)for c in value['cases']),'original kernel results incomplete')
        require(value['corpus_sha256']==digest(value['cases']),'original kernel observations changed')
        require(value['original_test_exit']==0 and len(value['discovered'])==13 and len(set(value['discovered']))==13,'original kernel discovery/exit differs')
        require({s['nodeid']for s in value['test_states']}==set(value['discovered'])and all(s['when']=='call'and s['outcome']=='passed'for s in value['test_states']),'original kernel suite incomplete')
        return []
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def capture(reference:Reference,out:Path,repo:Path)->dict:
    expected=owners(repo)
    for path,sha in expected.items():
        if hashlib.sha256((reference.root/path).read_bytes()).hexdigest()!=sha:raise ValueError('original kernel owner changed: '+path)
    target=out/'reference.json'
    if target.exists():
        value=json.loads(target.read_bytes());errors=validate_reference(value)
        if errors or value['owners']!=expected:raise ValueError(errors or'original kernel owners differ')
        return value
    out.mkdir(parents=True,exist_ok=True);script=out/'capture.py';request=out/'request.json';script.write_text(SCRIPT)
    request.write_text(json.dumps(dict(root=str(reference.root),cases=definitions(),suite=SUITE,junit=str(out/'original-tests.xml'),result=str(out/'observations.json')),ensure_ascii=True))
    proc=subprocess.run([str(reference.python),str(script),str(request)],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'stdout.log').write_bytes(proc.stdout);(out/'stderr.log').write_bytes(proc.stderr)
    if proc.returncode:raise ValueError('original kernel capture failed: '+proc.stdout.decode(errors='replace')[-2500:]+proc.stderr.decode(errors='replace')[-1000:])
    (out/'process-exit.json').write_text(json.dumps(dict(exit=proc.returncode))+'\n')
    value=json.loads((out/'observations.json').read_bytes());value.update(owners=expected,script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),execution=dict(exit=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),stderr_sha256=hashlib.sha256(proc.stderr).hexdigest(),observations_sha256=hashlib.sha256((out/'observations.json').read_bytes()).hexdigest()))
    value['corpus_sha256']=digest(value['cases']);errors=validate_reference(value)
    if errors:raise ValueError(errors)
    target.write_bytes((json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode('utf8',errors='backslashreplace'));return value

"""Original candidate union over real SQLite source/vector artifacts."""
SCRIPT=r'''
import dataclasses,importlib,json,pathlib,platform,sys,tempfile,unicodedata
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.db import connect,init_schema
from ken.retrieval.model import EntityKey,Span,Passage,SearchRequest
from ken.retrieval.storage import replace_file_passages
from ken.retrieval.profile import EncoderSpec,RetrievalProfile,_backend_runtime,_package_version
from ken.retrieval.representations import index_embeddings
from ken.retrieval.candidates import retrieve
for name in ['candidates','storage','representations','profile']:
 if not pathlib.Path(importlib.import_module('ken.retrieval.'+name).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original selection module')
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
 if isinstance(value,dict):return {str(k):clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [clean(v)for v in value]
 if isinstance(value,np.generic):return value.item()
 return value
records=[]
for case in request['cases']:
 data=case['input'];calls=[]
 class Encoder:
  def __init__(self,name):self.name=name
  def embed_passages(self,texts):
   result=[]
   for text in texts:
    selected=next((v for word,v in data['document_vectors']if word.lower()in text.lower()),data['fallback_vector']);result.append(np.asarray(selected,dtype=np.float32))
   return result
  def embed_query(self,text):calls.append(dict(encoder=self.name,query=text));return np.asarray(data['query_vector'],dtype=np.float32)
 try:
  with tempfile.TemporaryDirectory(prefix='ken-selection-original-')as temporary:
   with connect(pathlib.Path(temporary)/'index.db')as conn:
    init_schema(conn);conn.execute('BEGIN')
    conn.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,language)VALUES('client.py',x'00',0,0,'python')")
    passages=[];symbols=set()
    for item in data['passages']:
     item=dict(item);item['entity']=EntityKey(**item['entity']);item['span']=Span(**item['span']);item['entity_span']=Span(**item['entity_span']);p=Passage(**item);passages.append(p)
     token=(p.entity.kind,p.entity.qualname,p.entity_span.start_line,p.entity_span.end_line)
     if token not in symbols:
      symbols.add(token);conn.execute('INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(1,?,?,?,?,?)',(p.entity.kind,p.entity.qualname.rsplit('.',1)[-1],p.entity.qualname,p.entity_span.start_line,p.entity_span.end_line))
    replace_file_passages(conn,1,passages,source_hash='a'*64);conn.commit()
    spec=EncoderSpec('test/selection','a'*40,'provided');profile=RetrievalProfile(spec,spec,candidate_limit=data.get('candidate_limit',100))
    first=Encoder('shared'if data.get('shared',True)else'identity');encoders=dict(identity=first,behavior=first if data.get('shared',True)else Encoder('behavior'))
    if data.get('prepare',True)and passages:index_embeddings(conn,profile,encoders=encoders)
    calls.clear()
    for sql in data.get('sql',[]):conn.execute(sql)
    conn.commit()
    result=retrieve(conn,pathlib.Path(temporary),SearchRequest(**data['request']),profile,encoders=encoders)
    records.append(dict(**case,result=dict(candidates=clean(result),query_calls=calls)))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),query_calls=calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
legacy=dict(format='ken-legacy-runtime/1',backends={backend:_backend_runtime(backend)for backend in('static','model2vec','sentence-transformers','mlx','provided')},evidence=[(name,_package_version(name))for name in('numpy','snowballstemmer')],contextual=[(name,_package_version(name))for name in('numpy','tokenizers','onnxruntime')])
value=dict(format='ken-selection-reference/1',family='selection',cases=records,legacy_runtime=legacy,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''

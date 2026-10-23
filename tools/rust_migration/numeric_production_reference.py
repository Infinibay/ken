"""Registered original forests and actual static-table/owner composition."""
from .numeric_feature_reference import SCRIPT as FEATURE_SCRIPT
SCRIPT=FEATURE_SCRIPT.split('records=[]\nfor case')[0]+r'''
import gzip,hashlib,time
from ken.retrieval.best_resources import load_rank_models
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.profile import EncoderSpec
from ken.embedder.static_head import StaticHeadEmbedder
native,piece=load_rank_models();models=dict(native=native,piece=piece)
directory=root/'src/ken/retrieval/data';registry=json.loads((directory/'production-rank-models.json').read_bytes())
artifact=root/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz';artifact_sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
word_spec=EncoderSpec('ken/static-qwen3-r512-v2',artifact_sha,'static')
static=StaticHeadEmbedder('ken/static-qwen3-r512-v2',path=artifact)
records=[]
for case in request['cases']:
 data=case['input'];model=models[data['role']];calls=[];stem_calls=[]
 class Encoder:
  spec=word_spec
  def embed_query(self,text):calls.append(dict(op='query',text=text));return static.embed_query(text)
  def embed_passages(self,texts):calls.append(dict(op='passages',texts=list(texts)));return np.asarray(static.embed_passages(list(texts)),dtype=np.float32)
 def stems(words):stem_calls.append(list(words));return EvidenceReranker.stem_words(words)
 try:
  if case['kind']=='production_identity':
   encoded=(directory/registry[data['role']]['file']).read_bytes();decoded=gzip.decompress(encoded)
   result=dict(fingerprint=model.fingerprint,features=list(model.features),trees=len(model.to_dict()['trees']),compressed_sha256=hashlib.sha256(encoded).hexdigest(),compressed_bytes=len(encoded),decoded_sha256=hashlib.sha256(decoded).hexdigest(),decoded_bytes=len(decoded))
  elif case['kind']=='production_predict':
   values=np.asarray([[((row*17+col*7)%257-128)/16. for col in range(len(model.features))]for row in range(data['rows'])],dtype=np.float64).reshape(data['rows'],len(model.features))
   result=dict(scores=model.predict(values))
  else:
   candidates=[candidate(v)for v in data['candidates']];descriptions={EntityKey(**o['key']):describe_owner([passage(p)for p in o['passages']])for o in data['owners']}
   runtime=EvidenceReranker(model,Encoder());runtime.stem_words=stems
   trace=RankingTrace(request_id='production-static-composition')
   matches=runtime.rank(SearchRequest(**data['request']),candidates,descriptions,expanded_query=data.get('expanded'),evidence_version=3,trace=trace)
   result=dict(matches=matches,trace=trace.to_dict(include_query=True),static_sha256=artifact_sha,word_spec=dataclasses.asdict(word_spec))
  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),encoder_calls=calls,stemmer_calls=stem_calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
if 'cached_suite'in request:
 cached=json.loads(pathlib.Path(request['cached_suite']).read_bytes());discovered=cached['discovered'];states=cached['test_states'];exit_code=cached['original_test_exit']
else:exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''

PATHS_SCRIPT=SCRIPT.replace("import gzip,hashlib,time", "import gzip,hashlib,time,struct").replace("  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls))", "  rows=trace.to_dict()['owners'];paths=[]\n  for owner in rows:\n   explanation=model.explain_pair(owner['feature_values'],owner['feature_values'])\n   paths.append([[struct.pack('>d',tree['left_leaf']).hex(),[[step['feature_index'],step['branch']]for step in tree['left_path']]]for tree in explanation['trees']])\n  result=dict(paths_sha256=hashlib.sha256(json.dumps(paths,separators=(',',':')).encode()).hexdigest())\n  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls))")

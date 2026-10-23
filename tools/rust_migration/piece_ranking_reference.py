"""Original full requested-piece features, calls, forest decisions and composition."""
from .numeric_feature_reference import SCRIPT as FEATURE_SCRIPT
SCRIPT=FEATURE_SCRIPT.split('records=[]\nfor case')[0]+r'''
import struct,hashlib
from ken.retrieval.model import CodeMatch
from ken.retrieval.description import OwnerDescription
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval import piece_ranking as module
if not pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original piece ranking')
real_features=module.piece_features
def observed_features(*args,**kwargs):
 value=real_features(*args,**kwargs);matrices.append(value);return value
module.piece_features=observed_features
def match(v):return CodeMatch(EntityKey(**v['entity']),v['score'],[passage(p)for p in v['evidence']],v['source_hash'],v.get('signals',{}),tuple(Span(**s)for s in v.get('owned_regions',[])))
def piece(v):
 members=[OwnerDescription(**{**m,'entity':EntityKey(**m['entity']),'passages':tuple(passage(p)for p in m['passages'])})for m in v['members']]
 return module.PieceCandidate(v['kind'],v['path'],EntityKey(**v['entity'])if v['entity']else None,tuple(members),tuple(match(m)for m in v['matches']))
production=None;static=None
records=[]
for case in request['cases']:
 data=restore(case['input']);calls=[];stem_calls=[];matrices=[]
 class Encoder:
  def embed_query(self,text):calls.append(dict(op='query',text=text));return static.embed_query(text)if data.get('production')else vector(text)
  def embed_passages(self,texts):calls.append(dict(op='passages',texts=list(texts)));return np.asarray(static.embed_passages(list(texts))if data.get('production')else[vector(t)for t in texts],dtype=np.float32)
 def stems(words):stem_calls.append(list(words));return EvidenceReranker.stem_words(words)if data.get('stemmer','english')=='english'else list(words)
 try:
  pieces=[piece(v)for v in data['pieces']];search=SearchRequest(**data['request'])
  if case['kind']=='piece_features':result=module.piece_features(search,pieces,encoder=Encoder(),stem_words=stems,expanded_query=data.get('expanded'))
  else:
   if data.get('production'):
    if production is None:
     from ken.retrieval.best_resources import load_rank_models
     from ken.embedder.static_head import StaticHeadEmbedder
     production=load_rank_models()[1];static=StaticHeadEmbedder('ken/static-qwen3-r512-v2',path=root/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz')
    model=production
   else:model=NumericRanker.from_dict(data['model'])
   ranked=module.PieceReranker(model,Encoder(),stem_words=stems).rank(search,pieces,expanded_query=data.get('expanded'))
   positions={id(p):i for i,p in enumerate(pieces)}
   result=dict(order=[positions[id(m.piece)]for m in ranked],scores=[m.score for m in ranked],features=matrices[-1]if matrices else None)
   if data.get('production'):
    paths=[]
    for row in matrices[-1].values if matrices else []:
     explanation=model.explain_pair(row,row)
     paths.append([[struct.pack('>d',tree['left_leaf']).hex(),[[step['feature_index'],step['branch']]for step in tree['left_path']]]for tree in explanation['trees']])
    result['paths_sha256']=hashlib.sha256(json.dumps(paths,separators=(',',':')).encode()).hexdigest()
  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),encoder_calls=calls,stemmer_calls=stem_calls))
'''+ 'discovered=[];states=[]'+FEATURE_SCRIPT.split('discovered=[];states=[]')[1].replace("ken-numeric-reference/1","ken-piece-reference/1")
_suite="exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])"
SCRIPT=SCRIPT.replace(_suite,"if 'cached_suite'in request:\n cached=json.loads(pathlib.Path(request['cached_suite']).read_bytes());discovered=cached['discovered'];states=cached['test_states'];exit_code=cached['original_test_exit']\nelse:"+_suite)

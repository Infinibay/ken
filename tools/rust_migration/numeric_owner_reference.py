"""Original owner ranking, profile/expansion binding, and request-local traces."""
from .numeric_feature_reference import SCRIPT as FEATURE_SCRIPT
SCRIPT=FEATURE_SCRIPT.split('records=[]\nfor case')[0]+r'''
from copy import deepcopy
from uuid import UUID
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.profile import EncoderSpec,EvidenceRanking
word_spec=EncoderSpec('test/words','b'*64,'provided',batch_size=1)
records=[]
for case in request['cases']:
 data=restore(case['input']);calls=[];stem_calls=[];expansion_calls=[]
 class Encoder:
  spec=word_spec
  def embed_query(self,text):calls.append(dict(op='query',text=text));return vector(text)
  def embed_passages(self,texts):calls.append(dict(op='passages',texts=list(texts)));return np.asarray([vector(t)for t in texts],dtype=np.float32)
 def stems(words):stem_calls.append(list(words));return EvidenceReranker.stem_words(words)
 def expand(query):expansion_calls.append(query);return data.get('expansion_result','persist durable cookie')
 try:
  model=NumericRanker.from_dict(data['model']);kind=case['kind']
  if kind=='trace_ids':
   a,b=RankingTrace(request_id=data.get('request_id')),RankingTrace(request_id=data.get('request_id'))
   result=dict(first_valid=UUID(a.request_id).version==4,second_valid=UUID(b.request_id).version==4,different=a.request_id!=b.request_id)
  elif kind.startswith('trace_'):
   trace=RankingTrace(request_id=data.get('request_id','fixed-trace'))
   if kind=='trace_empty':
    result=trace.compare(EntityKey('missing.py','function','missing'),EntityKey('other.py','function','other'))if data.get('compare_empty')else trace.to_dict()
   else:
    candidates=[candidate(v)for v in data['candidates']];values=np.asarray(data['values'],dtype=np.float64);scores=model.predict(values)
    order=sorted(range(len(candidates)),key=lambda i:(-candidates[i].signals.get('exact',0),-scores[i],i))
    from ken.retrieval.model import CodeMatch
    matches=[CodeMatch(candidates[i].entity,float(scores[i]),candidates[i].passages,candidates[i].passages[0].source_hash,dict(candidates[i].signals),candidates[i].owned_regions)for i in order]
    trace.record(model=model,query=data['query'],expanded=data.get('expanded',data['query']),candidates=candidates,matches=matches,values=values,feature_version=1,evidence_version=1,piece_kind=data.get('piece_kind'))
    original=trace.to_dict(include_query=True)
    if kind=='trace_restore':
     altered=deepcopy(original);tamper=data.get('tamper')
     if tamper=='model':altered['model_fingerprint']='0'*64
     elif tamper=='names':altered['feature_names'].reverse()
     elif tamper=='proposal':altered['owners'][0]['proposal_index']=8
     elif tamper=='ranks':altered['owners'][0]['rank']=0
     elif tamper=='duplicate':altered['owners'][1]['path']=altered['owners'][0]['path'];altered['owners'][1]['entity']=deepcopy(altered['owners'][0]['entity'])
     elif tamper=='scores':altered['owners'][0]['score']+=1
     elif tamper=='order':altered['owners'][0]['rank'],altered['owners'][1]['rank']=altered['owners'][1]['rank'],altered['owners'][0]['rank']
     elif tamper=='policy':altered['policy']='unsupported'
     elif tamper=='exact-policy':altered['policy']='unique_exact'
     elif tamper=='query':altered['query']='tampered query'
     elif tamper=='expanded':altered['expanded_query_sha256']='0'*64
     elif tamper=='drop-query':altered.pop('query');altered.pop('expanded_query')
     trace=RankingTrace.from_dict(altered,model)
    detached=trace.to_dict(include_query=True);detached['owners'][0]['signals']['rrf']=999
    values[0,0]=999;candidates[0].signals['rrf']=999
    result=dict(trace=trace.to_dict(),with_query=trace.to_dict(include_query=True),pair=trace.compare(matches[0].entity,matches[1].entity),detached=trace.to_dict()['owners'][0]['signals']['rrf']!=999)
  else:
   runtime=EvidenceReranker(model,Encoder(),expand_query=expand if data.get('expand')else None,expansion_revision=data.get('expansion_revision'));runtime.stem_words=stems
   if kind=='prepare':result=runtime.prepare_query(data['query'])
   elif kind=='validate':
    spec=dict(model_revision=model.fingerprint,word_model=word_spec,expansion_revision=data.get('expansion_revision'),feature_version=runtime.feature_version)
    for key,value in data.get('profile',{}).items():spec[key]=EncoderSpec(**value)if key=='word_model'else value
    runtime.validate(EvidenceRanking(**spec));result=True
   else:
    candidates=[candidate(v)for v in data['candidates']];before=deepcopy(candidates);descriptions={EntityKey(**o['key']):describe_owner([passage(p)for p in o['passages']])for o in data['owners']};trace=RankingTrace(request_id=data.get('request_id','fixed-rank-trace'))if kind=='rank_trace'else None
    matches=runtime.rank(SearchRequest(**data['request']),candidates,descriptions,expanded_query=data.get('expanded'),evidence_version=data.get('evidence_version',1),trace=trace)
    if data.get('second_query')is not None:matches=runtime.rank(SearchRequest(data['second_query']),candidates,descriptions,evidence_version=data.get('evidence_version',1),trace=trace)
    result=dict(matches=matches,unchanged=candidates==before)
    if trace:
     result.update(trace=trace.to_dict(),with_query=trace.to_dict(include_query=True))
     restored=RankingTrace.from_dict(result['with_query'],model)
     result['restored']=restored.to_dict(include_query=True)
     if len(matches)>=2:result['pair']=trace.compare(matches[0].entity,matches[1].entity)
  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls,expansion_calls=expansion_calls))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),encoder_calls=calls,stemmer_calls=stem_calls,expansion_calls=expansion_calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''

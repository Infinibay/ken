"""Actual Snowball words, provider ownership, and original reuse observations."""
SCRIPT=r'''
import concurrent.futures,importlib,json,pathlib,platform,sys,unicodedata
from types import SimpleNamespace
import pytest,snowballstemmer
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
import ken.retrieval.owner_ranking as module
if not pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original stem owner')
records=[]
for case in request['cases']:
 data=case['input'];kind=case['kind'];module._stem_word.cache_clear();original=module.import_module
 try:
  if kind=='stem':result=module.EvidenceReranker.stem_words(data['words'])
  elif kind=='stem_concurrent':
   with concurrent.futures.ThreadPoolExecutor(max_workers=8)as pool:result=list(pool.map(module.EvidenceReranker.stem_words,data['groups']))
  elif kind=='stem_reuse':
   calls=[]
   def factory(language):
    if language!='english':raise ValueError('wrong stemming language')
    return SimpleNamespace(stemWords=lambda words:[emit(w)for w in words])
   def emit(word):calls.append(word);return data['prefix']+word
   module.import_module=lambda name:SimpleNamespace(stemmer=factory)
   batches=[]
   for words in data['batches']:
    value=module.EvidenceReranker.stem_words(words);batches.append(list(value))
    if value:value[0]='mutated'
   info=module._stem_word.cache_info();result=dict(batches=batches,calls=calls,entries=info.currsize,capacity=info.maxsize)
  elif kind=='stem_capacity':
   calls=[]
   def factory(language):return SimpleNamespace(stemWords=lambda words:[emit(w)for w in words])
   def emit(word):calls.append(word);return word
   module.import_module=lambda name:SimpleNamespace(stemmer=factory)
   words=['term'+str(i)for i in range(data['count'])];module.EvidenceReranker.stem_words(words)
   output=module.EvidenceReranker.stem_words(['term0',words[-1]])
   info=module._stem_word.cache_info();result=dict(output=output,calls=calls,entries=info.currsize,capacity=info.maxsize)
  elif kind=='stem_providers':
   calls=[]
   def make(prefix):
    def factory(language):return SimpleNamespace(stemWords=lambda words:[emit(prefix,w)for w in words])
    return factory
   def emit(prefix,word):calls.append([prefix,word]);return prefix+word
   factories={p:make(p)for p in data['providers']};outputs=[]
   for provider in data['order']:
    module.import_module=lambda name:SimpleNamespace(stemmer=factories[provider])
    outputs.append(module.EvidenceReranker.stem_words(data['words']))
   result=dict(outputs=outputs,calls=calls)
  else:raise ValueError('unknown stem operation')
  records.append(dict(**case,result=result))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error))))
 finally:module.import_module=original;module._stem_word.cache_clear()
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family='stems',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,snowball='3.0.1'),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''

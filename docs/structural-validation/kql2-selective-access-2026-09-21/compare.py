import sys,time,json,hashlib
from pathlib import Path
from ken.structural.service import patterns
from ken.structural.query import QueryBudget
from ken.structural.index_service import project_index
from examples.bench.pattern_search import semantic_result
label,case=sys.argv[1:3]
root=Path('/Users/andres/Projects/codex') if case=='sdk26' else Path('/tmp/ken-sub5-corpus-100')
cache=Path('/tmp/ken-kql2-audit-20260920') if case=='sdk26' else Path('/tmp/ken-sub5-baseline-cache')
scope='sdk/typescript' if case=='sdk26' else '.'
names=None if case=='sdk26' else [case.removesuffix('100')]
with project_index(root,path=scope,database=cache/'patterns.sqlite',source_cache_path=cache/'source-cache.sqlite') as (_,preparation):
 print('Prepared',len(preparation['files']),flush=True)
def canonical(v):
 if isinstance(v,dict):
  return {k: ('CATALOG/'+value.split('/ken/structural/',1)[1] if k=='source' and isinstance(value,str) and '/ken/structural/' in value else canonical(value)) for k,value in v.items()}
 if isinstance(v,list):return [canonical(x) for x in v]
 return v
records=[]
for i in range(2):
 start=time.monotonic()
 r=patterns(root,names=names,path=scope,cache_directory=cache,use_result_cache=False,budget=QueryBudget(timeout_ms=40000))
 elapsed=time.monotonic()-start
 semantics=semantic_result(canonical({'findings':r['findings'],'incomplete':r['incomplete'],'outcomes':{n:{k:o[k] for k in ('complete','unknown')} for n,o in r['outcomes'].items()}}))
 record={'seconds':elapsed,'complete':r['complete'],'index_hit':r['analysis']['query_index']['hit'],'semantic_sha256':hashlib.sha256(json.dumps(semantics,sort_keys=True).encode()).hexdigest()}
 records.append(record)
 Path('/tmp/'+label+'-'+str(i)+'.json').write_text(json.dumps(r,indent=2))
 Path('/tmp/'+label+'-timings.json').write_text(json.dumps(records,indent=2))
 print(record,flush=True)

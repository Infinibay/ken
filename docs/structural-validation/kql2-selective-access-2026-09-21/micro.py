import hashlib,json,sys,time
from pathlib import Path
from ken.kql2.exploration.records import Records,encode
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
label=sys.argv[1]
records=Records(encode([(str(i),'common',i) for i in range(20000)],3,{0,1},lambda:None),3,{0,1})
assert list(records.select({1:'common',0:'1'}))==[1]
timings=[]
for _ in range(3):
 start=time.perf_counter()
 total=sum(int(records.select({1:'common',0:str(i)})[0]) for i in range(2000))
 timings.append(time.perf_counter()-start)
assert total==sum(range(2000))
result={'vector':{'rows':20000,'lookups':2000,'seconds':timings,'checksum':total}}
with Store(Path('/tmp/ken-sub5-baseline-cache/patterns.sqlite')) as store:
 graph=store.db.execute('select max(graph_id) from k2_graph_publications where ready=1').fetchone()[0]
 index=GraphIndex(store,graph)
 ids=[index.words(r[0]) for r in store.db.execute('select local_id from k2_graph_operations where graph_id=? order by ordinal limit 100',(graph,))]
 list(index.operations(local_id=ids[0]))
 timings=[]
 for _ in range(3):
  start=time.perf_counter()
  selected=[op.id for identifier in ids for op in index.operations(local_id=identifier)]
  timings.append(time.perf_counter()-start)
 result['operations']={'lookups':len(ids),'seconds':timings,'result_sha256':hashlib.sha256(json.dumps(selected).encode()).hexdigest()}
 index.close()
Path('/tmp/'+label+'.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)

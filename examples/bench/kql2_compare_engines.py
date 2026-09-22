"""Compare KQL1/KQL2 on equivalent selectors over exactly the same input IR."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import tempfile
import time

from ken.kql2 import parse as parse2
from ken.kql2.compiler import compile as compile2
from ken.kql2.execution import execute as execute2
from ken.structural.kenql import Engine,parse as parse1,query_graph
from ken.structural.model import IR,Entity
from ken.structural_store import Store


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--nodes',type=int,default=100000)
    parser.add_argument('--repeats',type=int,default=15)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    ir=IR('synthetic.py','python')
    for i in range(args.nodes):
        key=f'c{i}'; name='Target' if i==args.nodes-1 else f'Class{i}'
        ir.entities[key]=Entity(key,'CLASS',name,ir.path,i+1,i+1)
        ir.add(key,'ENTITY','CLASS',name=name)
    text1='query q { class(name: "Target") as $c; emit $c; }'
    text2='language "kql/2"; module bench; query q { class $c { name: "Target"; } select $c; }'
    start=time.perf_counter(); q1=parse1(text1); compile1=(time.perf_counter()-start)*1000
    start=time.perf_counter(); q2=compile2(parse2(text2)); compile_ms2=(time.perf_counter()-start)*1000
    start=time.perf_counter(); graph=query_graph(ir); prepare1=(time.perf_counter()-start)*1000
    with tempfile.TemporaryDirectory() as temp:
        with Store(Path(temp)/'store.sqlite') as store:
            start=time.perf_counter(); u=store.put_unit('corpus',ir,'fixed','bench'); snapshot=store.publish([u],expected_parent=None); prepare2=(time.perf_counter()-start)*1000
            samples={'kql1':[],'kql2':[]}
            for iteration in range(args.repeats):
                # Alternate engine order to reduce systematic ordering effects.
                for engine in (('kql1','kql2') if iteration%2==0 else ('kql2','kql1')):
                    start=time.perf_counter()
                    if engine=='kql1':
                        out=Engine(graph,{}).execute(q1)
                        ids={m['bindings']['$c'] for m in out['matches']}
                        complete=out['complete']; rows=out['stats']['rows_examined']
                    else:
                        out2=execute2(q2,store,snapshot,timeout_ms=None)
                        ids={r[0].local_id for r in out2.rows}; complete=out2.complete; rows=out2.scanned_nodes
                    elapsed=(time.perf_counter()-start)*1000
                    assert complete and ids=={f'c{args.nodes-1}'}
                    samples[engine].append({'ms':elapsed,'candidates':rows})
            report={'nodes':args.nodes,'platform':platform.platform(),'query1':text1,'query2':text2,
                    'compile_ms':{'kql1':compile1,'kql2':compile_ms2},'prepare_graph_ms':{'kql1_in_memory':prepare1,'kql2_persisted':prepare2},
                    'first_query_ms':{k:v[0]['ms'] for k,v in samples.items()},
                    'warm_median_ms':{k:statistics.median(s['ms'] for s in v[1:]) for k,v in samples.items()},'samples':samples,
                    'limitations':['One selective synthetic workload; not general speed comparison',
                                   'Both evaluate every query; no result memo',
                                   'KQL1 returns proof metadata; KQL2 returns nodes',
                                   'KQL1 graph preparation is RAM-only; KQL2 includes persistence',
                                   'No source parsing, OS cold-cache or incremental timings in this experiment'],
                    'code_hashes':{str(p):sha256(p.read_bytes()).hexdigest() for base in ('src/ken/kql2','src/ken/structural_store') for p in Path(base).rglob('*.py')}}
            args.output.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({k:report[k] for k in ('warm_median_ms','first_query_ms','prepare_graph_ms')}))

if __name__=='__main__':
    main()

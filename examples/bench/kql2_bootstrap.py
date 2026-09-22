"""Reproducible selective-query baseline, including build and reference costs.

Run with the repository Python environment; emits JSON, never runs corpus code.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import platform
from pathlib import Path
import statistics
import sys
import tempfile
import time

from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.structural.model import Entity, IR, IR_VERSION
from ken.structural_store import Store

QUERY='language "kql/2"; module bench; query q { class $c { name: "Target"; } select $c; }'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--nodes',type=int,default=100_000)
    parser.add_argument('--repeats',type=int,default=7)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.nodes < 2 or args.repeats < 1:
        parser.error('positive workload required')
    program=compile(parse(QUERY))
    ir=IR('synthetic.py','python')
    for i in range(args.nodes):
        ident=f'n{i}'
        ir.entities[ident]=Entity(ident,'CLASS','Target' if i==args.nodes-1 else f'Class{i}',ir.path,i+1,i+1)
    with tempfile.TemporaryDirectory(prefix='ken-kql2-bench-') as directory:
        path=Path(directory)/'store.sqlite'
        with Store(path) as store:
            start=time.perf_counter()
            unit=store.put_unit('fixed-corpus',ir,'synthetic','baseline')
            snapshot=store.publish([unit],expected_parent=None)
            build_ms=(time.perf_counter()-start)*1000
            runs={}
            for name,reference in [('indexed',False),('reference',True)]:
                samples=[]
                for _ in range(args.repeats):
                    outcome=execute(program,store,snapshot,reference=reference,timeout_ms=None,max_states=args.nodes*2)
                    assert outcome.complete and len(outcome.rows)==1
                    assert outcome.rows[0][0].name=='Target'
                    samples.append({'ms':outcome.elapsed_ms,'scanned_nodes':outcome.scanned_nodes,'states':outcome.states})
                runs[name]={'samples':samples,'median_ms':statistics.median(s['ms'] for s in samples)}
            sql,params=store.scan_sql(snapshot,kind='CLASS',name='Target')
            physical_plan=store.db.execute('EXPLAIN QUERY PLAN '+sql,params).fetchall()
            bytes_allocated=store.allocated_bytes
        start=time.perf_counter()
        with Store(path) as store:
            reopened=execute(program,store,snapshot,timeout_ms=None)
            reopen_ms=(time.perf_counter()-start)*1000
        hashes={str(p):sha256(p.read_bytes()).hexdigest() for base in ('src/ken/kql2','src/ken/structural_store') for p in sorted(Path(base).rglob('*.py'))}
        result={'python':sys.version,'platform':platform.platform(),'ir':IR_VERSION,
                'query':QUERY,'nodes':args.nodes,'repeats':args.repeats,'build_ms':build_ms,
                'store_bytes':bytes_allocated,'reopen_and_query_ms':reopen_ms,
                'reopened_scanned_nodes':reopened.scanned_nodes,'runs':runs,
                'sqlite_plan':physical_plan,'implementation_hashes':hashes,
                'limitations':['Synthetic selective query, not the full catalogue','Reference scans same typed store; not KQL1','Reopen retains OS page cache','No result memoization; warm times execute joins','No p95 claim from seven samples']}
        text=json.dumps(result,indent=2)+'\n'
        if args.output:
            args.output.write_text(text)
        else:
            print(text)

if __name__=='__main__':
    main()

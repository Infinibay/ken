"""Benchmark the common AST against Python's AST. Never executes corpus code."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import tempfile
import time
from ken.common_ast import VERSION
from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.structural.frontend import lower_source
from ken.structural_store import Store
from ken.structural_store.common_ast import View

QUERY='language "kql/2"; module bench; query q {node $n {kind:"return";} select $n.path,$n.start_byte,$n.line;}'


def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('root',type=Path)
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--repeats',type=int,default=5)
 args=parser.parse_args()
 if args.repeats<1: parser.error('repeats must be positive')
 root=args.root.resolve(); oracle=set(); manifest={}; units=[]
 program=compile(parse(QUERY)); parse_ms=0.; persist_ms=0.
 counters=Counter(); opaque=Counter()
 with tempfile.TemporaryDirectory(prefix='ken-common-ast-') as directory:
  database=Path(directory)/'store.sqlite'
  with Store(database) as store:
   for file in sorted(root.rglob('*.py')):
    data=file.read_bytes(); relative=file.relative_to(root).as_posix()
    manifest[relative]=sha256(data).hexdigest()
    offsets=[0]
    for line in data.splitlines(keepends=True): offsets.append(offsets[-1]+len(line))
    for node in ast.walk(ast.parse(data)):
     if isinstance(node,ast.Return): oracle.add((relative,offsets[node.lineno-1]+node.col_offset,node.lineno))
    start=time.perf_counter(); ir=lower_source(data.decode('utf8'),'python',relative)
    parse_ms+=(time.perf_counter()-start)*1000
    start=time.perf_counter(); unit=store.put_unit(manifest[relative]+relative,ir,manifest[relative],'bench-common-ast')
    persist_ms+=(time.perf_counter()-start)*1000
    units.append(unit)
    view=View(store,unit)
    for node in view.nodes():
     counters['nodes']+=1
     if node.category=='opaque': opaque[node.native_kind]+=1
    for family in ('scopes','symbols','references'): counters[family]+=len(view.rows(family))
   snapshot=store.publish(units,expected_parent=None)
   runs={}
   # Repeat each plan; samples execute queries, not cached result retrieval.
   for label,reference in [('indexed',False),('full_scan',True)]:
    samples=[]
    for _ in range(args.repeats):
     outcome=execute(program,store,snapshot,reference=reference,timeout_ms=None)
     assert outcome.complete and set(outcome.rows)==oracle and not outcome.unknown_candidates
     samples.append({'ms':outcome.elapsed_ms,'scanned_nodes':outcome.scanned_nodes,'states':outcome.states})
    runs[label]={'samples':samples,'median_ms':statistics.median(s['ms'] for s in samples)}
   allocated=store.allocated_bytes
  start=time.perf_counter()
  with Store(database) as store:
   def forbidden(*args): raise AssertionError('query must not deserialize the legacy IR')
   store.load_unit=forbidden
   result=execute(program,store,snapshot,timeout_ms=None)
   assert set(result.rows)==oracle
  reopen_ms=(time.perf_counter()-start)*1000
 output={'version':VERSION,'root':str(root),'platform':platform.platform(),'python':platform.python_version(),
  'manifest':manifest,'query':QUERY,'files':len(units),'counts':dict(counters),'opaque_native_kinds':dict(opaque.most_common()),
  'parse_ms':parse_ms,'projection_and_persistence_ms':persist_ms,'store_bytes':allocated,
  'runs':runs,'reopen_and_query_ms':reopen_ms,'oracle':'Python ast.Return: exact (path, UTF-8 byte offset, line) set',
  'expected':len(oracle),'matched':len(result.rows),'false_positives':0,'false_negatives':0,
  'implementation_hashes':{str(p):sha256(p.read_bytes()).hexdigest() for base in ('src/ken/common_ast','src/ken/kql2','src/ken/structural_store') for p in sorted(Path(base).rglob('*.py'))},
  'limitations':['Return-node query, not GoF precision','OS page cache retained','Store size includes legacy IR and indexes','Full scan is common AST without kind/name pushdown, not KQL1','No whole-program execution/initialization oracle']}
 args.output.write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps({k:v for k,v in output.items() if k not in ('manifest','implementation_hashes','runs')},indent=2))
 print('query medians', {key:run['median_ms'] for key,run in runs.items()})

if __name__=='__main__': main()

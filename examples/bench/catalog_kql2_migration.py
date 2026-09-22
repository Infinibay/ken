"""Compare frozen catalog queries with KQL 2 on read-only local source corpora.

No source programs are executed. This measures migration parity, not a truth
oracle for design intent. Run without concurrent CPU-heavy jobs for timings.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import subprocess
import time

from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget
from ken.structural.rules import SavedRule, builtin_rules, query_registry
from ken.structural.semantic import link_project


def contract(result):
    return {'bindings':sorted(([m['bindings'],m['status'],m['unknown']] for m in result['matches']), key=repr),
            'complete':result['complete'], 'unknown':result['unknown']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',action='append',required=True,type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-files',type=int,default=40)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    fixture=root/'tests/structural/catalog_matrix/pre_kql2_catalog.json'
    old_rules=[SavedRule(**r) for r in json.loads(fixture.read_text())['rules']]
    started=time.perf_counter();new_rules=[r for r in builtin_rules() if r.source];new=query_registry(new_rules)
    cold=time.perf_counter()-started
    warm=[]
    for _ in range(args.repeats):
        started=time.perf_counter();query_registry(new_rules);warm.append(time.perf_counter()-started)
    old=query_registry(old_rules)
    languages={'.py':'python','.cpp':'cpp','.cc':'cpp','.rs':'rust','.go':'go','.java':'java','.ts':'typescript','.js':'javascript','.cs':'csharp','.rb':'ruby'}
    from ken.structural.model import IR_VERSION
    from ken.kql2.compilation import implementation_fingerprint
    report={'ir_version': IR_VERSION, 'engine_fingerprint': implementation_fingerprint(),
            'baseline_sha256':sha256(fixture.read_bytes()).hexdigest(),
            'repeats':args.repeats,'catalog_cold_ms':cold*1000,'catalog_warm_ms':statistics.median(warm)*1000,'repositories':[]}
    for repo in args.repo:
        files=subprocess.check_output(['git','ls-files','-z'],cwd=repo).decode().split('\0')
        eligible=[f for f in sorted(files) if Path(f).suffix in languages and not (repo/f).is_symlink() and (repo/f).is_file()]
        files=eligible[:args.max_files]
        start=time.perf_counter();units=[];manifest=[]
        for path in files:
            data=(repo/path).read_bytes();language=languages[Path(path).suffix]
            units.append(lower_source(data,language,path));manifest.append({'path':path,'language':language,'sha256':sha256(data).hexdigest()})
        index=query_graph(link_project(units));build=time.perf_counter()-start
        results=[]
        for rule in new_rules:
            outcomes={};times={'old':[],'kql2':[]}
            for turn in range(args.repeats):
                for label,registry in ([('old',old),('kql2',new)] if turn%2==0 else [('kql2',new),('old',old)]):
                    start=time.perf_counter()
                    out=Executor(index,registry,QueryBudget(max_states=1_000_000,max_rows=2_000_000,timeout_ms=3000)).execute(registry[rule.id])
                    times[label].append((time.perf_counter()-start)*1000)
                    outcomes[label]=out
            results.append({'id':rule.id,'same':contract(outcomes['old'])==contract(outcomes['kql2']),
                            'matches':len(outcomes['kql2']['matches']),
                            'complete':outcomes['kql2']['complete'],
                            'unknown':outcomes['kql2']['unknown'],
                            'old_ms':statistics.median(times['old']),'kql2_ms':statistics.median(times['kql2']),
                            'old_states':outcomes['old']['stats']['states'],'kql2_states':outcomes['kql2']['stats']['states']})
        print(repo, 'complete', sum(r['complete'] for r in results), '/', len(results), flush=True)
        report['repositories'].append({'path':str(repo),'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
              'eligible_files':len(eligible),'files':manifest,'facts':len(index.ir.facts),'build_ms':build*1000,'diagnostics':index.ir.diagnostics,'results':results})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(args.output)


if __name__=='__main__':
    main()

"""Three-arm identity audit; references remain closed until all public guards pass."""
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import unseen_piece_score as old
import verifiable_grading


def validate_production(path, lock):
    path=Path(path);reg=json.loads((path/'registration.json').read_text())
    if reg['status']!='ALL additional public outputs closed without Gold':raise ValueError('production must close before Gold')
    if reg['variant']!='production' or reg['variant_policy']!=lock['variant_policy'] or reg['lock_sha256']!=old.sha(lock['_path']):raise ValueError('production policy/lock differs')
    answers=[];timings=[];memory=[];cpu=[]
    for repo,pins in reg['closed'].items():
        if set(pins)!={'answers.jsonl','performance.json'}:raise ValueError('unexpected production closure')
        for name,digest in pins.items():
            if old.sha(path/repo/name)!=digest:raise ValueError('production output changed')
        rows=old.rows(path/repo/'answers.jsonl');perf=json.loads((path/repo/'performance.json').read_text())
        if perf['providers']!=['CPUExecutionProvider'] or perf['heavy_imports'] or perf['source_receipt']!=lock['source_receipt']:raise ValueError('production CPU/source policy differs')
        if perf['repo']!=repo or any(a['repo_id']!=repo for a in rows):raise ValueError('production repository metadata differs')
        answers+=rows;timings+=perf['timings'];memory.append(perf['peak_rss_native']*(1 if perf['rss_unit']=='bytes' else 1024));cpu.append(perf['server_cpu_total_ms'])
    amap=old.unique(answers)
    if len(timings)!=len(answers) or set(old.unique(timings))!=set(amap):raise ValueError('production timing IDs incomplete')
    for answer in answers:
        old.validate_returned_units(answer)
        response=answer['public_response']
        if response.get('ok') is False or len(response['results'])!=len(answer['units']):raise ValueError('public response differs')
        for result,unit in zip(response['results'],answer['units'],strict=True):
            kind=result['piece_kind']
            actual={'target_kind':kind,'path':result['path'],'entity':result['entity'] if kind in {'class','symbol'} else None,'module_name':result.get('module_name') if kind=='module' else None}
            if actual!=unit or result['stale']:raise ValueError('actual public piece identity differs')
    times=[t['ms'] for t in timings]
    return reg,answers,{'p50_ms':float(np.median(times)),'p95_ms':float(np.quantile(times,.95)),'max_ms':max(times),'peak_rss_bytes':max(memory),'server_cpu_total_ms':sum(cpu),'cpu_ms_p50':None,'cpu_note':'MCP does not expose per-query child CPU; total server process CPU includes setup/warmup and compact checks.'}


def validate_public_closure(path, cases, *, production):
    """Authenticate every repo payload and resource value before aggregation."""
    path=Path(path);registration=json.loads((path/'registration.json').read_text())
    groups={}
    for case in cases:groups.setdefault(case['repo_id'],set()).add(case['id'])
    if set(registration['closed'])!=set(groups):raise ValueError('closure repositories differ from public queries')
    def nonnegative(value):
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
    for repo,expected_ids in groups.items():
        pins=registration['closed'][repo]
        if set(pins)!={'answers.jsonl','performance.json'}:raise ValueError('complete closure file hashes required')
        for name,digest in pins.items():
            if old.sha(path/repo/name)!=digest:raise ValueError('closed payload changed')
        answers=old.rows(path/repo/'answers.jsonl');perf=json.loads((path/repo/'performance.json').read_text())
        if set(old.unique(answers))!=expected_ids or any(a['repo_id']!=repo for a in answers):raise ValueError('per-repository answers differ')
        if set(old.unique(perf['timings']))!=expected_ids:raise ValueError('per-repository timing IDs differ')
        if perf['rss_unit'] not in {'bytes','KiB'} or not nonnegative(perf['peak_rss_native']):raise ValueError('invalid RSS value/unit')
        for row in perf['timings']:
            if not nonnegative(row['ms']):raise ValueError('invalid wall timing')
            if production:
                if row['cpu_ms'] is not None:raise ValueError('MCP per-query CPU must remain unavailable')
            elif not nonnegative(row['cpu_ms']):raise ValueError('invalid process CPU timing')
        if production and not nonnegative(perf['server_cpu_total_ms']):raise ValueError('invalid total server CPU')


def preflight(lock_path, baseline_path, optimized_path, production_path):
    lock=json.loads(Path(lock_path).read_text())
    if old.sha(__file__)!=lock['scorer_sha256'] or old.sha(old.__file__)!=lock['previous_scorer_sha256'] or old.sha(verifiable_grading.__file__)!=lock['grading_sha256']:raise ValueError('scoring source changed')
    previous_path=Path(lock['previous_lock']);production_lock_path=Path(lock['production_lock'])
    if old.sha(previous_path)!=lock['previous_lock_sha256'] or old.sha(production_lock_path)!=lock['production_lock_sha256']:raise ValueError('arm lock changed')
    previous=json.loads(previous_path.read_text());prodlock=json.loads(production_lock_path.read_text());prodlock['_path']=str(production_lock_path)
    if previous['scorer_sha256']!=old.sha(old.__file__) or previous['grading_sha256']!=old.sha(verifiable_grading.__file__):raise ValueError('previous scoring pins differ')
    if len({Path(p).resolve() for p in (baseline_path,optimized_path,production_path)})!=3:raise ValueError('capture directories must differ')
    for source in (previous,prodlock):
        for path,digest in source['input_pins'].items():
            if old.sha(path)!=digest:raise ValueError('prelocked public input changed')
    if previous['public_cases']!=prodlock['public_cases'] or previous['queries']!=prodlock['queries']:raise ValueError('public query set differs')
    cases=old.rows(previous['public_cases'])
    for path,is_production in ((baseline_path,False),(optimized_path,False),(production_path,True)):
        validate_public_closure(path,cases,production=is_production)
    base,ba,bcpu=old.load_closed(baseline_path);optimized,oa,ocpu=old.load_closed(optimized_path);production,pa,pcpu=validate_production(production_path,prodlock)
    for reg,role,path in ((base,'baseline',baseline_path),(optimized,'optimized',optimized_path)):
        if reg['variant']!=role or reg['variant_policy']!=previous['variants'][role] or reg['lock_sha256']!=old.sha(previous_path):raise ValueError('previous role/lock/policy mismatch')
        if old.sha(Path(path)/'registration.json')!=lock['capture_registration_pins'][role]:raise ValueError('prior closure changed')
    for registration,role,path in ((production,'production',production_path),):
        if old.sha(Path(path)/'registration.json')!=lock['capture_registration_pins'][role]:raise ValueError('production closure differs from final receipt')
    for source in (previous,prodlock):
        for path,digest in source['input_pins'].items():
            if old.sha(path)!=digest:raise ValueError('prelocked public input changed')
    if previous['public_cases']!=prodlock['public_cases'] or previous['queries']!=prodlock['queries']:raise ValueError('public query set differs')
    cases=old.rows(previous['public_cases']);cm=old.unique(cases)
    if not cm or len(cm)!=previous['queries']:raise ValueError('incomplete public query set')
    maps=[old.unique(a) for a in (ba,oa,pa)]
    if any(set(m)!=set(cm) for m in maps):raise ValueError('all three captures must be complete before Gold')
    for qid,case in cm.items():
        for answers in maps:
            answer=answers[qid];old.validate_returned_units(answer)
            if any(answer[k]!=case[k] for k in ('repo_id','target_kind')) or any(u['target_kind']!=case['target_kind'] for u in answer['units']):raise ValueError('request metadata/type differs')
        if maps[0][qid]['native_units']!=maps[1][qid]['native_units'] or maps[0][qid]['pool_sha256']!=maps[1][qid]['pool_sha256']:raise ValueError('CPU optimization changed native source pool')
    return lock,previous,cases,(ba,oa,pa),(bcpu,ocpu,pcpu)


def main():
    parser=argparse.ArgumentParser()
    for key in ('lock','baseline','optimized','production','output','private-output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--gold',type=Path,nargs=2,required=True);args=parser.parse_args()
    lock,previous,cases,answers,cpu=preflight(args.lock,args.baseline,args.optimized,args.production)
    references=[]
    # No reference payload is opened before the complete three-arm preflight.
    if {str(p.resolve()) for p in args.gold}!=set(previous['reference_pins']):raise ValueError('reference set differs')
    for path in args.gold:
        if old.sha(path)!=previous['reference_pins'][str(path.resolve())]:raise ValueError('reference seal differs')
        references+=old.rows(path)
    report={'scope':'Independent additional200 identity; same eight repositories; no new-repository generalization','arms':{},'cpu':{},'lock_sha256':old.sha(args.lock),'limits':'Separate from exposed development200. Query Wilson intervals ignore repository dependence. No90% population guarantee. v104 remains unopened; its overlap is not verified.'};private={}
    for role,arm,perf in zip(('baseline','optimized','production'),answers,cpu,strict=True):
        result,outcomes=old.evaluate_identity(cases,arm,references);report['arms'][role]=result;report['cpu'][role]=perf;private[role]=outcomes
    args.output.mkdir(parents=True,exist_ok=False);args.private_output.mkdir(parents=True,exist_ok=False)
    (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');(args.private_output/'graded-rows.json').write_text(json.dumps(private,indent=2)+'\n')
    print(json.dumps({role:report['arms'][role]['top1'] for role in report['arms']}))

if __name__=='__main__':main()

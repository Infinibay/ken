"""One fresh public CPU arm, immutable canonical-identity grading and no Gold preflight."""
import argparse,json,math
import numpy as np
from pathlib import Path,PurePosixPath
import public_default_three_arm_score as guards
import unseen_piece_score as old
import verifiable_grading as grading
import ken.bench.source_receipts as source

_SCOPE='FRESH_BALANCED200_CANONICAL_PIECE_ACCEPTANCE'
_REPOS={'ajv','attrs','boltons','commons-csv','junit5','marked','packaging','pytest'}
class ReferenceBoundary:
    """Reject paths and same-file aliases before any public preflight reads."""
    def __init__(self,paths):
        self.paths={Path(p).resolve() for p in paths}
        if not self.paths:raise ValueError('explicit sealed reference paths required')
        self.files={(p.stat().st_dev,p.stat().st_ino) for p in self.paths}
    def public(self,path):
        p=Path(path);resolved=p.resolve()
        if resolved in self.paths:raise ValueError('private reference is not a public input')
        if p.exists():
            stat=p.stat()
            if (stat.st_dev,stat.st_ino) in self.files:raise ValueError('private reference alias is not a public input')
        return p

def validate_unit(unit,kind):
    if not isinstance(unit,dict) or set(unit)!={'target_kind','path','entity','module_name'} or unit['target_kind']!=kind:
        raise ValueError('canonical requested-unit shape required')
    path=unit['path']
    if (not isinstance(path,str) or not path or '\x00' in path or '\\' in path
            or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
            or PurePosixPath(path).as_posix()!=path or path=='.'):
        raise ValueError('canonical relative source path required')
    entity=unit['entity']
    if kind in {'class','symbol'}:
        if (not isinstance(entity,dict) or set(entity)!={'kind','qualname','owner','definition_ordinal'}
                or not isinstance(entity['qualname'],str) or not entity['qualname']
                or entity['owner'] is not None and not isinstance(entity['owner'],str)
                or type(entity['definition_ordinal']) is not int or entity['definition_ordinal']<0
                or entity['kind'] not in ({'class'} if kind=='class' else {'function','method','const','constant'})):
            raise ValueError('canonical class/symbol identity required')
    elif entity is not None:raise ValueError('module/file primary entity must be null')
    if kind=='module':
        if not isinstance(unit['module_name'],str) or not unit['module_name']:raise ValueError('module identity required')
    elif unit['module_name'] is not None:raise ValueError('nonmodule name must be null')

def preflight(lock_path,capture,*,protected_paths):
    boundary=ReferenceBoundary(protected_paths)
    lock=json.loads(boundary.public(lock_path).read_text())
    if lock['scope']!=_SCOPE:raise ValueError('fresh acceptance scope required')
    if {str(p) for p in boundary.paths}!=set(lock['reference_pins']):raise ValueError('sealed private boundary differs')
    expected={str(Path(p).resolve()) for p in [__file__,guards.__file__,old.__file__,grading.__file__,source.__file__]}
    if set(lock['code_pins'])!=expected:raise ValueError('complete immutable scorer dependencies required')
    for path,digest in lock['code_pins'].items():
        if old.sha(boundary.public(path))!=digest:raise ValueError('scoring source changed')
    path=boundary.public(lock['production_lock'])
    if old.sha(path)!=lock['production_lock_sha256']:raise ValueError('prelocked production policy changed')
    prod=json.loads(path.read_text());prod['_path']=str(path)
    engine=Path(prod['engine_root']);manifest=boundary.public(engine/'SOURCE-MANIFEST.json')
    for name in json.loads(manifest.read_text())['files']:boundary.public(engine/name)
    if source.verify_frozen_source(engine)!=prod['source_receipt']:raise ValueError('production frozen source changed')
    policy=prod['variant_policy']
    if (policy.get('default_engine') is not True or policy.get('source_receipt')!=prod['source_receipt']
            or Path(policy.get('engine_root','')).resolve()!=engine.resolve()):raise ValueError('actual default engine/source policy required')
    producer=Path(__file__).with_name('public_default_mcp_run.py').resolve()
    launcher=Path(__file__).with_name('public_default_server.py').resolve()
    pins={str(Path(p).resolve()):digest for p,digest in prod['input_pins'].items()}
    if (prod.get('producer_sha256')!='4867cf0de55a5ce74e723314b0d931b3e12b46aa7b505a59a080c250c88d182d'
            or Path(prod.get('server_launcher','')).resolve()!=launcher
            or pins.get(str(producer))!=prod['producer_sha256']
            or pins.get(str(launcher))!='190885e3e647a6930bb3dc4b475e862db41beb66857f87c10e8e7f924353b426'):
        raise ValueError('registered actual public producer/launcher must be pinned')
    if str(Path(prod['public_cases']).resolve()) not in pins:raise ValueError('public queries must be pinned')
    for p,digest in prod['input_pins'].items():
        if old.sha(boundary.public(p))!=digest:raise ValueError('prelocked public input changed')
    cases=old.rows(boundary.public(prod['public_cases']));cm=old.unique(cases)
    if prod['queries']!=200 or len(cm)!=200:raise ValueError('all200fresh queries required')
    if {c['repo_id'] for c in cases}!=_REPOS:raise ValueError('fresh repository set differs')
    for kind in ['class','module','symbol','file']:
        group=[c for c in cases if c['target_kind']==kind]
        if len(group)!=50:raise ValueError('balanced piece quotas differ')
        if sum(c['language']=='en' for c in group)!=30 or sum(c['language']=='es' for c in group)!=20:raise ValueError('per-kind language quotas differ')
        if sum(c['query_style']=='behavior' for c in group)!=40 or sum(c['query_style'] in {'lookup','qualified_lookup'} for c in group)!=10:raise ValueError('per-kind intent quotas differ')
    boundary.public(Path(capture)/'registration.json')
    for repo in _REPOS:
        for name in ['answers.jsonl','performance.json']:boundary.public(Path(capture)/repo/name)
    guards.validate_public_closure(capture,cases,production=True)
    try:
        with np.errstate(over="raise",invalid="raise"):
            reg,answers,cpu=guards.validate_production(capture,prod)
    except FloatingPointError as exc:
        raise ValueError("resource aggregate overflow") from exc
    if any(isinstance(value,(int,float)) and not math.isfinite(value) for value in cpu.values()):
        raise ValueError("finite resource aggregates required")
    if old.sha(Path(capture)/'registration.json')!=lock['capture_registration_sha256']:raise ValueError('complete public closure changed')
    am=old.unique(answers)
    if set(am)!=set(cm):raise ValueError('every public query needs an answer')
    for qid,case in cm.items():
        answer=am[qid];units=answer['units'];card=answer['card']
        if any(answer[k]!=case[k] for k in ['repo_id','target_kind']):raise ValueError('public request metadata differs')
        if bool(units)!=(card is not None):raise ValueError('top1 presence differs from returned order')
        for i,unit in enumerate(units):
            validate_unit(unit,case['target_kind'])
            if grading.identity_hit({'unit':unit},units[:i]):
                raise ValueError('duplicate canonical unit identity')
    return lock,cases,answers,cpu

def main():
    p=argparse.ArgumentParser()
    for k in ['lock','capture','gold','output','private-output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();lock,cases,answers,cpu=preflight(a.lock,a.capture,protected_paths=[a.gold])
    # References first opened AFTER all public/source/closure/resource guards.
    if {str(a.gold.resolve())}!=set(lock['reference_pins']):raise ValueError('reference set differs')
    if old.sha(a.gold)!=lock['reference_pins'][str(a.gold.resolve())]:raise ValueError('sealed references changed')
    summary,outcomes=old.evaluate_identity(cases,answers,old.rows(a.gold))
    report={'scope':'Fresh balanced independent200 canonical piece identity, same8repositories; no new-repository generalization','quality':summary,'cpu':cpu,'lock_sha256':old.sha(a.lock),'cohort_status':'CONSUMED_AS_ACCEPTANCE_AFTER_THIS_SCORING','limits':'Separate from exposed development. Query Wilson intervals ignore repository dependence. No population90% guarantee; v104 remains unopened.'}
    a.output.mkdir(parents=True,exist_ok=False);a.private_output.mkdir(parents=True,exist_ok=False)
    (a.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');(a.private_output/'graded-rows.json').write_text(json.dumps(outcomes,indent=2)+'\n')
    print(json.dumps(summary))
if __name__=='__main__':main()

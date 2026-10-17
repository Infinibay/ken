"""Grade four preclosed view-composition arms on already consumed public labels only."""
from collections import defaultdict
from pathlib import Path
import hashlib,json,sys
base=Path.cwd();clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');sys.path.insert(0,str(clean/'experiments/search-engine'))
from verifiable_grading import identity_hit
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();run=base/'output/analysis/view-scale-v288-old240';reg=json.loads((run/'registration.json').read_text());assert reg['status']=='ALL240English variant orders CLOSED before exposed Gold' and reg['old240_baseline_orders_reproduced'];assert sha(run/'predictions.jsonl')==reg['predictions_sha256'];assert sha(base/'output/analysis/repoqa-diagnosis-v236/source/replay_view_scale_v288.py')==reg['producer_sha256'];predictions=[json.loads(x) for x in (run/'predictions.jsonl').read_text().splitlines()];assert len(predictions)==240 and len({r['id'] for r in predictions})==240
known=json.loads((base/'output/development/prior-java-regression-v276/grading-registration-v278.json').read_text());manifest_path=Path(known['exposed_manifest']);assert sha(manifest_path)==known['exposed_manifest_sha256'];assert sha(clean/'experiments/search-engine/verifiable_grading.py')==known['identity_helper_sha256'];manifest=json.loads(manifest_path.read_text());pins={name:digest for cohort in manifest['cohorts'] for name,digest in cohort['exposed_gold_pins'].items()};assert pins==known['reference_pins']
lock={'capture_registration_sha256':sha(run/'registration.json'),'exposed_manifest_sha256':sha(manifest_path),'reference_pins':pins,'identity_helper_sha256':known['identity_helper_sha256'],'grader_sha256':sha(Path(__file__)),'reserve':'CLOSED','status':'All240predictions already closed and old240baseline orders identical before reading exposed references'};lock_path=run/'grading-registration-v290.json';assert not lock_path.exists();lock_path.write_text(json.dumps(lock,indent=2)+'\n')
gold={}
for name,digest in pins.items():
 p=Path(name);assert sha(p)==digest;gold.update({r['id']:r for r in map(json.loads,p.read_text().splitlines())})
assert len(gold)==400;summary={};outcomes=[]
for variant in reg['variants']:
 counts=defaultdict(lambda:{'queries':0,'top1':0,'top10':0});changes=[]
 for row in predictions:
  units=row['orders'][variant];hit=lambda u:bool(identity_hit({'unit':u},gold[row['id']]['acceptable_units']));rank=next((i for i,u in enumerate(units,1) if hit(u)),None);baseline=bool(row['orders']['baseline_mean'] and hit(row['orders']['baseline_mean'][0]));c=counts[row['cohort']];c['queries']+=1;c['top1']+=rank==1;c['top10']+=rank is not None
  out={k:row[k] for k in ('id','cohort','language','target_kind','repo_id')}|{'variant':variant,'rank':rank,'top1':rank==1,'top10':rank is not None,'baseline_top1':baseline};outcomes.append(out)
  if (rank==1)!=baseline:changes.append(out)
 assert counts['original']['queries']==counts['symbols']['queries']==120 and counts['original']['top10']==118 and counts['symbols']['top10']==119
 summary[variant]={'cohorts':dict(counts),'gains':sum(r['top1'] for r in changes),'losses':sum(not r['top1'] for r in changes),'changes':changes}
assert summary['baseline_mean']['cohorts']['original']['top1']==110 and summary['baseline_mean']['cohorts']['symbols']['top1']==108
report={'summary':summary,'closure_registration_sha256':sha(run/'registration.json'),'grading_registration_sha256':sha(lock_path),'reserve':'CLOSED','interpretation':'Fixed cached-logit composition diagnostic; all240English exposed development queries. Not independent acceptance, inference or CPU/RAM comparison. Whole baseline order reproduced before grading. No fitted weights, language/repository routing or production promotion.'};(run/'report.json').write_text(json.dumps(report,indent=2)+'\n');(run/'outcomes.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in outcomes));print(json.dumps({k:{x:v[x] for x in ('cohorts','gains','losses')} for k,v in summary.items()},indent=2))

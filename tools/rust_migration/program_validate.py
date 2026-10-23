"""Input-only program requests and complete independently observed comparisons."""
from pathlib import Path
import json
from .native_json import NativeJsonCapture,identity,load

def source_identity(repo:Path)->dict:
 files=[repo/name for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml')]
 files+=sorted(p for p in(repo/'crates/ken-program').rglob('*')if p.is_file())
 return {str(p.relative_to(repo)):identity(p)for p in files}
def program_cases(repo:Path)->list[dict]:
 folder=repo/'crates/ken-program/tests/fixtures';cases=[]
 corpus=load(folder/'program-reference.json')
 for group,kind,prefix in [('programs','normalize','program'),('codecs','codec','codec')]:
  for row in corpus[group]:cases.append(dict(id=prefix+':'+row['id'],kind=kind,input=row['input'],expected={k:v for k,v in row.items()if k not in ('id','input','tests','calls')}))
 for row in load(folder/'type-reference.json')['types']:cases.append(dict(id='type:'+row['id'],kind='type',input=row['input'],expected=dict(result=row['result'])))
 return cases

def requests(cases:list[dict])->dict:
 rows=[]
 for case in cases:
  row=dict(id=case['id'],kind=case['kind'])
  if case['kind']=='normalize':row.update(ir=case['input'],lookups=[{k:q[k]for k in ('name','scope','point')}for q in case['expected'].get('lookups',[])])
  elif case['kind']=='codec':row['program']=case['input']
  else:row.update(case['input'])
  rows.append(row)
 return dict(cases=rows)

def compare_program_observations(cases:list[dict],actual:dict)->list[str]:
 try:
  def require(value,message):
   if not value:raise ValueError(message)
  def error(original,native):
   require(original['type']in ('ValueError','TypeError')and set(native)=={'kind','message'}and native['kind']=='invalid_program'and type(native['message'])is str and bool(native['message']),'original program failure differs/swallowed')
  require(set(actual)=={'format','cases'}and actual['format']=='ken-program-observation/1','wrong program observation protocol')
  require(len(actual['cases'])==len(cases),'missing/duplicate program cases')
  for case,row in zip(cases,actual['cases'],strict=True):
   require(row['id']==case['id'],'program identity/order differs');expected=case['expected']
   if case['kind']=='type':require(set(row)=={'id','descriptor'}and row['descriptor']==expected['result'],'complete original type differs: '+case['id'])
   elif'error'in expected:require(set(row)=={'id','error'},'original program error became success');error(expected['error'],row['error'])
   else:
    keys={'id','program','bodies','lookups'}if case['kind']=='normalize'else{'id','program'}
    require(set(row)==keys and row['program']==expected['result'],'complete original program differs: '+case['id'])
    if case['kind']=='normalize':
     require(row['bodies']==expected['bodies'],'branch body ranges differ')
     require(len(row['lookups'])==len(expected['lookups']),'lookup inventory differs')
     for original,lookup in zip(expected['lookups'],row['lookups'],strict=True):
      require(all(lookup[k]==original[k]for k in ('name','scope','point')),'lookup context/order differs')
      if'error'in original:require(set(lookup)=={'name','scope','point','error'},'invalid lookup became success');error(original['error'],lookup['error'])
      else:require(set(lookup)=={'name','scope','point','result'}and lookup['result']==original['result'],'lookup identity/status/availability/reason differs')
  return []
 except(ValueError,KeyError,TypeError)as failure:return[str(failure)]

def run_program_capture(repo:Path,probe:Path,cases:list[dict],out:Path)->dict:
 before=source_identity(repo)
 with NativeJsonCapture(probe,out,repo=repo,prefix='ken-program-process-')as process:
  (out/'SOURCES.json').write_text(json.dumps(before,indent=2)+'\n');process.run(requests(cases))
  build=dict(format='ken-program-build/1',sources=before,native_sha256=process.binary['sha256']);(out/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
  if source_identity(repo)!=before:raise ValueError('program sources changed during execution')
 from .program_evidence import verify_program_capture
 errors=verify_program_capture(out,cases)
 if errors:raise ValueError(errors)
 return build

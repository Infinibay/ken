"""Disjoint, authenticated frozen-original search-selection observations."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from .reference import Reference,reference_env
from .retrieval_reference import owners as kernel_owners,digest
from .native_json import load,identity
from .selection_owner_reference import SCRIPT as OWNERS_SCRIPT
from .selection_sql_reference import SCRIPT as SELECTION_SCRIPT
from .selection_context_reference import SCRIPT as CONTEXT_SCRIPT
from .selection_context_sql_reference import SCRIPT as CONTEXT_SELECTION_SCRIPT
from .selection_ranking_reference import SCRIPT as RANKING_SCRIPT
ROOT=Path(__file__).resolve().parents[2]
SUITES={'text':['tests/retrieval/test_intent.py','tests/retrieval/test_qualified_locator.py'],'owners':['tests/retrieval/test_owner_description.py'],'selection':['tests/retrieval/test_candidates.py']}
SUITES['context']=['tests/retrieval/test_contextual_retrieval.py','tests/retrieval/test_contextual_source_views.py']
SUITES['context_selection']=['tests/retrieval/test_contextual_search.py']
SUITES['ranking']=['tests/retrieval/test_ranking.py::'+name for name in (
    'test_joint_ranker_orders_behavior_and_never_counts_duplicate_passages_as_votes',
    'test_test_purpose_reaches_joint_ranker_and_exact_identity_stays_first',
    'test_joint_ranker_rejects_nonfinite_scores',
    'test_implementation_comparison_does_not_treat_description_as_executable_source',
    'test_passage_judgments_choose_owner_and_retain_decisive_evidence_score')]

def owners(repo:Path):
    value=kernel_owners(repo)
    baseline=load(repo/'docs/validation/rust-migration-2026-10-18/baseline.json')
    value.update({r['path']:r['sha256']for r in baseline['files']if r['path'].startswith('tests/retrieval/')})
    return value

def definitions(family:str,repo:Path=ROOT):
    value=load(repo/f'crates/ken-retrieval/tests/fixtures/selection-inputs-{family}.json')
    return value['cases']

TEXT_SCRIPT=r'''
import dataclasses,hashlib,importlib,json,pathlib,platform,re,sys,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import SearchRequest,EntityKey
from ken.retrieval.intent import interpret,requested_piece_kind,requested_piece_path
from ken.retrieval.source_locator import symbol_locator
from ken.retrieval.piece_catalog import module_name
for name in ['intent','source_locator','piece_catalog']:
 if not pathlib.Path(importlib.import_module('ken.retrieval.'+name).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original selection module')
records=[]
for case in request['cases']:
 data=case['input'];kind=case['kind']
 try:
  if kind=='intent':
   search=SearchRequest(**data);result=dict(intent=dataclasses.asdict(interpret(search)),piece_kind=requested_piece_kind(search),path=requested_piece_path(search))
  elif kind=='locator':
   locator=symbol_locator(data['query']);result=dict(locator=dataclasses.asdict(locator)if locator else None,matches=[locator.matches(EntityKey(**key))if locator else False for key in data['entities']])
  elif kind=='module':result=module_name(data['path'])
  elif kind=='identifier':result=data['text'].isidentifier()
  else:raise ValueError('unknown text operation')
  records.append(dict(**case,result=result))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error))))
def ranges(predicate):
 result=[];start=None
 for cp in range(0x110000):
  if predicate(chr(cp)):
   if start is None:start=cp
  elif start is not None:result.append([start,cp-1]);start=None
 if start is not None:result.append([start,0x10ffff])
 return result
alphabet='abcdefghijklmnopqrstuvwxyzáéíóúñü';patterns=[(letter,re.compile(re.escape(letter),re.I))for letter in alphabet];allowed=re.compile('['+alphabet+']',re.I)
fold={}
for cp in range(0x110000):
 c=chr(cp)
 if allowed.fullmatch(c):
  letter=next(letter for letter,pattern in patterns if pattern.fullmatch(c))
  if c!=letter:fold[str(cp)]=letter
text_semantics=dict(unicode=unicodedata.unidata_version,identifier_start=ranges(str.isidentifier),identifier_continue=ranges(lambda c:('A'+c).isidentifier()),query_literal_fold=fold)
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-selection-reference/1',family='text',cases=records,text_semantics=text_semantics,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
SCRIPTS={'text':TEXT_SCRIPT,'owners':OWNERS_SCRIPT,'selection':SELECTION_SCRIPT}
SCRIPTS['context']=CONTEXT_SCRIPT
SCRIPTS['context_selection']=CONTEXT_SELECTION_SCRIPT
SCRIPTS['ranking']=RANKING_SCRIPT

def validate_reference(value:dict,family:str,repo:Path=ROOT):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-selection-reference/1'and value['family']==family,'original selection family differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),'original selection observer differs')
        require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==definitions(family,repo),'original selection input inventory differs')
        require(all(('result'in c)^('error'in c)for c in value['cases'])and digest(value['cases'])==value['corpus_sha256'],'original selection observations differ')
        require(value['execution']['exit']==0 and value['original_test_exit']==0,'original selection process/suite failed')
        found=value['discovered'];states=value['test_states'];require(found and len(set(found))==len(found),'original selection discovery absent/duplicated')
        require({s['nodeid']for s in states}==set(found)and all(s['when']=='call'and s['outcome']=='passed'for s in states),'original selection suite incomplete')
        if family=='text':require(value['text_semantics']['unicode']=='15.0.0'and value['text_semantics']['identifier_start']and value['text_semantics']['identifier_continue'],'frozen text semantics absent')
        return []
    except(KeyError,ValueError,TypeError)as error:return[str(error)]

def capture(reference:Reference,out:Path,repo:Path,family:str):
    expected=owners(repo)
    for name,sha in expected.items():
        if identity(reference.root/name)['sha256']!=sha:raise ValueError('original selection owner changed: '+name)
    if(out/'reference.json').exists():
        value=load(out/'reference.json');errors=validate_reference(value,family,repo)
        if errors or value['owners']!=expected:raise ValueError(errors or'original selection owner inventory differs')
        return value
    out.mkdir(parents=True,exist_ok=False);(out/'capture.py').write_text(SCRIPTS[family])
    request=dict(root=str(reference.root),cases=definitions(family,repo),suite=SUITES[family],junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
    (out/'request.json').write_text(json.dumps(request,ensure_ascii=True))
    proc=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'stdout.log').write_bytes(proc.stdout);(out/'stderr.log').write_bytes(proc.stderr);(out/'process-exit.json').write_text(json.dumps(dict(exit=proc.returncode)))
    if proc.returncode:raise ValueError('original selection capture failed: '+proc.stdout.decode(errors='replace')[-2500:]+proc.stderr.decode(errors='replace')[-1000:])
    value=load(out/'observations.json');value.update(owners=expected,script_sha256=hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),execution=dict(exit=proc.returncode,files={name:identity(out/name)for name in('capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json','original-tests.xml')}))
    value['corpus_sha256']=digest(value['cases']);errors=validate_reference(value,family,repo)
    if errors:raise ValueError(errors)
    (out/'reference.json').write_bytes((json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode('utf8',errors='backslashreplace'));return value

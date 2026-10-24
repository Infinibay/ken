"""Isolated original card projections, current-source checks and exact text budgets."""
SCRIPT = r'''
import copy,hashlib,importlib,json,pathlib,platform,sys,tempfile,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Passage,Span,CodeMatch
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval import piece_cards as module
if not pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original piece cards')
def passage(v):return Passage(**{**v,'entity':EntityKey(**v['entity']),'span':Span(**v['span']),'entity_span':Span(**v['entity_span'])})
def match(v):return CodeMatch(EntityKey(**v['entity']),v['score'],[passage(p)for p in v['evidence']],v['source_hash'],v.get('signals',{}),tuple(Span(**s)for s in v.get('owned_regions',[])))
records=[]
for case in request['cases']:
 data=case['input']
 with tempfile.TemporaryDirectory(prefix='ken-original-card-')as temporary:
  base=pathlib.Path(temporary);project=base/'project';project.mkdir()
  for name,content in data['catalog']['files'].items():
   p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes(content))
  try:
   catalog=SourceCatalog(project,{EntityKey(**o['key']):[passage(p)for p in o['passages']]for o in data['catalog']['owners']})
   if data.get('primary') is not None:
    primary=data['primary'];primary=EntityKey(**primary)if isinstance(primary,dict)else primary
    cards=[module.build_card(primary,data['piece_kind'],[EntityKey(**k)for k in data['supporting']],data['query'],catalog)]
   else:cards=module.build_piece_cards([match(v)for v in data['matches']],data['piece_kind'],data['query'],catalog,limit=data.get('limit',20))
   if 'card_updates'in data:
    updates=data['card_updates']
    for key,value in updates.get('card',{}).items():cards[0][key]=value
    cards[0]['unit'].update(updates.get('unit',{}))
    for index,values in updates.get('excerpts',{}).items():cards[0]['excerpts'][int(index)].update(values)
    if updates.get('duplicate'):cards[0]['excerpts'].append(copy.deepcopy(cards[0]['excerpts'][0]))
   mutation=data.get('mutation')
   if mutation:
    target=project/mutation['path']
    if mutation['op']=='write':target.write_bytes(bytes(mutation['bytes']))
    elif mutation['op']=='symlink':
     outside=base/'outside.py';outside.write_text('outside fixture\n');target.unlink();target.symlink_to(outside)
    elif mutation['op']=='replace-root':
     project.rename(base/'old-project');project.mkdir();target=project/mutation['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes(mutation['bytes']))
    else:raise ValueError('unknown card mutation')
   for card in cards:module.validate_card(card,catalog,check_disk=data.get('check_disk',True))
   result=dict(cards=cards,texts=[module.card_text(c)for c in cards],canonical=[module.canonical(c)for c in cards],characters=[len(module.canonical(c))for c in cards],projection=module.CARD_PROJECTION)
   records.append(dict(**case,result=result))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error).replace(str(project),'{project}').replace(str(base),'{scenario}'))))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-piece-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''

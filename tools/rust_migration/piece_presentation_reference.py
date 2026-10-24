"""Original public owner/card responses and compact Python-character budgets."""
from .piece_card_reference import SCRIPT as CARD_SCRIPT
SCRIPT = CARD_SCRIPT.split('records=[]')[0] + r'''
import importlib.metadata
from ken.retrieval.model import SearchRequest
from ken.retrieval.presentation import present
from ken.retrieval.piece_search import present_cards
for function in (present,present_cards):
 if not pathlib.Path(importlib.import_module(function.__module__).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original presentation')
records=[]
for case in request['cases']:
 data=case['input'];physical=data['catalog']if data['operation']=='cards'else data
 with tempfile.TemporaryDirectory(prefix='ken-original-presentation-')as temporary:
  base=pathlib.Path(temporary);project=base/'project';project.mkdir()
  for name,content in physical['files'].items():
   p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes(content))
  try:
   search=SearchRequest(**data['request']);matches=[match(v)for v in data['matches']]
   if data['operation']=='cards':
    catalog=SourceCatalog(project,{EntityKey(**o['key']):[passage(p)for p in o['passages']]for o in data['catalog']['owners']})
    if data.get('primary')is not None:
     primary=data['primary'];primary=EntityKey(**primary)if isinstance(primary,dict)else primary
     cards=[module.build_card(primary,data['piece_kind'],[EntityKey(**k)for k in data['supporting']],data['query'],catalog)]
    else:cards=module.build_piece_cards(matches,data['piece_kind'],data['query'],catalog,limit=data.get('limit',20))
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
    elif mutation['op']=='delete':target.unlink()
    elif mutation['op']=='symlink':
     outside=base/'outside.py';outside.write_text('outside fixture\n');target.unlink();target.symlink_to(outside)
    elif mutation['op']=='replace-root':
     project.rename(base/'old-project');project.mkdir();target=project/mutation['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes(mutation['bytes']))
    else:raise ValueError('unknown source mutation')
   response=(present_cards(cards,search,catalog,profile_version=data['profile_version'])if data['operation']=='cards'else present(matches,project,search,profile_version=data['profile_version'])).to_dict()
   # Normalize only machine-specific paths in diagnostics; budget policy itself
   # already ran with the real project path before this portable observation.
   response['warnings']=[warning.replace(str(project),'{project}').replace(str(base),'{scenario}')for warning in response['warnings']]
   result=dict(response=response,characters=len(json.dumps(response,ensure_ascii=False,separators=(',',':'))))
   records.append(dict(**case,result=result))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error).replace(str(project),'{project}').replace(str(base),'{scenario}'))))
''' + 'discovered=[];states=[]' + CARD_SCRIPT.split('discovered=[];states=[]')[1]
# Card observations have no numeric dependency; the presentation suite does.
SCRIPT = SCRIPT.replace("unicode=unicodedata.unidata_version)", "unicode=unicodedata.unidata_version,numpy=importlib.metadata.version('numpy'))")

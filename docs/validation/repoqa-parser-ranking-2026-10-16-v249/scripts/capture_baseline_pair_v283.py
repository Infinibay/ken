"""One preregistered baseline-stage diagnostic for the parser-variant top10 loss."""
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,sys,time
base=Path.cwd();out=base/'output/analysis/repoqa-before-after-v283';old=base/'output/development/repoqa-core-v222';engine=base/'output/frozen/bounded-symbol-ranking-v214';rid='86a2e6c50b5263a4c119cd96'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def backup(a,b):
 b.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect('file:'+str(a)+'?mode=ro',uri=True) as src,sqlite3.connect(b) as dst:src.backup(dst)
assert sha(engine/'SOURCE-MANIFEST.json')=='b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079'
for name,digest in json.loads((engine/'SOURCE-MANIFEST.json').read_text())['files'].items():assert sha(engine/name)==digest
request=next(r for r in map(json.loads,(old/'repoqa-requests.jsonl').read_text().splitlines()) if r['id']==rid);source=json.loads((old/'repoqa-sources.json').read_text())[request['repo_id']];original=Path(request['root']);out.mkdir(exist_ok=False);root=out/'project';root.mkdir();write(out/'registration.json',{'request':{k:v for k,v in request.items() if k!='root'},'baseline_engine_manifest_sha256':sha(engine/'SOURCE-MANIFEST.json'),'source_pins':source['source_pins'],'original_root':str(original),'labels_in_worker':False,'source_or_models_changed':False,'purpose':'One named diagnostic of the sole Rust variant top10 regression; not a new aggregate accuracy run. Original source/query fixed, no labels used in engine worker.','reserve':'CLOSED','producer_sha256':sha(Path(__file__))})
for name,digest in source['source_pins'].items():
 assert sha(original/name)==digest;target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/name,target)
(root/'.ken').mkdir();backup(original/'.ken/ken.db',root/'.ken/ken.db')
for name in ('search-context','vectors'):
 if (original/'.ken'/name).is_dir():shutil.copytree(original/'.ken'/name,root/'.ken'/name)
sys.path.insert(0,str(engine/'src'))
from ken.retrieval.connections import project_connection
from ken.retrieval.best_resources import default_resources
from ken.retrieval.best_search import _prepared
from ken.retrieval.candidates import owner_passages,owner_descriptions,retrieve_contextual
from ken.retrieval.model import SearchRequest
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.piece_cards import build_piece_cards
from ken.retrieval.storage import generation
resources=default_resources();search=SearchRequest(request['query'],target='symbol',piece_kind='symbol',limit=10,max_chars=12000)
with project_connection(root) as conn:
 project=_prepared(conn,root,resources);owners=owner_passages(conn)
 candidates,expanded=retrieve_contextual(conn,root,search,resources.profile,runtime=project.context,expand_query=resources.owner_ranker.prepare_query,encoders={'identity':resources.words,'behavior':resources.words})
 trace=RankingTrace(request_id=rid);descriptions=owner_descriptions(conn,candidates);matches=resources.owner_ranker.rank(search,candidates,descriptions,expanded_query=expanded,evidence_version=3,trace=trace)
 context=project.context.score(request['query'],expanded,owners,generation=generation(conn),policy=resources.profile.contextual)
 write(out/'context-owners.json',[{'path':key.path,'entity':key.to_dict(),'entity_span':dict(zip(('start_line','end_line'),project.pieces.catalog.extent(key)))} for key in context.source.owners])
 write(out/'stages.json',{'id':rid,'expanded_query':expanded,'contextual_original':[float(x) for x in context.original],'contextual_expanded':[float(x) for x in context.expanded],'proposals':[{'path':c.entity.path,'entity':c.entity.to_dict(),'signals':c.signals} for c in candidates],'numeric_trace':trace.to_dict(),'native_cards':build_piece_cards(matches,'symbol',expanded,project.pieces.catalog)[:10],'description_hashes':[{'path':key.path,'entity':key.to_dict(),'fields':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in d.fields.items()}} for key,d in descriptions.items()]})
 assert list(resources.context.providers)==['CPUExecutionProvider'] and resources.neural._session is None
assert not any(name in sys.modules for name in ('torch','transformers'))
for name,digest in source['source_pins'].items():assert sha(root/name)==digest and sha(original/name)==digest
shutil.rmtree(root/'.ken');write(out/'closure.json',{'all_outputs_closed':True,'requests':1,'neural_inference':False,'pins':{p.name:sha(p) for p in out.iterdir() if p.is_file()},'reserve':'CLOSED'});print(json.dumps({'closed':1,'out':str(out),'neural_inference':False}))

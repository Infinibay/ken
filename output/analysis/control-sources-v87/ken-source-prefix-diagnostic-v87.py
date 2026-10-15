"""Locate current source-prefix information loss, without fitting or regrading."""
import gc,hashlib,json,sqlite3,sys
from collections import defaultdict
from pathlib import Path
import ken
from tokenizers import Tokenizer
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.description import describe_owner
from ken.retrieval.model import EntityKey
from ken.retrieval.source_views import owner_view_texts
from ken.retrieval.storage import load_passage_map
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
A=R/'output/models/cpu-context-registration-v42.json';V=R/'output/analysis/context-views-source7-v69';P=R/'output/analysis/c-source-reindex-v66c';D=R/'experiments/search-engine/datasets/development.jsonl';T=R/'output/development/cpu-shared-field-terms-v81-loo/report.json';O=R/'output/analysis/source-prefix-diagnostic-v87';O.mkdir(exist_ok=False)
assets=json.loads(A.read_text());assert sha(A)=='9de3e49ef29ce4672b5b77dfca0078a4eba82412a64c318cafe048b512787d7a'
tokfile=Path(assets['root'])/'tokenizer.json';assert sha(tokfile)==assets['artifacts']['tokenizer.json']
tokenizer=Tokenizer.from_file(str(tokfile));tokenizer.no_padding();tokenizer.enable_truncation(max_length=512)
source=json.loads((V/'registration.json').read_text());index=json.loads((P/'registration.json').read_text())
roots={k:Path(v)for k,v in json.loads((R/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
cases=list(map(json.loads,D.read_text().splitlines()));assert len(cases)==400 and len({c['id']for c in cases})==400
outcomes={x['id']:x for x in json.loads(T.read_text())['rows']};assert set(outcomes)=={c['id']for c in cases}
bindings={str(p):sha(p)for p in(A,tokfile,V/'registration.json',P/'registration.json',D,T,R/'experiments/search-engine/cpu-source-prefix-diagnostic-v87.md')};receipt=verify_frozen_source(E)
rows=[]
for repo in sorted(roots):
    ip=P/'indices'/(repo+'.db');vp=V/(repo+'-source.db')
    assert sha(ip)==index['source_repos'][repo]['new_source_index_sha256']and sha(vp)==source['source_repos'][repo]['source_db_sha256']
    bindings[str(ip)],bindings[str(vp)]=sha(ip),sha(vp)
    db=sqlite3.connect(f'file:{ip}?mode=ro',uri=True);db.row_factory=sqlite3.Row
    grouped=defaultdict(list)
    for passage in load_passage_map(db).values():grouped[passage.entity].append(passage)
    db.close();db=sqlite3.connect(f'file:{vp}?mode=ro',uri=True)
    recorded={EntityKey(**json.loads(e)):(digest,th,text)for e,digest,th,text in db.execute("SELECT entity,source_hash,o.text_hash,text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE view='implementation'")}
    for case in(c for c in cases if c['repo_id']==repo):
        alternatives=[]
        for alternative in case['alternatives']:
            path=alternative['path'];physical=roots[repo]/path;assert sha(physical)==alternative['source_hash'];bindings[str(physical)]=sha(physical)
            anchors={line for s in alternative['anchors']for line in range(s['start_line'],s['end_line']+1)}
            if alternative['entity']is not None:
                entities=[EntityKey(path,**alternative['entity'])]
            else:
                entities=[entity for entity,passages in grouped.items()if entity.path==path and anchors<={line for p in passages for line in range(p.span.start_line,p.span.end_line+1)}]
            values=[]
            for entity in entities:
                passages=grouped.get(entity)
                if not passages:
                    values.append({'entity':entity.to_dict(),'missing_entity':True});continue
                owner=describe_owner(passages);text=owner_view_texts(owner)['implementation'];digest,th,stored=recorded[entity]
                assert text==stored and sha(physical)==digest and hashlib.sha256(text.encode()).hexdigest()==th
                implementation=owner.fields['implementation'];assert text.endswith(implementation)
                character=len(text)-len(implementation);positions={};pieces=[]
                for passage in sorted({p.span:p for p in passages}.values(),key=lambda p:p.span.start_line):
                    offset=max(0,(passage.implementation_start_line or passage.span.start_line)-passage.span.start_line)
                    for relative,line in enumerate(passage.fields['body'].split('\n')[offset:],offset):
                        pieces.append(line);positions[passage.span.start_line+relative]=(character,character+len(line.rstrip()));character+=len(line)+1
                assert '\n'.join(pieces)==implementation
                encoded=tokenizer.encode(text);cutoff=max((end for start,end in encoded.offsets if end>start),default=0)
                assert len(encoded.ids)<=512
                missing=sorted(anchors-positions.keys());beyond=sorted(line for line in anchors&positions.keys()if positions[line][1]>cutoff)
                values.append({'entity':entity.to_dict(),'text_sha256':th,'encoded_tokens':len(encoded.ids),'characters':len(text),'encoded_character_end':cutoff,'missing_owned_implementation_anchor_lines':missing,'owned_anchor_lines_beyond_prefix':beyond,'all_original_anchor_lines_in_prefix':not missing and not beyond})
            alternatives.append({'path':path,'original_entity':alternative['entity'],'anchor_lines':sorted(anchors),'eligible_owners':values})
        rows.append({'id':case['id'],'repo':repo,'strict_hit81':outcomes[case['id']]['strict_hit'],'identity_hit81':outcomes[case['id']]['identity_hit'],'alternatives':alternatives})
    db.close();del grouped,recorded;gc.collect()
    print(json.dumps({'repo':repo,'queries':len(rows)}),flush=True)
assert len(rows)==400 and {r['id']for r in rows}==set(outcomes)
for row in rows:
    owners=[v for a in row['alternatives']for v in a['eligible_owners']]
    row['any_eligible_owner_all_anchors_in_prefix']=any(v.get('all_original_anchor_lines_in_prefix',False)for v in owners)
    row['any_eligible_owner_all_anchors_owned']=any(not v.get('missing_entity')and not v['missing_owned_implementation_anchor_lines']for v in owners)
summary={}
for name,subset in [('all',rows),('strict_hits',[r for r in rows if r['strict_hit81']]),('wrong_identity',[r for r in rows if not r['identity_hit81']]),('missing_visible_anchor',[r for r in rows if r['identity_hit81']and not r['strict_hit81']])]:
    summary[name]={'total':len(subset),'has_complete_anchor_prefix':sum(r['any_eligible_owner_all_anchors_in_prefix']for r in subset),'has_owned_anchors_but_no_complete_prefix':sum(r['any_eligible_owner_all_anchors_owned']and not r['any_eligible_owner_all_anchors_in_prefix']for r in subset),'no_owner_complete_anchor_implementation':sum(not r['any_eligible_owner_all_anchors_owned']for r in subset)}
assert all(sha(p)==digest for p,digest in bindings.items())and verify_frozen_source(E)==receipt
record={'scope':'Information availability diagnostic on original400 exposed development references, not acceptance/regrading/causal proof or an attainable-accuracy bound','engine_receipt':receipt,'script_sha256':sha(__file__),'inputs':bindings,'summary':summary,'rows':rows,'no_inference_or_fit':True}
(O/'report.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(summary),flush=True)

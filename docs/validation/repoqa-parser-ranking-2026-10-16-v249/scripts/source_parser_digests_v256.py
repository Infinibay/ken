"""Hash parser output for every source file, without query/reference data."""
import argparse,dataclasses,hashlib,json,sys
from pathlib import Path
from ken.parsers import detect_language
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
base=Path.cwd();sources=json.loads((base/'output/development/repoqa-core-v222/repoqa-sources.json').read_text());rows=[]
requests=[json.loads(x) for x in (base/'output/development/repoqa-core-v222/repoqa-requests.jsonl').read_text().splitlines()]
roots={r['repo_id']:Path(r['root']) for r in requests}
for group,description in sources.items():
 if not group.startswith(('cpp--','rust--')):continue
 root=roots[group]
 if not root.is_absolute():raise ValueError(description.keys())
 for name,digest in description['source_pins'].items():
  path=root/name;source=path.read_bytes();assert hashlib.sha256(source).hexdigest()==digest
  try:
   detected=detect_language(path,source=source);language=detected[0] if detected else None;parsed=detected[1](source,path.name) if detected else None
   serial=json.dumps(dataclasses.asdict(parsed),sort_keys=True,separators=(',',':')) if parsed else None
   rows.append({'repo_id':group,'path':name,'source_hash':digest,'language':language,'parsed_sha256':hashlib.sha256(serial.encode()).hexdigest() if serial else None})
  except Exception as error:rows.append({'repo_id':group,'path':name,'error':f'{type(error).__name__}: {error}'})
value={'rows':rows,'source_only':True,'labels_used':False,'engine_module':sys.modules['ken'].__file__,'errors':sum('error' in r for r in rows)}
a.out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='rows'}))

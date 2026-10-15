import hashlib,json,urllib.request,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');O=R/'output/models/query-actions-v90';O.mkdir(exist_ok=True);assert not any(O.iterdir())
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Ken-local-research'})
 with urllib.request.urlopen(req,timeout=60)as response:return response.read()
commit=json.loads(fetch('https://api.github.com/repos/nltk/nltk_data/commits/gh-pages'))['sha']
base='https://raw.githubusercontent.com/nltk/nltk_data/'+commit
index=fetch(base+'/index.xml');root=ET.fromstring(index);package=next(p for p in root.iter('package')if p.attrib['id']=='averaged_perceptron_tagger_eng')
assert package.attrib['license']=='MIT License'
archive=fetch(base+'/packages/taggers/averaged_perceptron_tagger_eng.zip')
expected=package.attrib['sha256_checksum'];assert hashlib.sha256(archive).hexdigest()==expected
(O/'index.xml').write_bytes(index);z=O/'averaged_perceptron_tagger_eng.zip';z.write_bytes(archive)
with zipfile.ZipFile(z)as opened:
 for entry in opened.infolist():
  assert not Path(entry.filename).is_absolute()and'..'not in Path(entry.filename).parts
  if not entry.is_dir():assert entry.filename.endswith('.json')
 opened.extractall(O)
files={str(p.relative_to(O)):hashlib.sha256(p.read_bytes()).hexdigest()for p in O.rglob('*')if p.is_file()}
r={'scope':'Official tiny POS data only; no query/code/model-fitting inputs read','repository_commit':commit,'model':'averaged_perceptron_tagger_eng','license':package.attrib['license'],'package':package.attrib,'files':files,'protocol_sha256':hashlib.sha256((R/'experiments/search-engine/cpu-query-actions-v90.md').read_bytes()).hexdigest(),'bytes':sum(p.stat().st_size for p in O.rglob('*')if p.is_file())}
(O/'registration.json').write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items()if k not in('files','package')},indent=2))

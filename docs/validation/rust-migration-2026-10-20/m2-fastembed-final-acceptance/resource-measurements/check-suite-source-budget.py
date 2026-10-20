from pathlib import Path
import hashlib,json,shutil,urllib.parse,urllib.request
from tools.rust_migration.preparation import PreparedNativeFastEmbed
from tools.rust_migration.fastembed_sources import suite_source_lease,capacity_plan
from tools.rust_migration.fastembed_ownership import MODELS
root=Path.cwd();area=root/'.ken/rust-migration/m2-fastembed';cache=area/'suite-budget-sources';cache.mkdir(exist_ok=True);assert list(cache.iterdir())==[]
registry=root/'crates/ken-models/resources/fastembed-catalog.json';catalogue=json.loads(registry.read_bytes());plan=capacity_plan(catalogue)
def public_data(url,timeout):
 parts=urllib.parse.unquote(urllib.parse.urlsplit(url).path).strip('/').split('/');assert parts[2]=='resolve'
 return (area/'sources'/(parts[0]+'--'+parts[1])/parts[3]/'/'.join(parts[4:])).open('rb')
urllib.request.urlopen=public_data
prepared=PreparedNativeFastEmbed(root/'target/release/examples/fastembed_probe',cache,registry,acquire=True)
records=[]
with suite_source_lease(prepared,environ={})as ready:
 for name in MODELS:
  model=next(m for m in catalogue['models']if m['name']==name);assets=model['assets'];snapshot=ready.sources/assets['model_id'].replace('/','--')/assets['revision']
  copies=[ready.sources/'mutable-copy',ready.sources/'private-copy']
  for destination in copies:
   shutil.copytree(snapshot,destination)
   for key,row in assets['artifacts'].items():
    with (destination/key).open('rb')as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    assert (destination/key).stat().st_ino!=(snapshot/key).stat().st_ino
  files=[p for p in cache.rglob('*')if p.is_file()and not p.is_symlink()]
  allocated=sum(p.stat().st_blocks*512 for p in files)
  assert allocated<plan['process_tests']['required_free_bytes']
  records.append({'model':name,'allocated_bytes_all_held_sources_and_two_current_copies':allocated})
  for destination in copies:shutil.rmtree(destination)
  print(json.dumps(records[-1]),flush=True)
assert list(cache.iterdir())==[]
(area/'suite-source-budget-proof.json').write_text(json.dumps({'status':'all real registered bytes/copy hashes verified; network replaced by read-only canonical source cache','all_five_sources_held':True,'all_leases_removed':True,'plan':plan,'records':records},indent=2)+'\n')
print('full real suite preparation/copy budget GREEN',flush=True)

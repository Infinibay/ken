"""Real pinned bytes, bounded owned copies; network replaced by read-only source cache."""
import hashlib,json,shutil,sys,urllib.parse,urllib.request
from pathlib import Path
from tools.rust_migration.preparation import PreparedNativeFastEmbed
from tools.rust_migration.fastembed_sources import capacity_plan,source_lease
from tools.rust_migration.fastembed_ownership import MODELS
root=Path.cwd();area=root/'.ken/rust-migration/m2-fastembed';sources=area/'bounded-schedule-sources';sources.mkdir(exist_ok=True)
assert list(sources.iterdir())==[]
registry=root/'crates/ken-models/resources/fastembed-catalog.json';catalogue=json.loads(registry.read_bytes());plan=capacity_plan(catalogue)
canonical=area/'sources';urls=[]
def open_registered(url,timeout):
    parsed=urllib.parse.urlsplit(url);parts=urllib.parse.unquote(parsed.path).strip('/').split('/')
    assert parsed.scheme=='https'and parsed.netloc=='huggingface.co'and parts[2]=='resolve'
    path=canonical/(parts[0]+'--'+parts[1])/parts[3]/'/'.join(parts[4:]);urls.append(url)
    return path.open('rb')
urllib.request.urlopen=open_registered
prepared=PreparedNativeFastEmbed(root/'target/release/examples/fastembed_probe',sources,registry,acquire=True)
records=[];peak=0
schedule=[(d,2)for d in catalogue['models']]+[(next(d for d in catalogue['models']if d['name']==name),3)for name in MODELS]
for definition,copies in schedule:
    with source_lease(prepared,definition,copies=copies)as leased:
        snapshot=leased.sources/definition['assets']['model_id'].replace('/','--')/definition['assets']['revision']
        for index in range(copies-1):
            copied=leased.sources/f'private-copy-{index}';shutil.copytree(snapshot,copied)
            for name,record in definition['assets']['artifacts'].items():
                with (copied/name).open('rb')as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==record['sha256']
                assert (copied/name).stat().st_ino!=(snapshot/name).stat().st_ino
        files=[p for p in leased.sources.rglob('*')if p.is_file()]
        observed=sum(p.stat().st_size for p in files);allocated=sum(p.stat().st_blocks*512 for p in files)
        declared=sum(r['bytes']for r in definition['assets']['artifacts'].values())*copies
        assert observed==declared and allocated<plan['peak_bytes']
        peak=max(peak,allocated)
        records.append({'model':definition['name'],'copies':copies,'verified_bytes':observed,'allocated_bytes':allocated})
    assert list(sources.iterdir())==[]
    print(json.dumps(records[-1]),flush=True)
result={'format':'ken-fastembed-bounded-source-schedule/1','models':30,'ownership_families':MODELS,'all_copies_verified':True,'all_leases_removed':True,'canonical_cache_read_only':True,'peak_allocated_bytes':peak,'plan':plan,'records':records,'network':'registered HTTPS URLs resolved to read-only preverified local bytes; separate real HTTPS download tested'}
(area/'bounded-source-schedule.json').write_text(json.dumps(result,indent=2)+'\n')
print('complete registered source/copy schedule GREEN',flush=True)

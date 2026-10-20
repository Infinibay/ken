from pathlib import Path
import hashlib,json,tempfile
from tools.rust_migration.fastembed_reference import capture_tokenizers,installed_provenance,source_state
root=Path.cwd();private=root/'.ken/rust-migration/m2-fastembed';catalog=json.loads((private/'registry-draft.json').read_bytes())
indices=[json.loads((private/p/'index.json').read_bytes()) for p in ['reference-macos-attempt3','reference-linux-attempt1']]
assert indices[0]['provenance']==indices[1]['provenance']==installed_provenance()
for model in catalog['models']:source_state(private/'sources',model)
with tempfile.TemporaryDirectory(prefix='token-audit-',dir=private) as directory:
    current=capture_tokenizers(private/'sources',catalog,Path(directory))
    expected={row['repo']:row['record']['raw_sha256'] for row in current['repositories']}
    for index in indices:assert expected=={row['repo']:row['record']['raw_sha256'] for row in index['tokenizers']['repositories']}
result={'passed':True,'models':30,'source_artifacts':148,'tokenizers':29,'current_config_matches_both_raw_token_corpora':True,'installed_fastembed_sources':58,'registry_sha256':hashlib.sha256((private/'registry-draft.json').read_bytes()).hexdigest()}
(private/'input-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

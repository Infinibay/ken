from pathlib import Path
import json,os,sys,tempfile,shutil
from tools.rust_migration.source_validate import capture_native_sources,run_native_walk,source_identity
r=Path.cwd();out=Path(sys.argv[1]);out.mkdir(parents=True)
probe=Path(os.environ['CARGO_TARGET_DIR'])/'release/examples/source_probe'
for corpus,filename in [('baseline','reference.json'),('review','reference-review.json')]:
    original=json.loads((r/'crates/ken-core/tests/fixtures/source-discovery'/filename).read_bytes())
    result=capture_native_sources(probe,original,r,out/corpus)
    print(corpus,len(result['observations']),'walks passed')
with tempfile.TemporaryDirectory(prefix='ken-source-process-') as t:
    sandbox=Path(t).resolve();(sandbox/'empty-path').mkdir();(sandbox/'home').mkdir()
    native=sandbox/'source-probe';shutil.copy2(probe,native)
    rows=[]
    for index,rule in enumerate(['a[z-a].py', 'a\\', '!', 'a[a--b].py']):
        project=sandbox/f'invalid-{index}';project.mkdir()
        (project/'.gitignore').write_text(rule+'\n');(project/'az.py').write_text('')
        actual=run_native_walk(native,dict(root=str(project),scope='.'),out/f'invalid-{index}',sandbox)
        assert not actual['entries'] and actual['errors'] and all(e==dict(kind='invalid_rules',path='.gitignore') for e in actual['errors']),actual
        rows.append(dict(rule=rule,actual=actual))
    (out/'invalid.json').write_text(json.dumps(rows,indent=2)+'\n')
print('invalid patterns rejected explicitly')

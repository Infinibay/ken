"""Retain closed training/export evidence; public400 capture remains separate."""
from pathlib import Path
import gzip,hashlib,importlib.metadata,json,platform,sys
w=Path.cwd();out=w/'output/analysis/external-code-adaptation-archive-v188';out.mkdir(exist_ok=False)
generated=out/'generated';generated.mkdir()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def rows(p):
    with Path(p).open() as f:
        for line in f:yield json.loads(line)
def metadata(function):
    return {k:v for k,v in function.items() if k not in {'query','code'}} | {
        'query_sha256':hashlib.sha256(function['query'].encode()).hexdigest()}
data=w/'output/development/external-code-data-v185/curated-c'
for name in ['functions','train','validation']:
    with (generated/(name+'-metadata.jsonl')).open('w') as f:
        for record in rows(data/(name+'.jsonl')):
            if name=='functions':value=metadata(record)
            else:value={k:v for k,v in record.items() if k not in {'query','candidates'}} | {
                'query_sha256':hashlib.sha256(record['query'].encode()).hexdigest(),
                'candidates':[metadata(c) for c in record['candidates']]}
            f.write(json.dumps(value,sort_keys=True)+'\n')
versions={name:importlib.metadata.version(name) for name in ['torch','transformers','tokenizers','numpy',
    'safetensors','onnx','onnxruntime','pyarrow','tree-sitter','tree-sitter-python','tree-sitter-java','tree-sitter-javascript']}
(generated/'environment.json').write_text(json.dumps({'python':sys.version,'platform':platform.platform(),
    'versions':versions,'training_uses_original_venv_torch_via_plain_path_pth':True},indent=2))
paths=[
 'experiments/search-engine/external_code_data.py','experiments/search-engine/test_external_code_data.py',
 'experiments/search-engine/source_syntax_view.py',
 'experiments/search-engine/code_adaptation_model.py','experiments/search-engine/test_code_adaptation_model.py',
 'experiments/search-engine/code_tail_export.py','experiments/search-engine/test_code_tail_export.py',
 'output/analysis/external-code-data-v185-protocol.md','output/analysis/codesearchnet-discovery-v185.json',
 'output/analysis/codesearchnet-tree-v185.json','output/analysis/download-codesearchnet-v185.py',
 'output/analysis/prepare-external-code-data-v185.py','output/analysis/external_code_data-v185b.py',
 'output/analysis/prepare-external-code-data-v185b.py',
 'output/analysis/external-data-reference-review-v185.json','output/analysis/external-data-reference-review-v185.md',
 'output/analysis/external-data-reference-review-v185-supplement-c.json','output/analysis/external-data-reference-review-v185-supplement-c.md',
 'output/analysis/download-ettin-training-v185.py','output/analysis/probe-code-adaptation-mps-v185.py',
 'output/analysis/preflight-tail-export-v185.py','output/analysis/tail-export-preflight-v185.json',
 'output/analysis/code-domain-adaptation-v186-protocol.md','output/analysis/train-code-domain-v186.py',
 'output/analysis/code-domain-v186-memory-operations.md','output/analysis/bound-code-training-v186a.py',
 'output/analysis/bound-code-training-v186.py','output/analysis/export-code-tail-v188.py',
 'output/analysis/audit-code-domain-completion-v189.py','output/analysis/code-domain-completion-audit-v189.json',
 'output/analysis/code-domain-v189-piece-policy-before-capture.md','output/analysis/code-domain-v189-piece-policy-registration.json',
 'output/analysis/capture-code-domain-v189.py','output/analysis/grade-code-domain-v189.py',
 'output/analysis/run-code-domain-validation-v189.py','output/analysis/verify-code-domain-inputs-v189.py',
 'output/analysis/smoke-code-capture-api-v189.py','output/analysis/code-ranking-research-v190.md',
 'output/development/external-code-data-v185/registration.json',
 'output/development/external-code-data-v185/curated-b/registration.json',
 'output/development/external-code-data-v185/curated-c/registration.json',
 'output/development/external-code-data-v185/curated-c/protected-source-manifest.json',
 'output/models/ettin-code-adaptation-source-v185/registration.json',
 'output/development/code-adaptation-mps-probe-v185/receipt.json',
 'output/development/code-domain-adaptation-v186/registration.json',
 'output/development/code-domain-adaptation-v186/progress.json',
 'output/development/code-domain-adaptation-v186/used-training-ids.json',
 'output/development/code-domain-adaptation-v186/baseline-summary.json',
 'output/development/code-domain-adaptation-v186/final-summary.json',
 'output/development/code-domain-adaptation-v186/baseline-validation.jsonl',
 'output/development/code-domain-adaptation-v186/final-validation.jsonl',
 'output/development/code-domain-adaptation-v186/operations.json',
 'output/development/code-domain-adaptation-v186/operations-b.json',
 'output/development/code-domain-adaptation-v186/final-tail.safetensors',
 'output/development/code-tail-identity-export-v188/registration.json',
 'output/development/code-tail-identity-export-v188/export-receipt.json',
 'output/development/code-tail-trained-export-v188/registration.json',
 'output/development/code-tail-trained-export-v188/export-receipt.json',
 'output/development/code-capture-api-smoke-v189/registration.json',
]
paths += [str(p.relative_to(w)) for p in (w/'output/development/code-domain-adaptation-v186/checkpoints').glob('*/manifest.json')]
paths += [str(p.relative_to(w)) for p in (w/'output/development/code-domain-adaptation-v186').glob('resume-*.log')]
paths += [str(p.relative_to(w)) for p in (w/'output/development/code-capture-api-smoke-v189').glob('*/receipt.json')]
paths += [str(p.relative_to(w)) for p in generated.iterdir()]
paths += ['/private/tmp/ken-code-domain-adaptation-v186.log','/private/tmp/ken-bound-code-training-v186.log',
          '/private/tmp/ken-bound-code-training-v186b.log',
          '/private/tmp/ken-code-tail-export-v188-red.log','/private/tmp/ken-code-tail-export-v188-fixture-failure.log',
          '/private/tmp/ken-code-tail-export-v188-green.log','/private/tmp/ken-external-code-and-export-v189-missing-pythonpath.log',
          '/private/tmp/ken-external-code-and-export-v189-tests.log','/private/tmp/ken-code-domain-completion-audit-v189.log',
          '/private/tmp/ken-code-adaptation-model-v185-red.log','/private/tmp/ken-code-adaptation-model-v185-green.log']
training=json.loads((w/'output/development/code-domain-adaptation-v186/registration.json').read_text())
assert training['external_gate'] and training['steps']==5484
assert sha(w/'output/development/code-domain-adaptation-v186/final-tail.safetensors')==training['final_checkpoint_sha256']
payload=out/'payload';payload.mkdir();entries=[]
for i,name in enumerate(paths):
    source=Path(name) if Path(name).is_absolute() else w/name
    assert source.is_file(),source
    value=source.read_bytes();blob=gzip.compress(value,compresslevel=9,mtime=0)
    target=payload/f'{i:04d}.gz';target.write_bytes(blob)
    entries.append({'source':str(source),'project_relative':str(source.relative_to(w)) if source.is_relative_to(w) else None,
                    'payload':str(target.relative_to(out)),'sha256':hashlib.sha256(value).hexdigest(),
                    'gzip_sha256':sha(target),'bytes':len(value),'gzip_bytes':len(blob)})
manifest={'scope':'Closed E185data/A186training/V188CPUexport, fixed V189producers registered; NO public400 results/private payloads',
 'producer_sha256':sha(__file__),'entries':entries,
 'omitted':'1GB upstream parquets and273MB public base model/graph; immutable upstream pins and download producers retained. Full curated code/query payloads omitted; exact metadata/order hashes and regenerating producer retained.',
 'final_tail_retained':True,'source_base_model_revision':'d166fa88ddde3c42bc3ee92f7df476d941c8204a',
 'external_baseline':2768,'external_final':2799,'external_queries':3000,
 'current_new200_installed_top1':159,'current_new200_installed_recall10':195,
 'public400_status':'Running separately, not scored at archive creation','reserve':'CLOSED'}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
for e in entries:
    assert sha(out/e['payload'])==e['gzip_sha256']
    assert hashlib.sha256(gzip.decompress((out/e['payload']).read_bytes())).hexdigest()==e['sha256']
print(json.dumps({'files':len(entries),'gzip_bytes':sum(e['gzip_bytes'] for e in entries),
                  'manifest_sha256':sha(out/'manifest.json')}),flush=True)

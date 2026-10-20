from pathlib import Path
import gzip,json,subprocess,sys,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();root=args.repo.resolve()
proof=root/'docs/validation/rust-migration-2026-10-20/m2-fastembed'
catalog=json.loads((root/'crates/ken-models/resources/fastembed-catalog.json').read_text())
cases=json.loads((proof/'cases.json').read_text())
requests=[];expected=[];seen=set()
for model in catalog['models']:
 repo=model['assets']['model_id']
 if repo not in seen:
  seen.add(repo)
  tokens=json.loads(gzip.decompress((proof/'reference-macos'/('tokens-'+repo.replace('/','--')+'.json.gz')).read_bytes()))
  requests.append({'model':model['name'].upper(),'cases':[{'id':c['id'],'side':'passage','texts':c['texts']}for c in tokens['cases']]})
  linux_tokens=json.loads(gzip.decompress((proof/'reference-linux'/('tokens-'+repo.replace('/','--')+'.json.gz')).read_bytes()));assert linux_tokens==tokens
  expected.append(('raw',tokens))
 requests.append({'model':model['name'],'cases':[{'id':c['id'],**c['input']}for c in cases if c['model']==model['name']]})
 expected.append(('model',model['name']))
binary=args.probe.resolve()
run=subprocess.run([str(binary),str(root/'crates/ken-models/resources/fastembed-catalog.json'),str(root/'.ken/rust-migration/m2-fastembed/sources'),str(root/'.ken/rust-migration/m2-fastembed')],input=''.join(json.dumps(r)+'\n' for r in requests),text=True,capture_output=True,check=True)
outputs=[json.loads(line)for line in run.stdout.splitlines()];assert len(outputs)==len(expected)
raw_count=cases_count=feed_count=failed_cases=empty_cases=0
for request,actual,(kind,original) in zip(requests,outputs,expected):
 assert actual['model']==request['model']
 if kind=='raw':
  raw_count+=1
  for case,observed in zip(original['cases'],actual['results'],strict=True):
   assert observed['id']==case['id']; enc=case['encodings']
   wanted={'shape':[len(enc),len(enc[0]['ids'])], 'ids':[x for e in enc for x in e['ids']], 'attention_mask':[x for e in enc for x in e['attention_mask']]}
   assert observed['batches']==[wanted],(original['repo'],case['id'])
 else:
  i=next(i for i,m in enumerate(catalog['models'])if m['name']==original)
  for platform in ['reference-macos','reference-linux']:
   golden=json.loads(gzip.decompress((proof/platform/f'{i:02}.json.gz').read_bytes()))
   for original_case,observed in zip(golden['results'],actual['results'],strict=True):
    assert original_case['id']==observed['id']
    if 'error'in original_case:
     if platform=='reference-macos':failed_cases+=1
     continue
    if platform=='reference-macos':cases_count+=1
    assert len(original_case['batches'])==len(observed['batches']),(original,original_case['id'])
    if platform=='reference-macos' and not observed['batches']:empty_cases+=1
    for batch,tokens in zip(original_case['batches'],observed['batches'],strict=True):
     feeds=batch['inputs'];ids=feeds['input_ids'];assert tokens['shape']==ids['shape'];assert tokens['ids']==ids['values'],(platform,original,original_case['id'],'ids')
     if 'attention_mask'in feeds:assert tokens['attention_mask']==feeds['attention_mask']['values'],(platform,original,original_case['id'],'mask')
     if platform=='reference-macos':feed_count+=1
out=args.out.resolve();out.mkdir(exist_ok=True,parents=True)
(out/'requests.jsonl.gz').write_bytes(gzip.compress((''.join(json.dumps(r)+'\n'for r in requests)).encode(),mtime=0))
(out/'native.jsonl.gz').write_bytes(gzip.compress(run.stdout.encode(),mtime=0));(out/'native.stderr').write_text(run.stderr)
summary={'raw_tokenizers':raw_count,'raw_cases':raw_count*4,'model_cases':cases_count,'empty_cases':empty_cases,'known_original_pre_inference_failures':failed_cases,'successful_input_batches_compared_both_platforms':feed_count,'no_expected_tokens_in_native_requests':True,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

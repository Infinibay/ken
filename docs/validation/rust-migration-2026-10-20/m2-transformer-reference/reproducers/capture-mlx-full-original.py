"""Private actual MLX encoder corpus; all inputs are synthetic/public test text."""
from pathlib import Path
from importlib.metadata import version
import argparse,hashlib,json,resource,time
import numpy as np
import mlx.core as mx,huggingface_hub
from ken.embedder.mlx_backend import MLXEncoder
from ken.retrieval.profile import EncoderSpec
import ken.embedder.mlx_backend as module
parser=argparse.ArgumentParser();parser.add_argument('--dtype',choices=['float32','float16','bfloat16'],required=True);args=parser.parse_args()
root=Path('/Users/andres/Projects/ken');area=root/'.ken/rust-migration/m2-optional';pre=area/'preflight';model_id='Qwen/Qwen3-Embedding-0.6B';revision='97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3';snapshot=area/'sources/Qwen--Qwen3-Embedding-0.6B'/revision
registration=json.loads((snapshot/'VERIFIED-DATA.json').read_text());requests=json.loads((pre/'st-original-full/qwen-cpu-float32.json').read_text())['requests']
original=root/'.ken/rust-migration/m0-m1/reference/src/ken/embedder/mlx_backend.py';assert Path(module.__file__).resolve()==original.resolve();source_sha=hashlib.sha256(original.read_bytes()).hexdigest()
def local_snapshot(model,**options):
 assert model==model_id and options=={'revision':revision,'local_files_only':True,'token':False};return str(snapshot)
huggingface_hub.snapshot_download=local_snapshot
spec=EncoderSpec(model_id,revision,backend='mlx',dtype=args.dtype,sequence_length=512,batch_size=16);encoder=MLXEncoder(spec)
assert encoder.embed_passages([])==[] and encoder._model is None
counts={r['id']:[encoder.token_count(t) for t in r['texts']] for r in requests};assert encoder._model is None;long_count=encoder.token_count('a '*700);assert long_count>512
start=time.monotonic();encoder._load();preparation=time.monotonic()-start;model=encoder._model;tokenizer=encoder._tokenizer
feeds=[];active_case=None;current={};tokenizations=[]
class ObservedTokenizer:
 def __getattr__(self,name):return getattr(tokenizer,name)
 def __call__(self,texts,**options):
  result=tokenizer(texts,**options);encoded=result['input_ids'];order=sorted(range(len(encoded)),key=lambda i:len(encoded[i]));current.update(encoded=encoded,order=order,offset=0)
  tokenizations.append({'case':active_case,'payload':texts,'options':options,'encoded':encoded,'order':order});return result
def captured(ids):
 hidden=model(ids);indices=current['order'][current['offset']:current['offset']+ids.shape[0]];current['offset']+=ids.shape[0]
 feeds.append({'case':active_case,'actual_device':'mlx-gpu','weight_dtype':args.dtype,'shape':list(ids.shape),'input_ids':np.asarray(ids).tolist(),'real_lengths':[len(current['encoded'][i]) for i in indices],'original_indices':indices});return hidden
encoder._tokenizer=ObservedTokenizer();encoder._model=captured
results=[]
for request in requests:
 active_case=request['id'];feed_start=len(feeds);start=time.monotonic()
 try:
  values=np.asarray(encoder.embed_query(request['texts'][0]) if request['side']=='query' else encoder.embed_passages(request['texts']),dtype=np.float32)
  if values.ndim==1:values=values.reshape(1,-1)
  record={'id':request['id'],'passed_original_call':True,'shape':list(values.shape),'vectors_f32le_hex':values.astype('<f4',copy=False).tobytes().hex(),'finite':bool(np.isfinite(values).all()),'device_after':'mlx'}
 except Exception as failure:record={'id':request['id'],'passed_original_call':False,'error':type(failure).__name__+': '+str(failure),'device_after':'mlx'}
 record.update(elapsed_s=time.monotonic()-start,feed_range=[feed_start,len(feeds)]);results.append(record);print(json.dumps({'dtype':args.dtype,'case':request['id'],'original_success':record['passed_original_call'],'elapsed_s':record['elapsed_s']}),flush=True)
assert hashlib.sha256(original.read_bytes()).hexdigest()==source_sha
receipt={'format':'ken-mlx-full-original-exploration/1','settings':{'model_id':model_id,'revision':revision,'dtype':args.dtype,'sequence_length':512,'batch_size':16},'model_registration':registration,'original_source_sha256':source_sha,'requests':requests,'results':results,'feeds':feeds,'tokenizations':tokenizations,'counts':counts,'long_count':long_count,'empty_batch_did_not_load':True,'count_did_not_load_model':True,'preparation_s':preparation,'package_versions':{p:version(p) for p in ['mlx','mlx-lm','transformers','numpy','tokenizers']},'peak_rss_process_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'device_info':mx.device_info(),'model_inference_accepted':False}
out=pre/'mlx-original-full';out.mkdir(exist_ok=True);(out/(args.dtype+'.json')).write_text(json.dumps(receipt)+'\n');print(json.dumps({'captured':True,'cases':len(results),'feeds':len(feeds),'model_inference_accepted':False}))

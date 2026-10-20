"""Private frozen-original corpus expansion; never used by the product runtime."""
from pathlib import Path
import argparse,gc,hashlib,inspect,json,os,resource,time,weakref
import numpy as np
import torch
from ken.embedder.st_backend import SentenceTransformerEmbedder
import ken.embedder.st_backend as module
parser=argparse.ArgumentParser();parser.add_argument('--model',choices=['qwen','bge'],required=True);parser.add_argument('--dtype',choices=['float32','float16','bfloat16'],required=True);parser.add_argument('--device',choices=['cpu','mps'],required=True);args=parser.parse_args()
root=Path('/Users/andres/Projects/ken');area=root/'.ken/rust-migration/m2-optional';pre=area/'preflight'
model,revision={'qwen':('Qwen/Qwen3-Embedding-0.6B','97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'),'bge':('BAAI/bge-m3','5617a9f61b028005a4858fdac845db406aefb181')}[args.model]
snapshot=area/'sources'/model.replace('/','--')/revision;registration=json.loads((snapshot/'VERIFIED-DATA.json').read_text())
original=root/'.ken/rust-migration/m0-m1/reference/src/ken/embedder/st_backend.py';assert Path(module.__file__).resolve()==original.resolve();source_sha=hashlib.sha256(original.read_bytes()).hexdigest()
torch.set_num_threads(2);torch.set_num_interop_threads(1)
lexical=['','   ','save_config(value)','¿Dónde se guarda configuración?','e\u0301 é 🦀','a','a b c d e f','repeat repeat repeat']
ties=['a'*8,'b'*8,'é'*8,'e\u0301'*4,'中'*8,'😀'*8,'_'*8,'é中'*4,'_a'*4,'AB'*4,'12'*4,'🦀'*8,'ÿ'*8,'ñ'*8,'あ'*8,'Ω'*8,'λ'*8]
requests=[{'id':'lexical','side':'passages','texts':lexical},{'id':'specials','side':'passages','texts':['<|endoftext|>','<s>','</s>','<pad>','[UNK]','é','e\u0301','__init__']},{'id':'repeated','side':'passages','texts':['same text']*3},{'id':'batch16','side':'passages','texts':(lexical*2)},{'id':'batch17','side':'passages','texts':(lexical*2+['tail source'])},{'id':'ties17','side':'passages','texts':ties},{'id':'ties33','side':'passages','texts':ties+ties[:16]},*[{'id':f'content_tokens_{n}','side':'passages','texts':['a '*(n-1)+'a']} for n in [511,512,513]],{'id':'unicode_truncation','side':'passages','texts':['猫 '*520]},{'id':'query_prompt','side':'query','texts':['where does save_config persist data?']}]
settings={'model_id':model,'revision':revision,'dtype':args.dtype,'device_request':args.device,'sequence_length':512,'batch_size':16}
encoder=SentenceTransformerEmbedder(model,device=args.device,revision=revision,model_path=str(snapshot),local_files_only=True,trust_remote_code=False,dtype=args.dtype,sequence_length=512,batch_size=16)
assert encoder.embed_passages([])==[] and encoder._model is None
counts={request['id']:[encoder.token_count(text) for text in request['texts']] for request in requests};long_count=encoder.token_count('a '*700);assert long_count>512 and encoder._model is None
feeds=[];active_case=None;original_build=encoder._build

def build(device):
 model_instance=original_build(device)
 actual=model_instance[0].auto_model;weak_forward=weakref.WeakMethod(actual.forward);signature=inspect.signature(actual.forward)
 def capture(*positional,**kwargs):
  forward=weak_forward()
  if forward is None:raise RuntimeError('original transformer disappeared during an owned request')
  receiver=forward.__self__
  feed={key:value.detach().cpu().tolist() for key,value in kwargs.items() if key in ('input_ids','attention_mask','token_type_ids')}
  feeds.append({'case':active_case,'actual_device':str(receiver.device),'weight_dtype':str(receiver.dtype),'shape':list(kwargs['input_ids'].shape),'inputs':feed,'attention_implementation':receiver.config._attn_implementation})
  return forward(*positional,**kwargs)
 capture.__signature__=signature
 actual.forward=capture
 return model_instance
encoder._build=build
start=time.monotonic();dimension=encoder.dim;preparation=time.monotonic()-start;assert encoder._model is not None
results=[]
for request in requests:
 active_case=request['id'];feed_start=len(feeds);start=time.monotonic()
 try:
  vectors=np.asarray(encoder.embed_query(request['texts'][0]) if request['side']=='query' else encoder.embed_passages(request['texts']),dtype=np.float32)
  if vectors.ndim==1:vectors=vectors.reshape(1,-1)
  record={'id':request['id'],'passed_original_call':True,'shape':list(vectors.shape),'vectors_f32le_hex':vectors.astype('<f4',copy=False).tobytes().hex(),'finite':bool(np.isfinite(vectors).all()),'device_after':encoder.device}
 except Exception as failure:record={'id':request['id'],'passed_original_call':False,'error':type(failure).__name__+': '+str(failure),'device_after':encoder.device}
 record.update({'elapsed_s':time.monotonic()-start,'feed_range':[feed_start,len(feeds)]});results.append(record)
 print(json.dumps({'settings':settings,'case':request['id'],'original_success':record['passed_original_call'],'device':encoder.device,'elapsed_s':record['elapsed_s']}),flush=True)
assert all(not r['passed_original_call'] or r['feed_range'][1]>r['feed_range'][0] for r in results), 'successful original call without observed feeds'
assert hashlib.sha256(original.read_bytes()).hexdigest()==source_sha
receipt={'format':'ken-st-full-original-exploration/1','settings':settings,'original_source_sha256':source_sha,'model_registration':registration,'dimension':dimension,'empty_batch_did_not_load':True,'count_did_not_load_model':True,'long_count':long_count,'counts':counts,'requests':requests,'results':results,'feeds':feeds,'preparation_s':preparation,'package_versions':{key:__import__('importlib.metadata',fromlist=['version']).version(key) for key in ['torch','sentence-transformers','transformers','tokenizers','numpy']},'peak_rss_process_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'model_inference_accepted':False}
out=pre/'st-original-full';out.mkdir(exist_ok=True);(out/f'{args.model}-{args.device}-{args.dtype}.json').write_text(json.dumps(receipt,ensure_ascii=True)+'\n')
print(json.dumps({'captured':True,'cases':len(results),'feeds':len(feeds),'model_inference_accepted':False}),flush=True)

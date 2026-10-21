from pathlib import Path
import hashlib
import inspect
import json
import torch
import transformers
from transformers import Qwen3Config, Qwen3Model
from safetensors.torch import save_file

torch.set_num_threads(2)
torch.set_num_interop_threads(1)
out=Path(__file__).resolve().parent
config=Qwen3Config(vocab_size=8,hidden_size=4,intermediate_size=6,num_hidden_layers=2,
 num_attention_heads=2,num_key_value_heads=1,head_dim=4,max_position_embeddings=16,
 rms_norm_eps=1e-6,rope_theta=10000.0,attention_bias=False,tie_word_embeddings=True,
 attention_dropout=0.0,hidden_act='silu',pad_token_id=0)
config._attn_implementation='sdpa'
model=Qwen3Model(config).eval()
with torch.no_grad():
 for index,(name,param) in enumerate(model.named_parameters()):
  values=(torch.arange(param.numel(),dtype=torch.float32).reshape(param.shape)%17-8)*0.03125+(index+1)*0.00390625
  if 'norm' in name: values=values+0.5
  param.copy_(values)
state={name:tensor.detach().clone().contiguous() for name,tensor in model.state_dict().items()}
save_file(state,str(out/'model.safetensors'))
save_file({'model.'+name:tensor for name,tensor in state.items()},str(out/'prefixed.safetensors'))
config.to_json_file(out/'config.json')
cases=[]
for device in ('cpu','mps'):
 assert device!='mps' or torch.backends.mps.is_available()
 for dtype in ('float32','float16','bfloat16'):
  # Rebuild on CPU to preserve original RoPE initialization before movement.
  actual=Qwen3Model(config).eval();actual.load_state_dict(state)
  actual=actual.to(device=device,dtype=getattr(torch,dtype))
  for name,ids,mask in [('padding',[[1,3,5,0],[2,4,0,0]],[[1,1,1,0],[1,1,0,0]]),('all_ones',[[2,6,1],[0,3,4]],[[1,1,1],[1,1,1]])]:
   with torch.no_grad():
    values=actual(input_ids=torch.tensor(ids,device=device),attention_mask=torch.tensor(mask,device=device),use_cache=False).last_hidden_state
   pooled=values[torch.arange(len(ids),device=device),torch.tensor(mask,device=device).sum(1)-1]
   for _ in range(2):pooled=torch.nn.functional.normalize(pooled,p=2,dim=1)
   pooled=torch.nn.functional.normalize(pooled.float(),p=2,dim=1)
   states=values[torch.arange(len(ids),device=device),torch.tensor(mask,device=device).sum(1)-1].float()
   weight=actual.get_input_embeddings().weight
   scores=states @ (weight[1].float()-weight[6].float())
   cases.append({'tied_scores':scores.cpu().tolist(),'sentence_vectors':pooled.cpu().reshape(-1).tolist(),'name':name,'device':device,'dtype':dtype,'input_ids':ids,'attention_mask':mask,'shape':list(values.shape),'values':values.float().cpu().reshape(-1).tolist()})
  del actual
source=Path(inspect.getfile(Qwen3Model))
(out/'original.json').write_text(json.dumps({'format':'ken-qwen3-tiny-original/1','torch':torch.__version__,'transformers':transformers.__version__,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'cases':cases},indent=2)+'\n')
print(json.dumps({'original_cases':len(cases),'parameters':len(state),'actual_mps':True}))

"""Published Ettin head assembly and fixed CPU-only scoring; no Torch import."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy.special import erf
from tokenizers import Tokenizer


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def cpu_options():
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    return options


def validate_head(w,hidden):
    expected={'dense':(hidden,hidden),'norm_weight':(hidden,),'norm_bias':(hidden,),
              'out':(1,hidden),'out_bias':(1,)}
    if set(w)!=set(expected) or any(w[k].shape!=shape or not np.isfinite(w[k]).all()
                                  for k,shape in expected.items()):
        raise ValueError('unsupported/nonfinite published head')


def numpy_head(cls,w):
    h=cls@w['dense'].T
    h=h*np.float32(.5)*(1+erf(h/np.float32(math.sqrt(2))))
    h=(h-h.mean(-1,keepdims=True))/np.sqrt(h.var(-1,keepdims=True)+np.float32(1e-5))
    return (h*w['norm_weight']+w['norm_bias'])@w['out'].T+w['out_bias']


def load_head(root):
    from safetensors.numpy import load_file
    pool=json.loads((root/'1_Pooling/config.json').read_text())
    dense=json.loads((root/'2_Dense/config.json').read_text())
    norm=json.loads((root/'3_LayerNorm/config.json').read_text())
    out=json.loads((root/'4_Dense/config.json').read_text())
    hidden=pool['embedding_dimension']
    if (pool['pooling_mode']!='cls' or dense['in_features']!=hidden
        or dense['out_features']!=hidden or dense['bias']
        or dense['activation_function']!='torch.nn.modules.activation.GELU'
        or norm['dimension']!=hidden or out['in_features']!=hidden
        or out['out_features']!=1 or not out['bias']
        or out['activation_function']!='torch.nn.modules.linear.Identity'):
        raise ValueError('published module architecture differs')
    d=load_file(root/'2_Dense/model.safetensors')
    n=load_file(root/'3_LayerNorm/model.safetensors')
    o=load_file(root/'4_Dense/model.safetensors')
    w={'dense':d['linear.weight'],'norm_weight':n['norm.weight'],
       'norm_bias':n['norm.bias'],'out':o['linear.weight'],'out_bias':o['linear.bias']}
    validate_head(w,hidden)
    return w,hidden


def assemble(upstream,output):
    import onnx
    from onnx import helper as h,numpy_helper as nh,TensorProto as T
    root=Path(upstream['root']);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    for name,record in upstream['artifacts'].items():
        expected=record['sha256'] if isinstance(record,dict) else record
        if sha(root/name)!=expected: raise ValueError('upstream artifact changed: '+name)
    w,hidden=load_head(root)
    model=onnx.load(root/'onnx/model_qint8_arm64.onnx')
    if len(model.graph.output)!=1 or model.opset_import[0].version!=18:
        raise ValueError('unexpected upstream ONNX output/opset')
    token_output=model.graph.output[0].name;prefix='ken_published_head/'
    def const(name,value):
        name=prefix+name;model.graph.initializer.append(nh.from_array(np.asarray(value),name));return name
    def node(op,inputs,name,**attrs):
        output_name=prefix+name
        model.graph.node.append(h.make_node(op,inputs,[output_name],name=output_name,**attrs));return output_name
    cls=node('Gather',[token_output,const('cls_index',np.array(0,np.int64))],'cls',axis=1)
    dense=node('MatMul',[cls,const('dense_weight',w['dense'].T)],'dense')
    scaled=node('Div',[dense,const('sqrt2',np.array(math.sqrt(2),np.float32))],'scaled')
    gauss=node('Erf',[scaled],'erf')
    added=node('Add',[gauss,const('one',np.array(1,np.float32))],'plus_one')
    product=node('Mul',[dense,added],'gelu_product')
    gelu=node('Mul',[product,const('half',np.array(.5,np.float32))],'gelu')
    norm=node('LayerNormalization',[gelu,const('norm_weight',w['norm_weight']),
        const('norm_bias',w['norm_bias'])],'norm',axis=-1,epsilon=1e-5)
    scores=node('MatMul',[norm,const('out_weight',w['out'].T)],'scores')
    logits=node('Add',[scores,const('out_bias',w['out_bias'])],'logits')
    del model.graph.output[:]
    model.graph.output.append(h.make_tensor_value_info(logits,T.FLOAT,['batch_size',1]))
    onnx.checker.check_model(model)
    graph=output/'model-reranker-int8.onnx';onnx.save(model,graph);del model
    # Reference compares the same published INT8 encoder + independent NumPy head.
    # These are synthetic, source/label-free strings, never benchmark requests.
    tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'))
    tokenizer.enable_padding();tokenizer.enable_truncation(max_length=512,strategy='only_second')
    encoded=tokenizer.encode_batch([('find a value','class Cache: store values by key'),
        ('parse input','function read(data) { return data; }'),
        ('validate fields','Checks attributes. '+'if value is None: return False\n'*80)])
    feeds={'input_ids':np.array([e.ids for e in encoded],np.int64),
           'attention_mask':np.array([e.attention_mask for e in encoded],np.int64)}
    encoder=ort.InferenceSession(str(root/'onnx/model_qint8_arm64.onnx'),
        sess_options=cpu_options(),providers=['CPUExecutionProvider'])
    tokens=encoder.run([token_output],feeds)[0];expected=numpy_head(tokens[:,0,:],w);del encoder
    merged=ort.InferenceSession(str(graph),sess_options=cpu_options(),providers=['CPUExecutionProvider'])
    actual=merged.run([logits],feeds)[0]
    delta=float(np.max(np.abs(expected-actual)))
    if not np.allclose(expected,actual,rtol=1e-5,atol=2e-5): raise ValueError('head parity failure')
    record={'upstream':upstream,'graph':str(graph.resolve()),'graph_sha256':sha(graph),
        'graph_bytes':graph.stat().st_size,'tokenizer':str((root/'tokenizer.json').resolve()),
        'tokenizer_sha256':sha(root/'tokenizer.json'),'output_name':logits,
        'hidden':hidden,'head':'CLS/Dense/exactGELU/LayerNorm(eps1e-5)/Dense/raw_logits',
        'max_abs_delta_numpy_head':delta,'probe_tokens':[len(e.ids) for e in encoded],
        'scope':'head parity only, not FP32-backbone parity or retrieval quality',
        'script_sha256':sha(__file__),'provider':merged.get_providers(),
        'heavy_imports':[m for m in ('torch','transformers','sentence_transformers') if m in sys.modules]}
    if record['provider']!=['CPUExecutionProvider'] or record['heavy_imports']:
        raise ValueError('CPU/no-heavy-runtime policy failed')
    (output/'assembly.json').write_text(json.dumps(record,indent=2))
    return record


class CPUReranker:
    def __init__(self,registration):
        self.registration=registration
        for path,expected in ((registration['graph'],registration['graph_sha256']),
                              (registration['tokenizer'],registration['tokenizer_sha256'])):
            if sha(path)!=expected: raise ValueError('model runtime asset changed')
        self.session=ort.InferenceSession(registration['graph'],sess_options=cpu_options(),
                                         providers=['CPUExecutionProvider'])
        if self.session.get_providers()!=['CPUExecutionProvider']: raise ValueError('CPU required')
        self.output=self.session.get_outputs()[0].name
        self.tokenizer=Tokenizer.from_file(registration['tokenizer'])
        self.tokenizer.enable_truncation(max_length=512,strategy='only_second')
        self.tokenizer.enable_padding()

    def score(self,query,texts):
        scores=[];truncated=0;token_ms=0;inference_ms=0;tokens=[]
        for start in range(0,len(texts),4):
            before=time.perf_counter()
            encoded=self.tokenizer.encode_batch([(query,x) for x in texts[start:start+4]])
            truncated+=sum(bool(e.overflowing) for e in encoded)
            tokens.extend(sum(e.attention_mask) for e in encoded)
            feeds={'input_ids':np.array([e.ids for e in encoded],np.int64),
                   'attention_mask':np.array([e.attention_mask for e in encoded],np.int64)}
            token_ms+=(time.perf_counter()-before)*1000;before=time.perf_counter()
            result=self.session.run([self.output],feeds)[0].reshape(-1)
            inference_ms+=(time.perf_counter()-before)*1000
            if not np.isfinite(result).all():raise ValueError('nonfinite reranker score')
            scores.extend(float(x) for x in result)
        return scores,{'token_ms':token_ms,'inference_ms':inference_ms,
                       'truncated_documents':truncated,'pair_tokens':tokens}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--registrations',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    registrations=json.loads(args.registrations.read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    for r in registrations:
        size=r['model_id'].split('ettin-reranker-')[1].split('-')[0]
        result=assemble(r,args.output/size)
        print(json.dumps({'model':r['model_id'],'bytes':result['graph_bytes'],
                          'head_parity_delta':result['max_abs_delta_numpy_head']}),flush=True)

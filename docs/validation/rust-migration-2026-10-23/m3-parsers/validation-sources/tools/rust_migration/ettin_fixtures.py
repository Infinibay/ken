"""Independent tiny head/pair data from explicit frozen-original test helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference,reference_env,verify_reference

_CHILD=r'''
import dataclasses,hashlib,json,math,runpy,shutil,sys
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
from safetensors.numpy import save_file
from ken.retrieval.neural_assets import append_published_head,prepare_reranker
from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
reference,root=map(Path,sys.argv[1:]);root.mkdir(parents=True)
import ken.retrieval.neural_assets as original
if not Path(original.__file__).resolve().is_relative_to(reference/'src'):raise ValueError('fixture import escaped frozen tree')
head_helper=reference/'tests/retrieval/test_reranker_head.py'
pair_helper=reference/'tests/retrieval/test_neural_reranker.py'
head_ns=runpy.run_path(str(head_helper));pair_ns=runpy.run_path(str(pair_helper))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def artifact(p):return {'bytes':p.stat().st_size,'sha256':sha(p)}
def definition(source,graph):
 return {'source':{'model_id':'test/reranker','revision':source.name,'artifacts':{
  p.relative_to(source).as_posix():artifact(p) for p in sorted(source.rglob('*')) if p.is_file()}},
  'graph':{'path':'model.onnx',**artifact(graph)}}
def prepared_pair(source,destination):
 destination.mkdir(parents=True)
 for old,new in [('graph.onnx','model.onnx'),('tokenizer.json','tokenizer.json'),('config.json','config.json'),('tokenizer_config.json','tokenizer_config.json')]:shutil.copyfile(source/old,destination/new)
 return definition(source,destination/'model.onnx')
def runtime(source,prepared):
 return ONNXReranker(lambda:RerankerAssets(prepared/'model.onnx',sha(prepared/'model.onnx'),
 prepared/'tokenizer.json',sha(prepared/'tokenizer.json'),prepared/'config.json',sha(prepared/'config.json'),
 prepared/'tokenizer_config.json',sha(prepared/'tokenizer_config.json')))
base=root/'head';base.mkdir()
head=head_ns['published_head'].__wrapped__(base)
head,head_definition=head_ns['registered_head'].__wrapped__(head,base)
ready=base/'prepared'/head.name
assets=prepare_reranker(head_definition,ready,source_snapshot=head)
options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
session=ort.InferenceSession(str(assets.graph),sess_options=options,providers=['CPUExecutionProvider'])
score=float(session.run(None,{'input_ids':np.array([[1]],np.int64),'attention_mask':np.array([[1]],np.int64)})[0][0,0])
values=[x*.5*(1+math.erf(x/math.sqrt(2))) for x in (2.,1.,-1.)]
mean=sum(values)/3;variance=sum((x-mean)**2 for x in values)/3
expected=sum((x-mean)/math.sqrt(variance+1e-5)*w for x,w in zip(values,(1.,-2.,.5),strict=True))+.25
pair=root/'pair'/('b'*40);pair.mkdir(parents=True)
pair_ns['registered_reranker'].__wrapped__(pair)
# Original helper fixes batch1. An explicit data adaptation makes batch dimension
# symbolic, so the same original scorer can exercise batch3 and right padding.
model=onnx.load(pair/'graph.onnx')
for value in [*model.graph.input,*model.graph.output]:
 value.type.tensor_type.shape.dim[0].ClearField('dim_value');value.type.tensor_type.shape.dim[0].dim_param='batch'
onnx.save(model,pair/'graph.onnx')
pair_ready=root/'pair/prepared'/pair.name
pair_definition=prepared_pair(pair,pair_ready)
invalid={}
for name in ['activation','nonfinite-head','wrong-head-shape','malformed-backbone','wrong-opset','extra-backbone-output']:
 directory=root/'invalid'/name;source=directory/head.name;shutil.copytree(head,source)
 if name=='activation':
  p=source/'2_Dense/config.json';d=json.loads(p.read_text());d['activation_function']='unsupported';p.write_text(json.dumps(d))
 elif name=='nonfinite-head':save_file({'linear.weight':np.full((3,3),np.nan,np.float32)},source/'2_Dense/model.safetensors')
 elif name=='wrong-head-shape':save_file({'linear.weight':np.ones((2,3),np.float32)},source/'2_Dense/model.safetensors')
 elif name=='malformed-backbone':(source/'onnx/model.onnx').write_bytes(b'not protobuf')
 else:
  m=onnx.load(source/'onnx/model.onnx')
  if name=='wrong-opset':m.opset_import[0].version=17
  else:m.graph.output.append(m.graph.output[0])
  onnx.save(m,source/'onnx/model.onnx')
 try:append_published_head(source,directory/'output.onnx');error=None
 except Exception as e:error=f'{type(e).__name__}: {e}'
 invalid[name]={'kind':'head','source':str(source),'definition':definition(source,assets.graph),'original_rejected':error is not None,'error':error}
for name in ['bad-pad-id','left-padding','model-limit','two-scores','nan-output','inf-output']:
 directory=root/'invalid'/name;source=directory/pair.name;shutil.copytree(pair,source)
 if name in ['bad-pad-id','model-limit']:
  p=source/'config.json';d=json.loads(p.read_text());d['pad_token_id' if name=='bad-pad-id' else 'max_position_embeddings']=0 if name=='bad-pad-id' else 16;p.write_text(json.dumps(d))
 elif name=='left-padding':
  p=source/'tokenizer_config.json';d=json.loads(p.read_text());d['padding_side']='left';p.write_text(json.dumps(d))
 else:
  m=onnx.load(source/'graph.onnx')
  if name=='two-scores':m.graph.node.append(onnx.helper.make_node('Concat',['scores','scores'],['invalid'],axis=1));width=2
  else:
   value=np.nan if name=='nan-output' else np.inf
   m.graph.initializer.append(onnx.numpy_helper.from_array(np.array(value,np.float32),'invalid_value'))
   m.graph.node.append(onnx.helper.make_node('Add',['scores','invalid_value'],['invalid']));width=1
  del m.graph.output[:];m.graph.output.append(onnx.helper.make_tensor_value_info('invalid',onnx.TensorProto.FLOAT,['batch',width]))
  onnx.save(m,source/'graph.onnx')
 ready_bad=directory/'prepared'/pair.name;d=prepared_pair(source,ready_bad)
 try:runtime(source,ready_bad).score('x',['y']);error=None
 except Exception as e:error=f'{type(e).__name__}: {e}'
 invalid[name]={'kind':'pair','source':str(source),'prepared':str(ready_bad),'definition':d,'original_rejected':error is not None,'error':error}
double=root/'non-f32'/pair.name;shutil.copytree(pair,double)
m=onnx.load(double/'graph.onnx')
m.graph.node.append(onnx.helper.make_node('Cast',['scores'],['double_scores'],to=onnx.TensorProto.DOUBLE))
del m.graph.output[:];m.graph.output.append(onnx.helper.make_tensor_value_info('double_scores',onnx.TensorProto.DOUBLE,['batch',1]))
onnx.save(m,double/'graph.onnx')
double_ready=root/'non-f32/prepared'/pair.name
double_definition=prepared_pair(double,double_ready)
double_scores,_=runtime(double,double_ready).score('x',['y'])
result={'original_helpers_verified':True,'helpers':{str(p.relative_to(reference)):sha(p) for p in [head_helper,pair_helper]},
 'head':{'source':str(head),'prepared':str(ready),'definition':head_definition,'expected_graph':artifact(assets.graph),
 'original_preparation_verified':True,'original_scalar_score':score,'independent_scalar_score':expected},
 'pair':{'source':str(pair),'prepared':str(pair_ready),'definition':pair_definition},'invalid':invalid,
 'non_f32':{'source':str(double),'prepared':str(double_ready),'definition':double_definition,'original_scores':double_scores}}
def relative(value):
 if isinstance(value,dict):return {k:relative(v) for k,v in value.items()}
 if isinstance(value,list):return [relative(v) for v in value]
 if isinstance(value,str) and value.startswith(str(root)+'/'):return value[len(str(root))+1:]
 return value
(root/'manifest.json').write_text(json.dumps(relative(result),indent=2,allow_nan=False)+'\n')
print(json.dumps(result,allow_nan=False))
'''


def generate(reference:Reference,output:Path)->dict:
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    output=output.resolve()
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-ettin-fixture-env-') as directory:
        env=reference_env(reference,Path(directory))
        child=subprocess.run([str(reference.python),'-c',_CHILD,str(reference.root),str(output)],
            cwd=output.parent,env=env,text=True,capture_output=True,timeout=120)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode:raise ValueError(f'frozen Ettin fixture generation failed: {child.stderr}')
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    return json.loads(child.stdout)

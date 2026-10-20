"""Regenerate tiny graphs; fixtures execute in Rust without Python children."""
from pathlib import Path
import hashlib,json,onnx
from onnx import helper as h,TensorProto as T
root=Path(__file__).parent
for mode in ['hidden','clip','task','wrong_type','extra_rows','nonfinite','unknown_input','wrong_input_type','invalid_operator']:
 inputs=[h.make_tensor_value_info('input_ids',T.FLOAT if mode=='wrong_input_type'else T.INT64,['batch','sequence'])]
 if mode not in ['clip','invalid_operator']:inputs.append(h.make_tensor_value_info('attention_mask',T.INT64,['batch','sequence']))
 if mode=='task':inputs.extend([h.make_tensor_value_info('token_type_ids',T.INT64,['batch','sequence']),h.make_tensor_value_info('task_id',T.INT64,[])])
 if mode=='unknown_input':inputs.append(h.make_tensor_value_info('mystery',T.INT64,[]))
 if mode in ['hidden','task','wrong_type','wrong_input_type','unknown_input']:
  nodes=[h.make_node('Cast',['input_ids'],['cast'],to=T.INT64 if mode=='wrong_type'else T.FLOAT),h.make_node('Unsqueeze',['cast','axis'],['column']),h.make_node('Concat',['column','column'],['output'],axis=2)]
  initial=[h.make_tensor('axis',T.INT64,[1],[2])];shape=['batch','sequence',2];dtype=T.INT64 if mode=='wrong_type'else T.FLOAT;name='fastembed-'+mode
 elif mode=='invalid_operator':
  nodes=[h.make_node('NoSuchKenOperator',['input_ids'],['output'])];initial=[];shape=['batch',2];dtype=T.FLOAT;name='invalid-op'
 else:
  values=[3.,4.]if mode=='clip'else[float('nan'),1.]if mode=='nonfinite'else[1.,2.,3.,4.];count=len(values)//2
  initial=[h.make_tensor('constant',T.FLOAT,[count,2],values)];nodes=[h.make_node('Identity',['constant'],['output'])];shape=[count,2];dtype=T.FLOAT;name='fastembed-'+mode
 graph=h.make_graph(nodes,name,inputs,[h.make_tensor_value_info('output',dtype,shape)],initial);model=h.make_model(graph,opset_imports=[h.make_opsetid('',17)],ir_version=10)
 if mode!='invalid_operator':onnx.checker.check_model(model)
 data=model.SerializeToString();path=root/(mode+'.onnx')
 if path.exists():assert path.read_bytes()==data,path
 else:path.write_bytes(data)
(root/'manifest.json').write_text(json.dumps({'generator_onnx_version':onnx.__version__,'files':{path.name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}for path in sorted(root.glob('*.onnx'))}},indent=2)+'\n')

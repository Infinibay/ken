"""Independent original-adapter and raw Python ORT observations of fixed inputs."""
from pathlib import Path
import hashlib
SOURCE='src/ken/embedder/contextual_onnx.py'
SOURCE_SHA='de3c201a2efec99ea81cb9c68db28d77dcd41c168c6f320c146d660c4752904b'

def observe(request:dict,repo:Path,mode:str,threads:int)->dict:
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    import ken.embedder.contextual_onnx as implementation
    from ken.model_assets import ModelAssets
    source=Path(implementation.__file__).resolve()
    if source!=repo.resolve()/SOURCE or hashlib.sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('original context source differs')
    definition=request['registration'];snapshot=Path(request['snapshot']);rows=[]
    tokenizer=Tokenizer.from_file(str(snapshot/'tokenizer.json'));tokenizer.no_padding();tokenizer.enable_truncation(max_length=512)
    if mode=='adapter':
        model=implementation.ContextModel(ModelAssets.from_dict(definition),definition['query_prefix'],definition['document_projection'])
    elif mode in('file','memory'):
        options=ort.SessionOptions();options.intra_op_num_threads=threads;options.inter_op_num_threads=1
        graph=snapshot/'onnx/model.onnx'
        session=ort.InferenceSession(str(graph)if mode=='file'else graph.read_bytes(),sess_options=options,providers=['CPUExecutionProvider'])
    else:raise ValueError('unknown Python context observation mode')
    for case in request['cases']:
        token=case['calls'][0];text=token['text'];encoded=tokenizer.encode((definition['query_prefix']if token['kind']=='query'else'')+text)
        tokens=dict(ids=encoded.ids,attention_mask=encoded.attention_mask)
        if mode=='adapter':
            encoder=implementation.ContextEncoder(model,snapshot=snapshot)
            vector=(encoder.embed_query(text)if token['kind']=='query'else encoder.embed_passages([text])[0]).tolist()
            repeats=[vector]
        else:
            inputs={('input_ids'if key=='ids'else key):np.array([value],dtype=np.int64)for key,value in tokens.items()}
            repeats=[session.run(['sentence_embedding'],inputs)[0][0].tolist()for _ in range(2)]
        rows.append(dict(id=case['id'],tokens=tokens,vectors=repeats))
    return dict(mode=mode,threads=threads,source=SOURCE,source_sha256=SOURCE_SHA,ort=ort.__version__,ort_build=ort.get_build_info(),cases=rows)

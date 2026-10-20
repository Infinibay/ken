from pathlib import Path
import hashlib,json
from ken.embedder.onnx_fastembed import OnnxEmbedder
import ken.embedder as source
from fastembed import TextEmbedding
from fastembed.common.preprocessor_utils import load_tokenizer
root=Path.cwd();owned=root/'.ken/rust-migration/m2-fastembed';registry=json.loads((owned/'registry-draft.json').read_bytes())
records=[]
for canonical in ['intfloat/multilingual-e5-large']:
    definition=next(m for m in registry['models'] if m['name']==canonical);assets=definition['assets']
    snapshot=owned/'sources'/assets['model_id'].replace('/','--')/assets['revision'];tokenizer,_=load_tokenizer(snapshot)
    for requested in [canonical,canonical.upper()]:
        encoder=OnnxEmbedder(requested,device='cpu')
        matches=[m.model for m in TextEmbedding._list_supported_models() if m.model.lower()==requested.lower()]
        assert matches==[canonical] and encoder.model_name==requested
        records.append({'requested':requested,'canonical_route':matches[0],'query_prompt':encoder._q_prompt,'passage_prompt':encoder._p_prompt,'query_ids':tokenizer.encode(encoder._q_prompt+'a').ids,'passage_ids':tokenizer.encode(encoder._p_prompt+'a').ids})
assert records[0]['query_prompt']=='query: ' and records[1]['query_prompt']==''
assert records[0]['query_ids']!=records[1]['query_ids']
result={'scope':'actual frozen original prompt/tokenizer-only alias observation, no neural/native parity claim','source':str(source.__file__),'source_sha256':hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest(),'records':records}
(owned/'case-alias-original-preflight.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

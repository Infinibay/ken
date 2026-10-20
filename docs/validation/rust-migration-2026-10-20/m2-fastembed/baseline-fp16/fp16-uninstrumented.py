from pathlib import Path
import argparse,hashlib,json,sys,traceback
parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,required=True);args=parser.parse_args()
from ken.embedder.onnx_fastembed import OnnxEmbedder
import ken.embedder.onnx_fastembed as original
encoder=OnnxEmbedder('jinaai/jina-embeddings-v2-base-de',device='cpu')
empty=encoder.embed_passages([])
assert encoder._model is None and not any(n in sys.modules for n in ['onnxruntime','fastembed'])
import fastembed
real=fastembed.TextEmbedding
def local(*a,**kw):return real(*a,**kw,specific_model_path=str(args.snapshot),local_files_only=True)
fastembed.TextEmbedding=local
records=[]
for attempt in range(2):
    try:
        vectors=encoder.embed_passages(['a']);records.append({'attempt':attempt,'success':True,'shape':[len(vectors),len(vectors[0])]})
    except Exception as error:
        records.append({'attempt':attempt,'success':False,'exception':type(error).__module__+'.'+type(error).__name__,'message':str(error),'traceback':traceback.format_exc(),'loaded':encoder._model is not None,'device':encoder.device})
print(json.dumps({'scope':'actual original uninstrumented session: path-only offline adapter, no thread/optimizer/inference overrides','source':str(original.__file__),'source_sha256':hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),'records':records},indent=2))

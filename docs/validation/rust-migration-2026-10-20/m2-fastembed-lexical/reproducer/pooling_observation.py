"""Observe the original functions on the exact F32 boundary fixture."""
import hashlib,inspect,json
from pathlib import Path
import numpy as np
from fastembed.common.utils import mean_pooling,normalize
bits=[1074976142,1059643487,1059287095,3200899132,3202574503,3221800815,3219705437,1068471701,3188325342,3206356528,1064556899,3210317925]
x=np.array(bits,dtype=np.uint32).view(np.float32).reshape(1,3,4)
mask=np.ones((1,3),dtype=np.int64);mean=mean_pooling(x,mask)
print(json.dumps({'input_f32_bits':bits,'shape':[1,3,4],'mask':mask.tolist(),'mean_dtype':str(mean.dtype),'late_f32_bits':normalize(mean).astype(np.float32).view(np.uint32).ravel().tolist(),'premature_f32_bits':normalize(mean.astype(np.float32)).view(np.uint32).ravel().tolist(),'original_functions':{fn.__name__:{'source':inspect.getsource(fn),'file_sha256':hashlib.sha256(Path(inspect.getfile(fn)).read_bytes()).hexdigest()}for fn in (mean_pooling,normalize)}},indent=2))

"""Observe the original alignment API and its actual process-local BLAS kernel."""
from pathlib import Path
import ctypes,dataclasses,hashlib

SOURCE='src/ken/retrieval/alignment.py'
SOURCE_SHA='4fd861b5f2d9fa792fe47ab9900af926acb697245e702687df26ab63a1aaa99b'

def observe(case:dict,repo:Path)->dict:
    import numpy as np
    from ken.retrieval.alignment import TermAlignment
    import ken.retrieval.alignment as implementation
    source=Path(implementation.__file__).resolve()
    if source!=repo.resolve()/SOURCE:raise ValueError('original alignment import escaped source')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    # Pin filled from the immutable1066-file original, not this experiment's result.
    if digest!=SOURCE_SHA:raise ValueError('original alignment source differs')
    data=case['input']
    def matrix(value):return np.array(value['values'],dtype=value['dtype']).reshape(value['rows'],value['columns'])
    query=matrix(data['query']);documents=matrix(data['documents']);weights=np.array(data['weights']['values'],dtype=data['weights']['dtype'])
    alignment=TermAlignment(query,weights);similarities=alignment.similarities(documents)
    library=next((Path(np.__file__).parent.parent/'numpy.libs').glob('libscipy_openblas64_*.so'))
    native=ctypes.CDLL(str(library));core=native.scipy_openblas_get_corename64_;core.restype=ctypes.c_char_p
    config=native.scipy_openblas_get_config64_;config.restype=ctypes.c_char_p
    return dict(source=SOURCE,source_sha256=digest,numpy=np.__version__,blas=dict(core=core().decode(),config=config().decode(),sha256=hashlib.sha256(library.read_bytes()).hexdigest()),similarities=similarities.tolist(),maxima=similarities.max(axis=1).tolist(),coverage=dataclasses.asdict(alignment.coverage(documents)))

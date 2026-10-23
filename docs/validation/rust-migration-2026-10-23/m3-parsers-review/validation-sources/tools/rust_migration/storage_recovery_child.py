"""Frozen-original fixture preparation/readback; never imported by a native child."""
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import numpy as np
from ken import db,vectors
import ken.embedder as emb
import ken._paths as paths

def main():
    request=json.load(sys.stdin);reference=Path(request['reference']).resolve();root=Path(request['root'])
    modules={'src/ken/db.py':db,'src/ken/vectors.py':vectors,'src/ken/embedder/__init__.py':emb,'src/ken/_paths.py':paths}
    sources={}
    for name in request['owners']:
        actual=Path(db.__file__).with_name('schema.sql').resolve() if name.endswith('.sql') else Path(modules[name].__file__).resolve()
        if actual!=reference/name:raise ValueError('original recovery import escaped frozen reference')
        sources[name]=hashlib.sha256(actual.read_bytes()).hexdigest()
    internal=root/'.ken'
    if request['action']=='seed':internal.mkdir(parents=True,exist_ok=True)
    conn=db.connect(internal/'ken.db')
    if request['action']=='seed':
        db.init_schema(conn)
        if request['operation']=='compact':
            conn.executescript("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(1,'a',x'',0,0,4),(2,'b',x'',0,0,1); INSERT INTO ci_symbols(id,file_id,kind,name,line_start,line_end,vec_slot) VALUES(1,1,'function','a',1,1,4),(2,2,'function','b',1,1,1); INSERT INTO ci_intent_sources(id,source_kind,text,updated_at,vec_slot) VALUES(1,'module_docstring','a',0,4),(2,'module_docstring','b',0,1);")
            for space in vectors.SPACES:
                conn.execute('INSERT INTO ci_vec_alloc VALUES(?,5)',(space,))
                with vectors.VectorStore(root,space,dim=2) as store:store.write([4,1],np.array([[1,0],[0,1]],dtype=np.float32),durable=True)
        elif request['operation']=='inline':
            for identity,values in [(1,[0,1,0]),(2,[1,0]),(3,[0,1])]:
                conn.execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,embedding) VALUES(?,?,x'',0,0,?)",(identity,str(identity)+'.py',np.array(values,dtype='<f4').tobytes()))
        else:raise ValueError('unknown original recovery fixture')
    elif request['action']!='read':raise ValueError('unknown original recovery action')
    spaces={};high_water={};free={}
    for space in vectors.SPACES:
        rows=conn.execute(f'SELECT id,vec_slot,embedding FROM {space} ORDER BY id').fetchall();observed=[]
        slots=[int(row['vec_slot']) for row in rows if row['vec_slot'] is not None]
        values={}
        if slots:
            with vectors.VectorStore(root,space,dim=2) as store:
                values={slot:vec.tolist() for slot,vec in zip(slots,store.read(slots),strict=True)}
        for row in rows:
            slot=row['vec_slot'];blob=row['embedding']
            observed.append({'id':row['id'],'vec_slot':slot,'embedding_hex':None if blob is None else bytes(blob).hex(),
                             'vector':None if slot is None else values[int(slot)]})
        spaces[space]=observed;high_water[space]=vectors.high_water(conn,space)
        free[space]=[r[0] for r in conn.execute('SELECT slot FROM ci_vec_free WHERE space=? ORDER BY slot',(space,))]
    markers=[list(r) for r in conn.execute("SELECT key,value FROM meta WHERE key GLOB '__ken_vector_*' ORDER BY key")]
    conn.close()
    if emb._singleton is not None:raise ValueError('recovery fixture instantiated a model')
    oracle={'frozen_import':True,'encoder_singleton_unloaded':True,'python':platform.python_version(),
            'sqlite':sqlite3.sqlite_version,'numpy':np.__version__,'sources':sources}
    print(json.dumps({'oracle':oracle,'data':{'spaces':spaces,'high_water':high_water,'free':free,'internal_markers':markers}},allow_nan=False))

if __name__=='__main__':main()

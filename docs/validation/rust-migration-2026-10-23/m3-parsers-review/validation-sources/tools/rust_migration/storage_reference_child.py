"""Isolated experiments; imports must resolve exclusively to the frozen original."""
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import warnings

import numpy as np
from ken import db,vectors
import ken.embedder as emb
import ken._paths as paths


def file_row(conn,path,embedding=None,slot=None):
    return conn.execute('INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) '
        'VALUES(?,x\'00\',0,0,?,?)',(path,embedding,slot)).lastrowid


def metadata(conn):
    return {r['key']:r['value'] for r in conn.execute('SELECT key,value FROM meta ORDER BY key')}


def schema(conn):
    objects=[list(r) for r in conn.execute("SELECT type,name,tbl_name FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    tables={}
    for kind,name,_ in objects:
        if kind!='table':continue
        columns=[list(r) for r in conn.execute('PRAGMA table_info('+json.dumps(name)+')')]
        indexes=[]
        for r in conn.execute('PRAGMA index_list('+json.dumps(name)+')'):
            indexes.append({'name':r[1],'unique':r[2],'origin':r[3],'partial':r[4],
                'columns':[list(c) for c in conn.execute('PRAGMA index_xinfo('+json.dumps(r[1])+')')]})
        tables[name]={'columns':columns,'indexes':sorted(indexes,key=lambda x:x['name']),
            'foreign_keys':[list(r) for r in conn.execute('PRAGMA foreign_key_list('+json.dumps(name)+')')]}
    return {'objects':objects,'tables':tables}


def schema_history(conn,data):
    file_row(conn,'é\0fixture.py');db.set_meta(conn,'keep','value')
    if data['legacy']:
        for name in ['idx_ci_imports_resolution','idx_ci_files_vec_slot','idx_ci_symbols_vec_slot','idx_ci_intent_sources_vec_slot']:
            conn.execute('DROP INDEX '+name)
        for name in ['trg_ci_files_free_slot','trg_ci_symbols_free_slot','trg_ci_intent_free_slot']:
            conn.execute('DROP TRIGGER '+name)
        for table,column in [('ci_imports','resolution'),('ci_files','vec_slot'),('ci_symbols','vec_slot'),
                             ('ci_intent_sources','vec_slot'),('ci_passages','implementation_start_line')]:
            conn.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
    before=[list(r) for r in conn.execute('SELECT id,path,content_hash FROM ci_files ORDER BY id')]
    db.init_schema(conn);once=schema(conn);db.init_schema(conn)
    return {'schema':once,'idempotent':once==schema(conn),'rows_preserved':before==[
        list(r) for r in conn.execute('SELECT id,path,content_hash FROM ci_files ORDER BY id')],
        'metadata':metadata(conn),'settings':{p:conn.execute('PRAGMA '+p).fetchone()[0]
            for p in ['journal_mode','synchronous','foreign_keys','busy_timeout']}}


def marker_history(conn,data):
    # A nullable legacy marker is intentional; present-empty is a different case.
    conn.execute('DROP TABLE meta');conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
    db.set_meta(conn,'unrelated','keep');db.set_meta(conn,'embed_doc_space','9')
    kind=data['marker']
    if kind in ('null','empty'):conn.execute('INSERT INTO meta VALUES(?,?)',('embed_model',None if kind=='null' else ''))
    if kind=='stored':db.set_meta(conn,'embed_model','stored/model')
    if kind=='vector-blob-empty':file_row(conn,'a.py',b'')
    if kind=='vector-slot-zero':file_row(conn,'a.py',slot=0)
    if kind=='vector-slot-negative':file_row(conn,'a.py',slot=-1)
    os.environ['KEN_EMBED_MODEL']=data['model'];before=metadata(conn)
    present=emb._has_embeddings(conn);selected=emb.configure_for_project(conn)
    return {'metadata_before':before,'metadata_after':metadata(conn),'selected':selected,'file_vectors_present':present}


def slot_history(conn,data):
    allocations=[]
    if data['rollback']:
        try:
            with vectors.immediate(conn):
                allocations.append(vectors.allocate(conn,'ci_files',4));raise RuntimeError('rollback fixture')
        except RuntimeError:pass
    else:
        with vectors.immediate(conn):
            allocations.append(vectors.allocate(conn,'ci_files',3));vectors.release(conn,'ci_files',[1,1])
            with vectors.immediate(conn):allocations.append(vectors.allocate(conn,'ci_files',2))
            vectors.allocate(conn,'ci_symbols',1)
    return {'allocations':allocations,'high_water':vectors.high_water(conn,'ci_files'),
        'free':[list(r) for r in conn.execute('SELECT space,slot FROM ci_vec_free ORDER BY space,slot')],
        'other_high_water':vectors.high_water(conn,'ci_symbols'),'in_transaction':conn.in_transaction}


def cascade_history(conn):
    fid=file_row(conn,'a.py',slot=3)
    for i,slot in enumerate((10,11)):
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(?,'function',?,1,2,?)",
            (fid,'f'+str(i),slot))
    conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at,vec_slot) VALUES(?,'module_docstring','fixture',0,7)",(fid,))
    conn.execute('DELETE FROM ci_files WHERE id=?',(fid,))
    return {'free':[list(r) for r in conn.execute('SELECT space,slot FROM ci_vec_free ORDER BY space,slot')],
        'rows':{table:conn.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in vectors.SPACES}}


def unique_history(conn):
    file_row(conn,'a.py',slot=7);rejected=False
    try:file_row(conn,'b.py',slot=7)
    except sqlite3.IntegrityError:rejected=True
    file_row(conn,'null1.py');file_row(conn,'null2.py')
    return {'duplicate_rejected':rejected,'null_slots':conn.execute('SELECT count(*) FROM ci_files WHERE vec_slot IS NULL').fetchone()[0]}


def vector_history(root,data):
    store=vectors.VectorStore(root,'ci_files',dim=data['dim'],model='fixture/model')
    matrix=np.stack([np.frombuffer(bytes.fromhex(value),dtype='<f4') for value in data['vectors_le_hex']])
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always');store.write(data['slots'],matrix)
        read=store.read(data['slots']);query=np.frombuffer(bytes.fromhex(data['query_le_hex']),dtype='<f4')
        scores=store.scores(query,count=max(data['slots'])+1)
    manifest=json.loads(store.manifest_path.read_text());store.close()
    # Reopen for actual persistence proof; no comparison algorithm produces values.
    with vectors.VectorStore(root,'ci_files',dim=data['dim']) as reopened:
        persisted=reopened.read(data['slots'])
    files=sorted((root/'.ken/vectors').glob('*.vec'))
    return {'read_le_hex':[row.astype('<f4').tobytes().hex() for row in read],
        'persisted_le_hex':[row.astype('<f4').tobytes().hex() for row in persisted],
        'scores_le_hex':scores.astype('<f4').tobytes().hex(),'score_count':len(scores),
        'manifest':manifest,'segments':[{'name':p.name,'bytes':p.stat().st_size} for p in files],
        'warnings':[str(w.message) for w in emitted]}


def migration_history(root,conn,data):
    file_row(conn,'matching.py',np.array([3,4,0,0],dtype='<f4').tobytes())
    if not data['twice']:file_row(conn,'foreign.py',np.array([1,0],dtype='<f4').tobytes())
    moved=[vectors.migrate_inline_vectors(conn,root,dim=4,batch=1)]
    if data['twice']:moved.append(vectors.migrate_inline_vectors(conn,root,dim=4,batch=1))
    rows=[{'id':r['id'],'path':r['path'],'embedding_hex':None if r['embedding'] is None else bytes(r['embedding']).hex(),
           'vec_slot':r['vec_slot']} for r in conn.execute('SELECT id,path,embedding,vec_slot FROM ci_files ORDER BY id')]
    with vectors.VectorStore(root,'ci_files',dim=4) as store:
        read=store.read([r['vec_slot'] for r in rows if r['vec_slot'] is not None]);report=store.verify(conn)
    return {'moved':moved,'rows':rows,'read_le_hex':[r.astype('<f4').tobytes().hex() for r in read],'verify':report}


def compact_history(root,conn,data):
    files=[file_row(conn,'file'+str(i)+'.py') for i in range(3)];expected={}
    matrix=np.eye(4,dtype=np.float32)[[3,0,3,1,3,2]]
    for space in vectors.SPACES:
        with vectors.immediate(conn):
            vectors.allocate(conn,space,6);vectors.release(conn,space,[0,2,4])
            for index,slot in enumerate([1,3,5]):
                if space=='ci_files':conn.execute('UPDATE ci_files SET vec_slot=? WHERE id=?',(slot,files[index]))
                elif space=='ci_symbols':conn.execute("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(?,'function',?,1,2,?)",(files[0],'f'+str(index),slot))
                else:conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at,vec_slot) VALUES(?,'module_docstring',?,0,?)",(files[0],'text'+str(index),slot))
        with vectors.VectorStore(root,space,dim=4,model='fixture/model') as store:store.write(list(range(6)),matrix)
        expected[space]={int(row['id']):matrix[int(row['vec_slot'])].copy() for row in conn.execute('SELECT id,vec_slot FROM '+space)}
    events=[];interrupted=False
    def progress(message):
        events.append(message)
        if data['interrupt']:raise RuntimeError('controlled original callback interruption')
    try:result=vectors.compact(conn,root,dim=4,progress=progress)
    except RuntimeError:interrupted=True;result=None
    states={};complete=True
    for space in vectors.SPACES:
        refs=[list(r) for r in conn.execute('SELECT id,vec_slot FROM '+space+' ORDER BY id')]
        with vectors.VectorStore(root,space,dim=4) as store:
            read=store.read([r[1] for r in refs]);report=store.verify(conn)
        for row,actual in zip(refs,read,strict=True):complete=complete and bool(np.array_equal(expected[space][row[0]],actual))
        states[space]={'references':refs,'read_le_hex':[r.astype('<f4').tobytes().hex() for r in read],'verify':report}
    return {'result':result,'events':events,'interrupted':interrupted,'complete_mapping':complete,'spaces':states}


def vacuum_history(root,conn):
    unit=np.zeros(128,dtype='<f4');unit[0]=1
    for i in range(400):file_row(conn,str(i)+'.py',unit.tobytes())
    moved=vectors.migrate_inline_vectors(conn,root,dim=128)
    before,after=vectors.reclaim_database(conn)
    return {'moved':moved,'rows':conn.execute('SELECT count(*) FROM ci_files WHERE vec_slot IS NOT NULL').fetchone()[0],
        'vacuum_completed':True}, {'main_bytes_before':before,'main_bytes_after':after}


def main():
    request=json.load(sys.stdin);reference=Path(request['reference']).resolve()
    modules={'src/ken/db.py':db,'src/ken/vectors.py':vectors,'src/ken/embedder/__init__.py':emb,'src/ken/_paths.py':paths}
    sources={}
    for name in request['owners']:
        actual=Path(db.__file__).with_name('schema.sql').resolve() if name.endswith('.sql') else Path(modules[name].__file__).resolve()
        if actual!=reference/name:raise ValueError('storage original import escaped frozen reference')
        sources[name]=hashlib.sha256(actual.read_bytes()).hexdigest()
    results=[]
    with tempfile.TemporaryDirectory(prefix='original-storage-cases-') as directory:
        for index,case in enumerate(request['cases']):
            root=Path(directory)/str(index);internal=root/'.ken';internal.mkdir(parents=True)
            (internal/'meta.json').write_text('{}');emb.reset_embedder()
            conn=db.connect(internal/'ken.db');db.init_schema(conn);data=case['input'];measurements={}
            try:
                op=data['op']
                if op=='schema':output=schema_history(conn,data)
                elif op=='metadata':
                    observed=[]
                    for value in data['values']:db.set_meta(conn,'key',value);observed.append(db.get_meta(conn,'key'))
                    output={'values':observed,'missing':db.get_meta(conn,'missing'),'default':db.get_meta(conn,'missing','fallback')}
                elif op=='marker':output=marker_history(conn,data)
                elif op=='slots':output=slot_history(conn,data)
                elif op=='cascade':output=cascade_history(conn)
                elif op=='unique':output=unique_history(conn)
                elif op=='vectors':output=vector_history(root,data)
                elif op=='migrate':output=migration_history(root,conn,data)
                elif op=='compact':output=compact_history(root,conn,data)
                elif op=='vacuum':output,measurements=vacuum_history(root,conn)
                elif op=='manifest':
                    with vectors.VectorStore(root,'ci_files',dim=4,model='fixture/model') as store:path=store.manifest_path
                    manifest=json.loads(path.read_text());manifest[data['field']]=data['value'];path.write_text(json.dumps(manifest))
                    with vectors.VectorStore(root,'ci_files',dim=4,model='fixture/model') as store:
                        output={'opened':True,'manifest':json.loads(store.manifest_path.read_text())}
                elif op=='sql-error':
                    conn.execute('ALTER TABLE ci_passages DROP COLUMN implementation_start_line');conn.execute('PRAGMA query_only=ON')
                    db._migrate(conn)
                    output={'migration_returned_success':True,'column_present':any(r[1]=='implementation_start_line' for r in conn.execute('PRAGMA table_info(ci_passages)'))}
                else:raise ValueError('unknown original storage operation')
                if op=='vectors':
                    measurements['segment_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted((root/'.ken/vectors').glob('*.vec'))}
                if emb._singleton is not None:raise ValueError('storage experiments instantiated an encoder')
                results.append({'id':case['id'],'classification':case['classification'],'output':output,'measurements':measurements})
            finally:conn.close();emb.reset_embedder()
    print(json.dumps({'scope':'original-storage/1','platform':platform.system(),'architecture':platform.machine(),
        'oracle':{'frozen_import':True,'encoder_singleton_unloaded':emb._singleton is None,'python':platform.python_version(),
                  'sqlite':sqlite3.sqlite_version,'numpy':np.__version__,'sources':sources},'results':results},allow_nan=False))


if __name__=='__main__':main()

"""Freeze real original SQLite/vector operations before native storage exists."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from .reference import Reference,reference_env,verify_reference
from .policy_compare import differences

OWNERS=('src/ken/db.py','src/ken/schema.sql','src/ken/vectors.py',
        'src/ken/embedder/__init__.py','src/ken/_paths.py')


def logical_storage_differences(expected:list,actual:object)->list[str]:
    """Compare valid histories; preserve correction observations and OS measurements.

    Only normalized/scored F32 payloads use 1e-6 + 1e-6 * abs(reference).
    Unchanged SQLite BLOBs, slots, IDs, fields and JSON primitive types stay exact.
    """
    def f32(want,got,path):
        if type(want) is not type(got):return [path+': JSON type differs']
        if isinstance(want,list):
            if len(want)!=len(got):return [path+': vector count differs']
            return [e for i,(w,g) in enumerate(zip(want,got,strict=True)) for e in f32(w,g,f'{path}[{i}]')]
        if (not isinstance(want,str) or not isinstance(got,str) or len(want)!=len(got)
                or any(re.fullmatch(r'(?:[0-9a-f]{8})*',v) is None for v in [want,got])):
            return [path+': canonical F32 payload required']
        pairs=zip(struct.iter_unpack('<f',bytes.fromhex(want)),struct.iter_unpack('<f',bytes.fromhex(got)),strict=True)
        for (w,),(g,) in pairs:
            if not math.isfinite(w) or not math.isfinite(g) or abs(w-g)>1e-6+1e-6*abs(w):
                return [path+': finite F32 values differ']
        return []
    def output(want,got,path):
        if type(want) is not type(got):return differences(want,got,path)
        if isinstance(want,dict):
            if set(want)!=set(got):return differences(want,got,path)
            return [e for key in want for e in (f32(want[key],got[key],path+'.'+key)
                if key in ('read_le_hex','persisted_le_hex','scores_le_hex') else output(want[key],got[key],path+'.'+key))]
        if isinstance(want,list):
            if len(want)!=len(got):return differences(want,got,path)
            return [e for i,(w,g) in enumerate(zip(want,got,strict=True)) for e in output(w,g,f'{path}[{i}]')]
        return differences(want,got,path)
    if not isinstance(actual,list) or len(expected)!=len(actual):return ['storage history coverage differs']
    errors=[]
    for index,(want,got) in enumerate(zip(expected,actual,strict=True)):
        path=f'histories[{index}]'
        if (not isinstance(got,dict) or set(want)!=set(got)
                or want['id']!=got.get('id') or want['classification']!=got.get('classification')):
            errors.append(path+': history identity/fields differ');continue
        if want['classification']=='compatibility':errors.extend(output(want['output'],got['output'],path+'.output'))
    return errors


def storage_cases()->list[dict]:
    rows=[]
    def add(name,op,**values):
        rows.append({'id':name,'classification':'integrity-correction' if name.startswith('correction-') else 'compatibility',
                     'input':{'op':op,**values}})
    for legacy in (False,True):add('schema-legacy' if legacy else 'schema-fresh','schema',legacy=legacy)
    add('metadata-strings','metadata',values=['','é/設定','\0middle\0','17'])
    for name in ['absent','null','empty','stored','vector-blob-empty','vector-slot-zero','vector-slot-negative']:
        add('marker-'+name,'marker',marker=name,model='user/model')
    add('slots-freed','slots',rollback=False);add('slots-rollback','slots',rollback=True)
    add('cascade','cascade');add('unique-slot','unique')
    def bits(*values):return struct.pack('<'+'f'*len(values),*values).hex()
    for name,slots,vectors in [
        ('boundary',[65535,65536],[[1,0,0,0],[0,1,0,0]]),
        ('sparse',[131072],[[0,0,1,0]]),
        ('duplicates',[2,0,2],[[1,0,0,0],[0,1,0,0],[0,0,1,0]]),
        ('zero',[0],[[0,0,0,0]]),
        ('mixed',[0,1],[[3,4,0,0],[1,-2,3,-4]]),
    ]:
        add('vectors-'+name,'vectors',slots=slots,vectors_le_hex=[bits(*v) for v in vectors],
            query_le_hex=bits(1,2,3,4),dim=4)
    for twice in (False,True):add('migrate-twice' if twice else 'migrate-mixed','migrate',twice=twice)
    add('compact','compact',interrupt=False);add('vacuum','vacuum')
    for field,value in [('space','ci_symbols'),('dtype','float16'),('segment_rows',0),('model','other/model')]:
        label={'segment_rows':'capacity'}.get(field,field)
        add('correction-manifest-'+label,'manifest',field=field,value=value)
    for name,vector in [('norm-overflow',bits(1e30,1e30)),('nan','0000c07f0000803f'),('inf','0000807f0000803f')]:
        add('correction-'+name,'vectors',slots=[0],vectors_le_hex=[vector],query_le_hex=bits(1,0),dim=2)
    add('correction-sql-error','sql-error')
    add('correction-compaction-interruption','compact',interrupt=True)
    return rows


def capture_storage(reference:Reference,out:Path)->dict:
    if (any(not (reference.root/p).is_file() for p in OWNERS)
            or not reference.manifest_path.is_file()
            or not set(OWNERS)<={r['path'] for r in json.loads(reference.manifest_path.read_text())['files']}):
        raise ValueError('complete frozen storage reference required')
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen storage reference drift')
    child=Path(__file__).with_name('storage_reference_child.py').read_text()
    request={'reference':str(reference.root),'owners':list(OWNERS),'cases':storage_cases()}
    with tempfile.TemporaryDirectory(prefix='ken-storage-original-') as directory:
        sandbox=Path(directory)
        process=subprocess.run([str(reference.python),'-c',child],input=json.dumps(request,allow_nan=False),
            text=True,capture_output=True,cwd=sandbox,env=reference_env(reference,sandbox/'environment'),timeout=180)
    if process.returncode or process.stderr:raise ValueError('original storage capture failed: '+process.stderr)
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen storage reference drift')
    result=json.loads(process.stdout);result['reference_fingerprint']=reference.fingerprint
    out=out.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=True,allow_nan=False)+'\n')
    out.with_suffix('.stderr.log').write_text(process.stderr)
    return result

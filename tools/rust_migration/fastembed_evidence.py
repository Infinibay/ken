"""Authenticate one execution tree, then recompare its owned raw FastEmbed bytes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import zlib

from . import policy_evidence as policy
from . import storage_evidence as storage
from .context_compare import RUNTIME_REGISTRATION,core_for_platform
from .context_reference import CPU_WARNING,stderr_errors
from .fastembed_compare import ROOT,compare_model,native_producer
from .fastembed_ownership import MODELS,ownership_errors,_exact
from .fastembed_process import decode_frames,_distinct,_nonfinite
from .fastembed_reference import RAW_LIMIT,read_chunk,native_request,known_original_failure
from .policy_compare import dependency_errors

FORMAT='ken-fastembed-execution/1'


def seal_execution(root:Path)->dict:return policy.seal_execution(root,format=FORMAT)


def authenticate_chunk(payload:bytes,receipt:dict)->dict:
    """No path IO: the containing execution manifest already owns these bytes."""
    if (type(receipt) is not dict or set(receipt)!={'path','bytes','sha256','raw_bytes','raw_sha256'}
            or type(receipt['path']) is not str or Path(receipt['path']).name!=receipt['path']
            or receipt['path'] in ('','.','..')
            or any(type(receipt[k]) is not int for k in ['bytes','raw_bytes'])
            or not 0<receipt['bytes']<=RAW_LIMIT+1024*1024 or not 0<receipt['raw_bytes']<=RAW_LIMIT
            or len(payload)!=receipt['bytes'] or hashlib.sha256(payload).hexdigest()!=receipt['sha256']):
        raise ValueError('compressed chunk authentication/bound failed')
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
    try:raw=decoder.decompress(payload,RAW_LIMIT+1)
    except zlib.error as error:raise ValueError('invalid compressed chunk') from error
    if len(raw)>RAW_LIMIT or decoder.unconsumed_tail:raise ValueError('decompressed chunk exceeds bound')
    if not decoder.eof or decoder.unused_data:raise ValueError('truncated or trailing compressed stream')
    if len(raw)!=receipt['raw_bytes'] or hashlib.sha256(raw).hexdigest()!=receipt['raw_sha256']:
        raise ValueError('raw chunk hash/size mismatch')
    value=json.loads(raw,object_pairs_hook=_distinct,parse_constant=_nonfinite)
    if type(value) is not dict:raise ValueError('raw record object required')
    return value


def execution_errors(root:Path,row:dict)->list[str]:
    try:
        files=policy.authenticate_manifest(row.get('execution_artifacts',{}),lambda name:policy._read(root,name),format=FORMAT)
        return _proof_errors(files,row)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError) as error:
        return ['FastEmbed execution evidence: '+str(error)]


def _registered_stderr(value:str,definition:dict,original:dict,system:str)->list[str]:
    if not stderr_errors(value,system):return []
    failures=[r for r in original['results'] if 'error' in r]
    if not failures or not all(known_original_failure(definition,r['error'],system) for r in failures):
        return ['unexpected raw FastEmbed stderr']
    remaining=value.removeprefix(CPU_WARNING) if system=='Linux' else value
    remaining=remaining.replace('\x1b[1;31m','').replace('\x1b[m','')
    lines=[line for line in remaining.splitlines() if line]
    markers=('Exception during initialization:','GetIndexFromName',
        'Attempting to get index by a name which does not exist:',
        'InsertedPrecisionFreeCast_/encoder/layer.11/attention/output/LayerNorm/Constant_output_0',
        'for node: /embeddings/LayerNorm/Mul/SimplifiedLayerNormFusion/')
    if len(lines)!=len(failures) or any(not all(m in line for m in markers) for line in lines):
        return ['unregistered raw FastEmbed initialization diagnostic']
    return []


def _proof_errors(files:dict[str,bytes],row:dict)->list[str]:
    from .fastembed_validate import fastembed_receipt_errors,REGISTRY,ORIGINAL
    def required(name):
        policy._relative(name)
        if name not in files:raise ValueError('unlisted required FastEmbed execution artifact: '+name)
        return files[name]
    def document(name):return json.loads(required(name),object_pairs_hook=_distinct,parse_constant=_nonfinite)
    def equal(name,wanted):
        if not _exact(document(name),wanted):raise ValueError('raw/embedded FastEmbed proof differs: '+name)
    errors=fastembed_receipt_errors(row,row['fingerprints'])
    equal('base/summary.json',row['storage_base'])
    base=policy.authenticate_manifest(row['storage_base']['execution_artifacts'],lambda name:required('base/'+name),format=storage.FORMAT)
    errors+=storage._proof_errors(base,row['storage_base'])
    catalogue=json.loads(REGISTRY.read_bytes());cases=json.loads((ORIGINAL/'cases.json').read_bytes())
    index=json.loads((ORIGINAL/'reference-index.json').read_bytes())
    matches=[p for p in index['platforms'] if (p['platform'],p['architecture'])==(row['platform'],row['architecture'])]
    if len(matches)!=1:raise ValueError('one registered original platform required')
    directory=ORIGINAL/matches[0]['directory'];raw_index=(directory/'index.json').read_bytes()
    if hashlib.sha256(raw_index).hexdigest()!=matches[0]['index_sha256']:raise ValueError('original platform index changed')
    model_index=json.loads(raw_index)
    originals={m['model']:read_chunk(directory,m['record']) for m in model_index['models']}
    definitions={m['name']:m for m in catalogue['models']}
    core=core_for_platform(json.loads(RUNTIME_REGISTRATION.read_bytes()),row['platform'],row['architecture'])
    producer=native_producer();parity=row['fastembed_parity'];ownership=row['fastembed_ownership']
    for key,proof in [('fastembed-parity',parity),('fastembed-ownership',ownership)]:
        equal(key+'/summary.json',proof)
        for index,item in enumerate(proof['models']):
            if item['directory']!=f'{index:02}':raise ValueError('ordered canonical raw model directory required')
            prefix=key+'/'+item['directory']+'/'
            record=authenticate_chunk(required(prefix+item['record']['path']),item['record'])
            name=item['model'];definition=definitions[name];original=originals[name]
            assets=definition['assets']
            source_suffix=(assets['model_id'].replace('/','--'),assets['revision'])
            model_cases=[c for c in cases if c['model']==name]
            if record['model']!=name or record['producer']!=producer:errors.append('raw native model/source identity differs')
            process=record['process'];frames=decode_frames(record['stdout'])
            if (type(process.get('native_exit')) is not int or process['native_exit']!=0
                    or process.get('outside_checkout') is not True or process.get('native_children')!=[]
                    or process.get('owned_after_exit')!=[] or process.get('native_sha256')!=parity['native_sha256']
                    or process.get('core_sha256')!=core['sha256'] or process.get('registry_sha256')!=parity['registry_sha256']
                    or type(process.get('native_process_wall_ns')) is not int or process['native_process_wall_ns']<=0
                    or (row['platform']=='Linux' and (type(process.get('exec_attempts')) is not int or process['exec_attempts']!=1))
                    or (row['platform']=='Darwin' and process.get('exec_attempts') is not None)):
                errors.append('invalid actual native process/identity/measurement witness')
            command=process['command'];native_command=command[-11:]
            if (type(command) is not list or len(command)!=(17 if row['platform']=='Linux' else 11)
                    or native_command[1::2]!=['--registry','--sources','--work','--runtime-library','--model']
                    or native_command[-1]!=name or any(not Path(p).is_absolute() for p in native_command[:9:2])):
                errors.append('invalid native command boundary')
            if row['platform']=='Linux':
                trace=required(prefix+'native-exec.trace').decode()
                if len(re.findall(r'\bexecve(?:at)?\(',trace))!=1 or native_command[0] not in trace:
                    errors.append('exactly one matching native executable trace required')
            errors+=_registered_stderr(record['stderr'],definition,original,row['platform'])
            if key=='fastembed-parity':
                expected=[{'id':name+':control-cold','operation':'status'},*[native_request(c) for c in model_cases],{'id':name+':control-final','operation':'status'}]
                if (record['format']!='ken-fastembed-native-record/1' or not _exact(record['requests'],expected)
                        or not _exact(record['source_before'],record['source_after'])
                        or record['source_before']['artifacts']!=definition['assets']['artifacts']
                        or not Path(record['source_before']['snapshot']).is_absolute()
                        or Path(record['source_before']['snapshot']).parts[-2:]!=source_suffix
                        or record['oracle_sha256']!=hashlib.sha256(json.dumps(original,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
                        or item['cases']!=len(model_cases) or item['native_process_wall_ns']!=process['native_process_wall_ns']
                        or item['vector_rows']!=sum(len(c['input']['texts']) for c,r in zip(model_cases,original['results'],strict=True) if 'error' not in r)):
                    errors.append('raw native request/source/oracle/measurement differs')
                errors+=compare_model(definition,model_cases,original,frames,producer,core)
            else:
                from .fastembed_ownership import ownership_requests
                case=next(c for c in model_cases if c['id'].endswith(':mixed_queries'))
                wanted=next(r for r in original['results'] if r['id']==case['id'])
                if (record['format']!='ken-fastembed-ownership-record/1'
                        or not _exact(record['requests'],ownership_requests(name,case))
                        or not _exact(record['canonical_before'],record['canonical_after'])
                        or not Path(record['canonical_before']['snapshot']).is_absolute()
                        or Path(record['canonical_before']['snapshot']).parts[-2:]!=source_suffix
                        or record['canonical_before']['artifacts']!=definition['assets']['artifacts']):
                    errors.append('raw native ownership request/canonical source differs')
                errors+=ownership_errors(definition,case,wanted,frames,record['facts'],process,producer,core,
                    native_sha256=parity['native_sha256'],registry_sha256=parity['registry_sha256'])
    audits=parity['dependency_audits']
    if set(audits)!={'binary','core'}:errors.append('binary and core dependency audits required')
    for role,audit in audits.items():
        if role not in ('binary','core'):raise ValueError('unexpected dependency audit role')
        linked=required('fastembed-parity/'+role+'-audit/dependencies.log')
        tree=required('fastembed-parity/'+role+'-audit/cargo-tree.log')
        if (audit.get('passed') is not True or type(audit.get('linked_exit')) is not int or audit['linked_exit']!=0
                or type(audit.get('tree_exit')) is not int or audit['tree_exit']!=0
                or audit.get('linked_sha256')!=hashlib.sha256(linked).hexdigest()
                or audit.get('tree_sha256')!=hashlib.sha256(tree).hexdigest()
                or not tree.startswith(b'ken-models ') or re.search(rb'libpython|pyo3|cpython',tree,re.I)):
            errors.append('invalid raw FastEmbed dependency audit')
        linked_text=linked.decode()
        if role=='core' and row['platform']=='Linux':
            # The registered standalone ORT wheel also links these glibc
            # compatibility libraries; the Rust policy binary does not.
            ordinary={'libdl.so.2','librt.so.1','libpthread.so.0'}
            lines=[]
            for line in linked_text.splitlines():
                fields=line.split()
                if (len(fields)>=3 and fields[0] in ordinary and fields[1]=='=>'
                        and fields[2] in {f'/lib/aarch64-linux-gnu/{fields[0]}',f'/usr/lib/aarch64-linux-gnu/{fields[0]}'}):continue
                lines.append(line)
            linked_text='\n'.join(lines)
        elif role=='core' and row['platform']=='Darwin':
            registered={'@rpath/libonnxruntime.1.25.1.dylib','/usr/lib/libobjc.A.dylib',
                '/System/Library/Frameworks/CoreML.framework/Versions/A/CoreML',
                '/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation',
                '/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation'}
            lines=linked_text.splitlines()
            linked_text='\n'.join([lines[0],*[line for line in lines[1:]
                if not line.split() or line.split()[0] not in registered]])
        errors+=dependency_errors(linked_text,row['platform'])
    return errors

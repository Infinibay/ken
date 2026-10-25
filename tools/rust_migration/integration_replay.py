"""Independently replay saved factory bytes against pinned previous observations."""
from __future__ import annotations
import hashlib,json,math,re
from pathlib import Path
from .fastembed_process import _distinct,_nonfinite,decode_frames


def _json(path:Path):
    return json.loads(path.read_bytes(),object_pairs_hook=_distinct,parse_constant=_nonfinite)


def replay_transformer_profile(directory:Path,repo:Path,system:str,index:int)->list[str]:
    errors=[]
    try:
        def require(condition,message):
            if not condition:raise ValueError(message)
        root=repo/'docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance'/system
        trusted=_json(root/'summary.json')['profiles'][index]
        original=_json(root/trusted['directory']/'inputs.json')
        direct=_json(root/trusted['directory']/'actual.json')
        request=_json(directory/'inputs.json');frames=decode_frames((directory/'stdout.json').read_text())
        require(len(frames)==1,'one complete factory frame required');actual=frames[0]
        receipt=_json(directory/'observed.receipt.json');build=_json(directory/'BUILD.json')
        require(receipt['native_sha256']==build['native_sha256'],'factory host binary binding differs')
        require(receipt['native_exit']==0 and receipt['outside_checkout']is True and receipt['native_children']==[]
            and receipt['owned_after_exit']==[] and receipt['execution_audit']is True,'incomplete native execution/ownership')
        require(receipt['fixed_deadline_s']==trusted['execution']['fixed_deadline_s']and
            0<receipt['elapsed_s']<=receipt['fixed_deadline_s'],'original execution bound differs')
        require(receipt['command'][-2]=='--factory'and'ken-transformer-process-'in receipt['command'][-3],'wrong outside-checkout command')
        loader=(directory/'stderr.log').read_text()
        require('libpython'not in loader and'libtorch_python'not in loader,'forbidden Python linkage')
        backend='mlx'if original['runtime']['backend']=='mlx'else'sentence-transformers'
        role='judge'if original['model']['role']=='judge'else'encoder'
        family='mlx'if backend=='mlx'else'sentence_transformer'
        legacy=_json(repo/'crates/ken-models/tests/fixtures/profile-identity'/('macos-mlx.json'if backend=='mlx'else'macos-torch.json'))['legacy_runtime']
        if system=='linux':
            for pair in legacy['backends']['sentence-transformers']:
                if pair[0]=='torch':pair[1]='2.9.0+cpu'
        spec={'model_id':original['model']['assets']['model_id'],'revision':original['model']['assets']['revision'],
            'backend':backend,'dtype':original['dtype'],'sequence_length':original['sequence_length'],'batch_size':original['batch_size']}
        require(request['selection']=={'kind':role,'spec':spec,'legacy':legacy},'requested original profile/runtime differs')
        require(request['source_overrides']=={spec['model_id']:original['snapshot']},'pinned borrowed source identity differs')
        native_name='mlx'if backend=='mlx'else'torch';native=request[native_name]
        require(native['registration']==original['runtime'],'registered native module/core differs')
        require(all(Path(native[k]).is_absolute()for k in('module','core_root')),'absolute prepared native resources required')
        selected={'role':role,'spec':spec,'requested_device':original.get('device',{'kind':'mps'})}
        if role=='encoder':selected['family']=family
        require(actual['format']=='ken-model-factory-observation/1'and actual['selection']==selected,'actual selected role/family/profile differs')
        require(request['device']==selected['requested_device'],'requested device differs')
        identity=hashlib.sha256(json.dumps({'config':spec,'runtime':legacy['backends'][backend]},sort_keys=True).encode()).hexdigest()[:16]
        require(actual['compatible_key']==spec['model_id']+'@'+spec['revision']+':'+identity,'compatible original key differs')
        require(request['policy']==actual['policy']=='offline','offline profile execution required')
        require(actual['initial_prepared']is False and actual['after_empty_prepared']is False,'factory cold/empty lifecycle differs')
        if system=='linux':
            require(Path(receipt['command'][0]).name=='strace'and receipt['command'][1:5]==['--seccomp-bpf','-f','-e','trace=execve,execveat,connect'],
                'actual tracer command must observe both exec syscalls and network')
            require(receipt['exec_attempts']==1 and receipt['execution_audit_syscalls']==['execve','execveat','connect'],'both exec and network audits required')
            trace=(directory/'exec.trace').read_text()
            require(len(re.findall(r'\bexecve(?:at)?\(',trace))==1 and receipt['command'][-3]in trace,'unexpected/missing actual exec')
            require(re.search(r'\bconnect\(',trace)is None,'offline factory opened network connection')
        library='libmlx.dylib'if backend=='mlx'else('libtorch_cpu.so'if system=='linux'else'libtorch_cpu.dylib')
        require(any('ken-transformer-'in line and library in line for line in loader.splitlines()),'actual private native core load missing')
        expected_cases=[];gold=[]
        for case,row in zip(original['cases'],direct['rows'],strict=True):
            if role=='encoder':
                require(case['side']=='passage','registered original first batch must be passages')
                call={'operation':'passages','texts':case['texts']}
            else:call={'operation':'score',**{k:case[k]for k in('query','documents','purpose')}}
            expected_cases.append({'id':case['id'],'call':call});gold.append(row)
            if role=='encoder'or row.get('passed_original_call'):break
        require(request['cases']==expected_cases,'actual public inputs differ from original representative calls')
        require(len(actual['rows'])==len(gold),'partial factory output')
        for observed,expected in zip(actual['rows'],gold,strict=True):
            require(observed['id']==expected['id']and observed['prepared']is True,'case identity or prepared state differs')
            trace=observed['preparation']['trace']if role=='encoder'else observed['preparation']
            require(trace==expected['preparation'],'actual model/core/module/device/dtype differs')
            if role=='encoder':require(observed['preparation']['family']==family,'prepared encoder family differs')
            if role=='judge'and not expected['passed_original_call']:
                require(observed['error']['kind']==expected['exception'],'original judge error differs')
            else:
                field='scores'if role=='judge'else'vectors'
                # Direct adapters remain independently accredited against the
                # original fixed-tolerance corpus. New factory outputs are exact.
                require(observed['result'][field]==expected[field],'factory/direct native values differ')
                def finite(value):
                    return all(finite(x)for x in value)if isinstance(value,list)else type(value)in(float,int)and math.isfinite(value)
                require(finite(observed['result'][field]),'nonfinite factory output')
        runtimes=actual['runtime'];require(set(runtimes)=={'onnx','torch','mlx'},'incomplete runtime observations')
        require(runtimes[native_name]==gold[-1]['preparation']['runtime'],'executing native runtime differs')
        require(all(value is None for key,value in runtimes.items()if key!=native_name),'unused native family loaded')
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration)as error:
        errors.append('saved factory profile: '+str(error))
    return errors


def replay_role(directory:Path,repo:Path,system:str,name:str,phase:str)->list[str]:
    """Compare published raw role output with its retained original recipe."""
    errors=[]
    try:
        import numpy as np
        from .integration_roles import role_cases
        def require(condition,message):
            if not condition:raise ValueError(message)
        recipe=next(r for r in role_cases(repo,system)if r['name']==name)
        request=_json(directory/'inputs.json');frames=decode_frames((directory/'stdout.json').read_text())
        require(len(frames)==1,'one complete role frame required');actual=frames[0]
        receipt=_json(directory/'observed.receipt.json');build=_json(directory/'BUILD.json')
        require(receipt['native_sha256']==build['native_sha256'],'native role host differs')
        require(receipt['native_exit']==0 and receipt['outside_checkout']is True and receipt['owned_after_exit']==[]
            and receipt['native_children']==[] and receipt['execution_audit']is True,'actual native role execution missing')
        require(receipt['command'][-2]=='--factory'and'ken-transformer-process-'in receipt['command'][-3],'outside-checkout command differs')
        require(phase in('offline','public')and(request['policy']==actual['policy']==phase),'explicit role acquisition policy differs')
        require(request['cases']==recipe['calls'],'role public inputs differ from original')
        require(actual['format']=='ken-model-factory-observation/1'and actual['initial_prepared']is False,'role constructor loaded model')
        if system=='linux':
            require(Path(receipt['command'][0]).name=='strace'and receipt['command'][1:5]==['--seccomp-bpf','-f','-e','trace=execve,execveat,connect'],
                'actual tracer command must observe both exec syscalls and network')
            require(receipt['exec_attempts']==1 and receipt['execution_audit_syscalls']==['execve','execveat','connect'],'missing actual exec/connect audit')
            trace=(directory/'exec.trace').read_text()
            require(len(re.findall(r'\bexecve(?:at)?\(',trace))==1 and receipt['command'][-3]in trace,'unexpected/missing native role exec')
            if phase=='offline':require(re.search(r'\bconnect\(',trace)is None,'offline role used network')
        loader=(directory/'stderr.log').read_text();require('libpython'not in loader and'libtorch_python'not in loader,'forbidden Python linkage')
        resources=repo/'crates/ken-models/resources';expected=recipe['expected'];rows=actual['rows']
        require(len(rows)==len(recipe['calls'])and[r['id']for r in rows]==[r['id']for r in recipe['calls']],'missing/duplicated role calls')
        def vectors(left,right):
            a=np.asarray(left,dtype=np.float32);b=np.asarray(right,dtype=np.float32);tol=recipe['tolerances']
            require(a.shape==b.shape and np.isfinite(a).all()and np.allclose(a,b,atol=tol['atol'],rtol=tol['rtol']),'original role values differ')
            if'cosine_min'in tol:
                for l,r in zip(a.reshape(-1,a.shape[-1]),b.reshape(-1,b.shape[-1]),strict=True):
                    norm=np.linalg.norm(l)*np.linalg.norm(r)
                    require(not norm or float(np.dot(l,r)/norm)>=tol['cosine_min'],'original cosine threshold differs')
        if name in('static','potion'):
            registration=_json(resources/('legacy-compatibility.json'if name=='static'else'potion-code-16M-v2.json'))
            if name=='static':registration=registration['static_table']
            revision=registration['sha256']if name=='static'else hashlib.sha256(json.dumps(registration,sort_keys=True).encode()).hexdigest()
            spec={'model_id':registration['model_id'],'revision':revision,'backend':'static'if name=='static'else'model2vec',
                'dtype':'float32'if name=='static'else'float16','sequence_length':512,'batch_size':16 if name=='static'else 1024}
            legacy=_json(repo/'crates/ken-models/tests/fixtures/profile-identity/macos.json')['legacy_runtime']
            require(request['selection']=={'kind':'encoder','spec':spec,'legacy':legacy},'requested role profile/runtime differs')
            family='static_table'if name=='static'else'potion'
            require(actual['selection']=={'role':'encoder','family':family,'spec':spec,'requested_device':{'kind':'cpu'}},'actual family/profile differs')
            suffix=hashlib.sha256(json.dumps({'config':spec,'runtime':legacy['backends'][spec['backend']]},sort_keys=True).encode()).hexdigest()[:16]
            require(actual['compatible_key']==spec['model_id']+'@'+revision+':'+suffix,'compatible role identity differs')
            require(actual['after_empty_prepared']is False,'empty role loaded')
            preparation={'family':family,('sha256'if name=='static'else'assets_fingerprint'):revision}
            require(all(r['preparation']==preparation and r['prepared']is True for r in rows),'actual authenticated role preparation differs')
            require(rows[0]['result']['count']==expected['count'],'original raw count differs')
            vectors(rows[1]['result']['vectors'],expected['vectors']);vectors(rows[2]['result']['vectors'],expected['vectors']*8)
        elif name=='context':
            require(actual['selection']=={'role':'context'}and request['selection']=={'kind':'context'},'wrong contextual role')
            require(rows[0]['result']['tokens']==expected['tokens'],'original contextual tokens differ');vectors(rows[0]['result']['vectors'],expected['vectors'])
        elif name=='reranker':
            require(actual['selection']=={'role':'reranker'}and request['selection']=={'kind':'reranker'},'wrong reranker role')
            vectors([rows[0]['result']['scores']],[expected['scores']])
        elif name=='expansion':
            require(actual['selection']=={'role':'expansion'}and request['selection']=={'kind':'expansion'},'wrong expansion role')
            require(rows[0]['result']['text']=='Where are names normalized?'and rows[0]['prepared']is False,'English lazy policy differs')
            value=rows[1]['result'];require(value['text']==expected['output'],'original translation differs');gold=expected['trace'];trace=value['trace']
            require(all(trace[k]==gold[k]for k in('prepared','hypotheses','decoded'))and trace['tokens']['ids']==gold['source_ids']
                and trace['tokens']['pieces_with_eos']==gold['source_pieces_with_eos'],'actual original translation tokens/hypotheses differ')
        elif name=='fastembed':
            model='sentence-transformers/all-MiniLM-L6-v2';require(request['selection']=={'kind':'legacy_encoder','name':model},'wrong legacy model')
            require(actual['selection']=={'role':'encoder','family':'fast_embed','name':model,'requested_device':'cpu'},'wrong FastEmbed family')
            import gzip
            direct_record=json.loads(gzip.decompress(recipe['reference'].read_bytes()),object_pairs_hook=_distinct,parse_constant=_nonfinite)
            direct=next(frame for frame in decode_frames(direct_record['stdout'])if frame['id'].endswith(':mixed_passages'))
            require(rows[0]['prepared']is True and rows[0]['before_prepared']is False
                and actual['after_empty_prepared']is False,'actual FastEmbed preparation lifecycle differs')
            require(rows[0]['preparation']=={'family':'fast_embed','trace':direct['preparation']},
                'actual FastEmbed model/artifact/runtime/provider preparation differs')
            vectors(rows[0]['result']['vectors'],expected['vectors'])
        runtime=actual['runtime'];require(set(runtime)=={'onnx','torch','mlx'},'incomplete runtime declaration')
        require(runtime['torch']is None and runtime['mlx']is None,'unselected optional tensor core loaded')
        if name in('context','reranker','fastembed'):
            declaration=_json(repo/'crates/ken-models/resources/onnx-runtime-libraries.json')
            identity=next(r for r in declaration['libraries']if r['os']==system and r['arch']=='aarch64')
            require(runtime['onnx']==identity,'actual ONNX core identity differs')
            # NativeOnnxRuntime authenticates bytes, maps a NamedTempFile, then
            # unlinks it. The loader sees its random private .tmp name.
            require(any('ken-transformer-process-'in line and re.search(r'/\.tmp[A-Za-z0-9]+(?:\s|$)',line)
                and ('calling init:'in line if system=='linux'else line.startswith('dyld['))
                for line in loader.splitlines()),'actual private ONNX native load absent')
        else:require(runtime['onnx']is None,'unselected ONNX core loaded')
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration)as error:errors.append('saved factory role: '+str(error))
    return errors

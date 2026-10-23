"""Execute fresh factory paths; preserve old neural observations at their old hashes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
from .integration_process import run_factory


def digest(path):
    raw=Path(path).read_bytes()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def capture_transformers(repo:Path,probe:Path,out:Path)->dict:
    system='macos'if platform.system()=='Darwin'else'linux'
    predecessor=repo/'docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance'/system
    inventory=json.loads((predecessor/'summary.json').read_bytes())
    identities=repo/'crates/ken-models/tests/fixtures/profile-identity'
    rows=[]
    for profile in inventory['profiles']:
        old=predecessor/profile['directory']
        inputs=json.loads((old/'inputs.json').read_bytes());direct=json.loads((old/'actual.json').read_bytes())
        kind='judge'if inputs['model']['role']=='judge'else'encoder'
        backend='mlx'if inputs['runtime']['backend']=='mlx'else'sentence-transformers'
        legacy=json.loads((identities/('macos-mlx.json'if backend=='mlx'else'macos-torch.json')).read_bytes())['legacy_runtime']
        if system=='linux':
            for pair in legacy['backends']['sentence-transformers']:
                if pair[0]=='torch':pair[1]='2.9.0+cpu'
        spec={'model_id':inputs['model']['assets']['model_id'],'revision':inputs['model']['assets']['revision'],
              'backend':backend,'dtype':inputs['dtype'],'sequence_length':inputs['sequence_length'],'batch_size':inputs['batch_size']}
        cases=[];gold=[]
        if kind=='encoder':
            case=inputs['cases'][0];reference=direct['rows'][0]
            if case['side']!='passage':raise ValueError('first original encoder case must preserve passage batch')
            cases=[{'id':case['id'],'call':{'operation':'passages','texts':case['texts']}}]
            gold=[{'vectors':reference['vectors']}]
        else:
            # Keep the actual original empty-load policy and then the first
            # successful public score request before any budget demotion.
            for case,reference in zip(inputs['cases'],direct['rows'],strict=True):
                cases.append({'id':case['id'],'call':{'operation':'score',**{k:case[k]for k in ('query','documents','purpose')}}})
                gold.append({'scores':reference['scores']}if reference.get('passed_original_call')else{'error_kind':reference['exception']})
                if reference.get('passed_original_call'):break
        core_env='KEN_MLX_CORE'if backend=='mlx'else'KEN_TORCH_CORE'
        module_env='KEN_MLX_MODULE'if backend=='mlx'else'KEN_TORCH_MODULE'
        native={'registration':inputs['runtime'],'module':os.environ[module_env],'core_root':os.environ[core_env]}
        request={'format':'ken-model-factory-request/1','policy':'offline','cache_root':str(out/'cache'),
                 'private_parent':str(out/'private'),'bundled_npz':str(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz'),
                 'source_overrides':{spec['model_id']:inputs['snapshot']},
                 'device':inputs.get('device',{'kind':'mps'}),'fastembed_device':'cpu',
                 'selection':{'kind':kind,'spec':spec,'legacy':legacy},
                 'cases':cases,('mlx'if backend=='mlx'else'torch'):native}
        output=out/profile['directory']
        observed=run_factory(probe,request,output,deadline_s=profile['execution']['fixed_deadline_s'])
        (output/'observed.receipt.json').write_text(json.dumps(observed['receipt'],indent=2)+'\n')
        actual=observed['actual'];errors=[]
        if actual['initial_prepared']or actual['after_empty_prepared']:errors.append('cold/empty preparation changed')
        if actual['selection']['spec']!=spec:errors.append('actual profile differs')
        family='mlx'if backend=='mlx'else'sentence_transformer'
        if kind=='encoder'and actual['selection']['family']!=family:errors.append('actual family differs')
        if len(actual['rows'])!=len(cases):errors.append('missing public calls')
        maximum=0.;values=0
        def compare(a,b):
            nonlocal maximum,values
            if isinstance(b,list):
                if not isinstance(a,list)or len(a)!=len(b):raise ValueError('output dimensions differ')
                for left,right in zip(a,b,strict=True):compare(left,right)
            else:
                import math
                if type(a)not in(float,int)or not math.isfinite(a):raise ValueError('invalid native value')
                maximum=max(maximum,abs(a-b));values+=1
        for case,reference,frame in zip(cases,gold,actual['rows'],strict=True):
            if frame['id']!=case['id']:errors.append('case order differs')
            if 'error_kind'in reference:
                if frame.get('error',{}).get('kind')!=reference['error_kind']:errors.append('original error type differs')
            else:
                field='scores'if kind=='judge'else'vectors'
                try:compare(frame['result'][field],reference[field])
                except(KeyError,ValueError,TypeError)as e:errors.append(str(e))
            trace=frame['preparation']['trace']if kind=='encoder'else frame['preparation']
            old_trace=next(row for row in direct['rows']if row['id']==case['id'])['preparation']
            if trace!=old_trace:errors.append('actual prepared model/core/device/dtype differs from accepted direct path')
        # Fresh factory and unchanged direct adapter must agree bit-for-bit;
        # the retained direct-to-original proof retains its own fixed tolerance.
        if maximum!=0:errors.append('factory/direct numerical values differ')
        row={'key':profile['key'],'request':digest(output/'inputs.json'),'stdout':digest(output/'stdout.json'),
             'receipt':digest(output/'observed.receipt.json'),'reference_inputs':digest(old/'inputs.json'),
             'reference_direct':digest(old/'actual.json'),'passed':not errors,'errors':errors,
             'scalar_values':values,'maximum_absolute_error_to_accepted_direct':maximum}
        rows.append(row)
        (out/'capture-progress.json').write_text(json.dumps({'platform':system,'profiles':rows,'M2_accepted':False},indent=2)+'\n')
        print(json.dumps({'key':row['key'],'passed':row['passed'],'errors':errors}),flush=True)
        if errors:raise ValueError('new factory profile rejected: '+profile['key'])
    summary={'format':'ken-factory-transformer-capture/1','platform':system,'profiles':rows,'M2_accepted':False,
             'scope':'Fresh representative factory calls only; full historical original equivalence remains bound to its original hosts/sources/modules.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();capture_transformers(args.repo.resolve(),args.probe.resolve(),args.out.resolve())

if __name__=='__main__':main()

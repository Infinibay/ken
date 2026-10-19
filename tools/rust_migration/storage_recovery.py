"""Declared recovery histories and strict checks of externally observed outcomes."""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from .policy_compare import differences
from .policy_compare import dependency_errors
from .model_compare import _audit,_sha
from .reference import Reference,reference_env,verify_reference
from .storage_compare import GOLDEN,select_oracle
from .storage_reference import OWNERS
from .validate import _digest

CASES=GOLDEN.with_name('recovery-cases.json')
def recovery_cases()->dict:
    document=json.loads(CASES.read_bytes())
    names=['compact-'+p for p in ['journal_published','backup_renamed','new_published','database_committed']]+['inline-first-batch']
    if (document.get('format')!='ken-storage-recovery-cases/1' or document.get('dim')!=2
            or document.get('spaces')!=['ci_files','ci_symbols','ci_intent_sources']
            or [c['id'] for c in document.get('cases',[])]!=names):
        raise ValueError('registered five storage recovery histories required')
    return document

def expected_events(case:dict,role:str)->list[dict]:
    if role in ('recover','repeat'):return [{'recovered':True}]
    if role=='resume':return [{'phase':'migrated','space':'ci_files','count':1},{'recovered':True}]
    if case['operation']=='inline':return [{'phase':'migrated','space':'ci_files','count':1}]
    events=[{'phase':'compacted','space':space,'before':5,'after':2} for space in ['ci_files','ci_symbols','ci_intent_sources']]
    for phase in ['staging_ready','journal_published','backup_renamed','new_published','database_committed']:
        events.append({'phase':phase})
        if phase==case['barrier']:return events
    raise ValueError('unknown recovery barrier')

def recovery_receipt_errors(row:dict)->list[str]:
    try:
        document=recovery_cases();errors=[]
        if (row.get('format')!='ken-storage-recovery/1' or row.get('passed') is not True
                or row.get('errors')!=[] or row.get('M2_accepted') is not False
                or row.get('outside_checkout') is not True or row.get('native_children')!=[]
                or row.get('dependency_audit',{}).get('passed') is not True
                or row.get('dependency_audit',{}).get('errors')!=[]):errors.append('incomplete storage recovery process proof')
        expected=select_oracle(json.loads(GOLDEN.read_bytes()),row['platform'],row['architecture'])
        errors+=differences(expected['oracle'],row.get('reference_oracle'),'recovery original provenance')
        cases=row.get('cases',[])
        if not isinstance(cases,list) or [c.get('id') for c in cases]!=[c['id'] for c in document['cases']]:
            return errors+['incomplete storage recovery history coverage']
        for spec,case in zip(document['cases'],cases,strict=True):
            if set(case)!={'id','executions','before','after','final','repeat'}:
                errors.append('recovery observation fields differ');continue
            for key,state in [('before','before'),('after','after'),('final','final'),('repeat','final')]:
                errors+=differences(document['states'][spec[state]],case[key],case['id']+'.'+key)
            executions=case['executions']
            if not isinstance(executions,list) or [e.get('role') for e in executions]!=spec['roles']:
                errors.append('missing native recovery execution');continue
            for execution in executions:
                role=execution['role'];exit_code=-9 if role=='interrupted' else 0
                if (set(execution)!={'role','exit','stderr','stdout','exec_attempts'}
                        or type(execution['exit']) is not int or execution['exit']!=exit_code
                        or execution['stderr']!='' or not isinstance(execution['stdout'],str)):
                    errors.append('native recovery execution failed');continue
                events=[json.loads(line) for line in execution['stdout'].splitlines()]
                errors+=differences(expected_events(spec,role),events,case['id']+'.'+role+'.events')
                count=execution['exec_attempts']
                if row['platform']=='Linux':
                    if type(count) is not int or count!=1:errors.append('one Linux exec required for each recovery role')
                elif count is not None:errors.append('macOS recovery does not claim a traced exec count')
        return errors
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        return ['malformed storage recovery proof: '+str(error)]


def _original(reference:Reference,root:Path,out:Path,state:str,operation:str,action:str)->dict:
    request={'reference':str(reference.root),'root':str(root),'owners':list(OWNERS),'action':action,'operation':operation}
    child=Path(__file__).with_name('storage_recovery_child.py').read_text()
    result=subprocess.run([str(reference.python),'-c',child],input=json.dumps(request),text=True,capture_output=True,
                          cwd=root,env=reference_env(reference,out/'environment'/state),timeout=30)
    (out/f'original.{state}.json').write_text(result.stdout)
    (out/f'original.{state}.stderr.log').write_text(result.stderr)
    if result.returncode or result.stderr:raise ValueError('original recovery fixture failed: '+result.stderr)
    return json.loads(result.stdout)

def _invoke(driver:Path,root:Path,out:Path,role:str,phase:str,env:dict,barrier:str|None)->dict:
    command=[str(driver),str(root),phase];traced=platform.system()=='Linux'
    if traced:
        tracer=shutil.which('strace')
        if not tracer:raise ValueError('Linux recovery requires actual strace')
        command=[tracer,'-f','-e','trace=execve,execveat','-o',str(out/(role+'.trace')),*command]
    process=subprocess.Popen(command,cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    stdout=b'';stderr=b''
    try:
        if barrier is not None:
            deadline=time.monotonic()+30;selector=selectors.DefaultSelector()
            selector.register(process.stdout,selectors.EVENT_READ,'stdout');selector.register(process.stderr,selectors.EVENT_READ,'stderr')
            reached=False
            try:
                while not reached:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise ValueError('native recovery barrier timed out: '+barrier)
                    ready=selector.select(min(1,remaining))
                    for key,_ in ready:
                        raw=os.read(key.fileobj.fileno(),65536)
                        if not raw:selector.unregister(key.fileobj);continue
                        if key.data=='stdout':
                            stdout+=raw
                            complete=stdout.rsplit(b'\n',1)[0] if b'\n' in stdout else b''
                            events=[json.loads(line) for line in complete.splitlines()]
                            reached=any(isinstance(e,dict) and e.get('phase')==barrier for e in events)
                        else:stderr+=raw
                    if not reached and process.poll() is not None and not selector.get_map():raise ValueError('native recovery exited before barrier: '+barrier)
                # Only this freshly-created isolated process group is terminated.
                # Linux strace and its native child share the group, so neither remains.
                os.killpg(process.pid,signal.SIGKILL)
            finally:selector.close()
        more,errors=process.communicate(timeout=30);stdout+=more;stderr+=errors
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL);process.communicate(timeout=10)
    row={'role':role,'exit':process.returncode,'stdout':stdout.decode(),'stderr':stderr.decode(),'exec_attempts':None}
    if traced:
        lines=[line for line in (out/(role+'.trace')).read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
        if len(lines)!=1 or str(driver) not in lines[0]:raise ValueError('only initial native recovery role exec allowed')
        row['exec_attempts']=len(lines)
    (out/(role+'.stdout.log')).write_bytes(stdout);(out/(role+'.stderr.log')).write_bytes(stderr)
    (out/(role+'.execution.json')).write_text(json.dumps(row,indent=2)+'\n')
    return row

def verify_recovery(reference:Reference,driver:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    row={'format':'ken-storage-recovery/1','platform':platform.system(),'architecture':platform.machine(),
         'passed':False,'errors':[],'M2_accepted':False,'outside_checkout':False,'native_children':[],'cases':[]}
    try:
        if not driver.is_absolute() or not driver.is_file() or not os.access(driver,os.X_OK):raise ValueError('explicit executable native storage recovery driver required')
        with driver.open('rb') as stream:
            if stream.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):raise ValueError('native recovery executable required; interpreter scripts rejected')
        if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen recovery reference drift')
        document=recovery_cases();golden=select_oracle(json.loads(GOLDEN.read_bytes()),row['platform'],row['architecture'])
        audit=_audit(driver,out,package='ken-store');checks=dependency_errors((out/'dependencies.log').read_text(),row['platform'])
        audit.update(passed=audit['passed'] and not checks,errors=checks);row['dependency_audit']=audit
        if not audit['passed']:raise ValueError('native recovery dependency audit failed')
        source=[r for r in json.loads(reference.manifest_path.read_bytes())['files'] if r['path'].startswith('src/ken/')]
        row.update(driver_sha256=_sha(driver),cases_sha256=_sha(CASES),reference_fingerprint=reference.fingerprint,
                   reference_source_fingerprint=_digest(source))
        with tempfile.TemporaryDirectory(prefix='ken-storage-recovery-process-') as directory:
            sandbox=Path(directory);copied=sandbox/'storage-recovery-driver';shutil.copy2(driver,copied)
            sentinels=sandbox/'sentinel-path';sentinels.mkdir();children=sandbox/'children.log'
            for name in ['python','python3','ken','sh','bash','zsh']:
                path=sentinels/name;path.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(children))}\nexit 97\n");path.chmod(0o755)
            env={'PATH':str(sentinels),'HOME':str(sandbox)}
            for index,spec in enumerate(document['cases']):
                root=sandbox/str(index);root.mkdir();folder=out/spec['id'];folder.mkdir()
                before=_original(reference,root,folder,'before',spec['operation'],'seed')
                if differences(golden['oracle'],before['oracle']):raise ValueError('original recovery runtime/owner provenance changed')
                row['reference_oracle']=before['oracle']
                executions=[_invoke(copied,root,folder,'interrupted',spec['barrier'],env,spec['barrier'])]
                executions.append(_invoke(copied,root,folder,'recover','recover',env,None))
                after=_original(reference,root,folder,'after',spec['operation'],'read')
                if 'resume' in spec['roles']:executions.append(_invoke(copied,root,folder,'resume','migrate_resume',env,None))
                final=_original(reference,root,folder,'final',spec['operation'],'read')
                executions.append(_invoke(copied,root,folder,'repeat','recover',env,None))
                repeat=_original(reference,root,folder,'repeat',spec['operation'],'read')
                if any(differences(before['oracle'],snapshot['oracle']) for snapshot in [after,final,repeat]):raise ValueError('original recovery snapshot provenance drift')
                row['cases'].append({'id':spec['id'],'executions':executions,'before':before['data'],'after':after['data'],'final':final['data'],'repeat':repeat['data']})
            row.update(outside_checkout=True,native_children=children.read_text().splitlines() if children.exists() else [])
            if _sha(copied)!=row['driver_sha256'] or _sha(driver)!=row['driver_sha256']:raise ValueError('recovery executable changed')
        if _sha(CASES)!=row['cases_sha256'] or verify_reference(reference.root,reference.manifest_path):raise ValueError('recovery inputs/reference changed')
        row['passed']=True;row['errors'].extend(recovery_receipt_errors(row))
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,subprocess.SubprocessError) as error:
        row['errors'].append(str(error))
    row['passed']=not row['errors']
    (out/'summary.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
    return row

"""Actual lint execution and completion evidence shared by native capabilities."""
from __future__ import annotations
import json,re,subprocess
from pathlib import Path
from .native_json import identity,load

def run_command_gates(gates:Path,commands:dict[str,list[str]],*,record_name:str="COMMANDS.json",cwd:Path|None=None):
    """Preserve actual command exits and log identities before propagating failure."""
    if not commands:raise ValueError("nonempty command gates required")
    records={}
    for name,command in commands.items():
        path=gates/(name+'.log')
        with path.open('wb')as stream:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=False,cwd=cwd)
        records[name]=dict(command=command,exit=result.returncode,log=identity(path))
        if cwd is not None:records[name]['cwd']=str(Path(cwd).resolve())
        (gates/record_name).write_text(json.dumps(records,indent=2)+'\n')
        if result.returncode:raise RuntimeError(name+' gate failed; actual command receipt preserved')

def command_gate_errors(gates:Path,commands:dict[str,list[str]],*,record_name:str="COMMANDS.json",cwd:Path|None=None):
    try:
        records=load(gates/record_name)
        if not commands or set(records)!=set(commands):raise ValueError('command inventory missing')
        for name,command in commands.items():
            row=records[name]
            fields={'command','exit','log'}|({'cwd'}if cwd is not None else set())
            if not(set(row)==fields and row['command']==command and type(row['exit'])is int and row['exit']==0 and row['log']==identity(gates/(name+'.log'))):raise ValueError('command execution/log differs')
            if cwd is not None and row['cwd']!=str(Path(cwd).resolve()):raise ValueError('command working directory differs')
        return[]
    except(OSError,KeyError,TypeError,ValueError)as error:return[str(error)]

def run_lint_gates(gates:Path,commands:dict[str,list[str]]):
    run_command_gates(gates,commands,record_name='LINT.json')

def lint_gate_errors(gates:Path,commands:dict[str,list[str]]):
    errors=command_gate_errors(gates,commands,record_name='LINT.json')
    if errors:return errors
    try:
        lines=(gates/'clippy.log').read_text().splitlines()
        if(gates/'fmt.log').read_bytes()!=b''or'error:'in(gates/'clippy.log').read_text():raise ValueError('format/lint failed')
        if not(lines and re.fullmatch(r'\s*Finished `dev` profile .*target\(s\) in \S+',lines[-1])):raise ValueError('clippy completion missing')
        return[]
    except(OSError,ValueError)as error:return[str(error)]

def python_scope_commands(executable:str,files:list[str],out:Path):
    command=[executable,'-m','pytest','-o','addopts=','-q',*files]
    return{'python-list':[*command,'--collect-only'],'python-tests':[*command,'--junitxml='+str(out/'gates/python.xml')]}

def run_python_scope(out:Path,files:list[str],*,cwd:Path|None=None):
    import sys
    (out/'PYTHON-OUTPUT.json').write_text(json.dumps(dict(format='ken-native-python-scope/1',recorded_directory=str(out.resolve())),indent=2)+'\n')
    run_command_gates(out/'gates',python_scope_commands(sys.executable,files,out.resolve()),record_name='PYTHON.json',cwd=cwd)

def python_scope_errors(out:Path,files:list[str],count:int,*,cwd:Path|None=None):
    from .receipts import junit_states
    try:
        record=load(out/'PYTHON-OUTPUT.json');recorded=Path(record['recorded_directory'])
        if(set(record)!={'format','recorded_directory'}or record['format']!='ken-native-python-scope/1'or not recorded.is_absolute()or'..'in recorded.parts or recorded.name!=out.name):raise ValueError('scoped Python output differs')
        records=load(out/'gates/PYTHON.json')
        if set(records)!={'python-list','python-tests'}:raise ValueError('scoped Python commands missing')
        executable=records['python-list']['command'][0]
        if Path(executable).name not in('python','python3','python3.12'):raise ValueError('scoped Python executable differs')
        errors=command_gate_errors(out/'gates',python_scope_commands(executable,files,recorded),record_name='PYTHON.json',cwd=cwd)
        if errors:return errors
        nodes=[]
        for line in(out/'gates/python-list.log').read_text().splitlines():
            for file in files:
                if line.startswith(file+'::'):nodes.append(line.replace(file,file[:-3].replace('/','.')))
        states=junit_states(out/'gates/python.xml')
        if len(nodes)!=len(set(nodes))or len(nodes)!=count or set(nodes)!=set(states)or set(states.values())!={'passed'}:raise ValueError('scoped Python discovery/completion differs')
        return[]
    except(OSError,KeyError,ValueError,TypeError,IndexError)as error:return[str(error)]

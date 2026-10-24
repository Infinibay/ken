"""Actual lint execution and completion evidence shared by native capabilities."""
from __future__ import annotations
import json,re,subprocess
from pathlib import Path
from .native_json import identity,load

def run_command_gates(gates:Path,commands:dict[str,list[str]],*,record_name:str="COMMANDS.json"):
    """Preserve actual command exits and log identities before propagating failure."""
    if not commands:raise ValueError("nonempty command gates required")
    records={}
    for name,command in commands.items():
        path=gates/(name+'.log')
        with path.open('wb')as stream:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=False)
        records[name]=dict(command=command,exit=result.returncode,log=identity(path))
        (gates/record_name).write_text(json.dumps(records,indent=2)+'\n')
        if result.returncode:raise RuntimeError(name+' gate failed; actual command receipt preserved')

def command_gate_errors(gates:Path,commands:dict[str,list[str]],*,record_name:str="COMMANDS.json"):
    try:
        records=load(gates/record_name)
        if not commands or set(records)!=set(commands):raise ValueError('command inventory missing')
        for name,command in commands.items():
            row=records[name]
            if not(set(row)=={'command','exit','log'}and row['command']==command and type(row['exit'])is int and row['exit']==0 and row['log']==identity(gates/(name+'.log'))):raise ValueError('command execution/log differs')
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

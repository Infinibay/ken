"""Select the registered backend closure for one exact native target."""
from .native_platform import native_target

def transformer_cores(registry:dict,system:str,machine:str)->list[dict]:
    target=native_target(system,machine)
    if registry.get('format')!='ken-native-transformer-cores/1'or not isinstance(registry.get('cores'),list):
        raise ValueError('versioned transformer core registration required')
    if any(not isinstance(row,dict)for row in registry['cores']):raise ValueError('invalid transformer core record')
    rows=[row for row in registry['cores']if(row.get('os'),row.get('arch'))==target]
    backends=[row.get('backend')for row in rows]
    if not rows or any(backend not in('torch','mlx')for backend in backends)or len(set(backends))!=len(backends):
        raise ValueError('ambiguous or missing transformer runtime platform')
    if target[0]!='macos'and'mlx'in backends:raise ValueError('MLX runtime requires macOS')
    return rows

def transformer_core(registry:dict,system:str,machine:str,backend:str)->dict:
    rows=[row for row in transformer_cores(registry,system,machine)if row['backend']==backend]
    if len(rows)!=1:raise ValueError('ambiguous or missing transformer runtime backend')
    return rows[0]

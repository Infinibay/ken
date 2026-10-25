"""Run independent model profiles while preserving every failed dependency."""
from collections.abc import Callable,Mapping
DEPENDENCIES={'context':(),'ettin':(),'views':('ettin',),'preferences':('views',)}
def run_profiles(profiles:Mapping[str,Callable[[],None]])->dict:
    if set(profiles)!=set(DEPENDENCIES):raise ValueError('complete named symbol profiles required')
    states={}
    for name,dependencies in DEPENDENCIES.items():
        missing=[key for key in dependencies if states[key]['state']!='passed']
        if missing:
            states[name]=dict(state='skipped',dependencies=missing);continue
        try:profiles[name]()
        except Exception as error:states[name]=dict(state='failed',error=type(error).__name__+': '+str(error))
        else:states[name]=dict(state='passed')
    return states

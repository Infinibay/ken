"""Run independent model profiles while preserving every failed dependency."""
from collections.abc import Callable,Mapping
DEPENDENCIES={'context':(),'ettin':(),'views':('ettin',),'preferences':('views',)}
def run_profiles(profiles:Mapping[str,Callable[[],None]],*,dependencies:Mapping[str,tuple[str,...]]|None=None)->dict:
    graph=DEPENDENCIES if dependencies is None else dependencies
    seen=set()
    for name,parents in graph.items():
        if any(parent not in seen for parent in parents):raise ValueError("dependencies must precede their consumers")
        seen.add(name)
    if set(profiles)!=set(graph):raise ValueError('complete named symbol profiles required')
    states={}
    for name,dependencies in graph.items():
        missing=[key for key in dependencies if states[key]['state']!='passed']
        if missing:
            states[name]=dict(state='skipped',dependencies=missing);continue
        try:profiles[name]()
        except Exception as error:states[name]=dict(state='failed',error=type(error).__name__+': '+str(error))
        else:states[name]=dict(state='passed')
    return states

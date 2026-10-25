"""Canonical identity for the native targets actually registered by Ken."""
HOST_TARGETS={
    ('Darwin','arm64'):('macos','aarch64'),
    ('Linux','aarch64'):('linux','aarch64'),
    ('Linux','x86_64'):('linux','x86_64'),
}

def native_target(system:str,machine:str)->tuple[str,str]:
    """Resolve an observed Python host or an already canonical native target."""
    target=HOST_TARGETS.get((system,machine))
    if target is None and(system,machine)in HOST_TARGETS.values():target=(system,machine)
    if target is None:raise ValueError('unregistered native runtime platform')
    return target

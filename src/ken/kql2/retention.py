"""Admit a source revision before falling back to disposable working storage."""

from ken.structural_store.maintenance import trim


def retain_unit(store, key, ir, source_hash, frontend, *, reclaim=True):
    """Retry one allocation after reclaiming unleased cache data.

    A full but in-budget database otherwise never triggers trim and every new
    request reparses into an ephemeral store. Staged units and reader leases
    remain protected; a working set that still cannot fit retains the fallback.
    """
    try:
        return store.put_unit(key, ir, source_hash, frontend)
    except MemoryError:
        if not reclaim:
            # Cheap projections should use disposable work storage rather than
            # spend their request budget evicting a much larger semantic graph.
            raise
        reclaimed = trim(store, pressure=True)
        if reclaimed["deferred"]:
            raise
        return store.put_unit(key, ir, source_hash, frontend)

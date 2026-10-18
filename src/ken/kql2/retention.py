"""Admit a source revision before falling back to disposable working storage."""

from ken.structural_store.maintenance import trim


def reclaim_before_reader(root, budget):
    """Reclaim old, unleased cache data before a building reader blocks GC."""
    from ken.structural_store import Store
    from ken.structural_store.acquisition import AcquisitionLock
    from ken.structural_store.store import MIN_PERSISTENT_MB

    database = root / '.ken/structural/v2/store.sqlite'
    disk_budget = budget - min(budget / 5, 100)
    if not database.is_file() or disk_budget < MIN_PERSISTENT_MB:
        return
    acquisition = AcquisitionLock(database, enabled=True)
    try:
        with Store(database, cache_mb=disk_budget) as store:
            trim(store)
    finally:
        acquisition.close()


def retain_unit(store, key, ir, source_hash, frontend, *, reclaim=True):
    """Retry one allocation after reclaiming unleased cache data.

    A full but in-budget database otherwise never triggers trim and every new
    request reparses into an ephemeral store. Staged units and reader leases
    remain protected; a working set that still cannot fit retains the fallback.
    """
    try:
        return store.put_unit(key, ir, source_hash, frontend, include_syntax=False)
    except MemoryError:
        if not reclaim:
            # Cheap projections should use disposable work storage rather than
            # spend their request budget evicting a much larger semantic graph.
            raise
        reclaimed = trim(store, pressure=True)
        if reclaimed["deferred"]:
            raise
        return store.put_unit(key, ir, source_hash, frontend, include_syntax=False)

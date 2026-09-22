from ken.structural.model import IR, Entity
from ken.structural_store import Store
from ken.structural_store.leases import collect
from ken.structural_store.maintenance import trim
from ken.structural_store.store import MIN_PERSISTENT_MB

QUOTA = int(MIN_PERSISTENT_MB * 1_000_000)


def populate(store, key='a'):
    ir=IR(key,'python',entities={f'{key}{i}':Entity(f'{key}{i}','CLASS',f'Class{i}',key,1,1) for i in range(1500)})
    unit=store.put_unit(key,ir,key,'v')
    return store.publish([unit],expected_parent=store.current)


def test_lowered_quota_reclaims_old_unpinned_cache(tmp_path):
    path=tmp_path/'s.db'
    with Store(path) as store:
        populate(store)
        assert store.allocated_bytes > QUOTA
    with Store(path,cache_mb=MIN_PERSISTENT_MB) as store:
        result=trim(store)
        assert result['snapshots'] == result['units'] == 1
        assert result['after_bytes'] < result['before_bytes']
        assert result['after_bytes'] <= QUOTA
        assert store.current is None
        populate_small=IR('b','python')
        unit=store.put_unit('b',populate_small,'h','v')
        store.publish([unit],expected_parent=None)


def test_pressure_preserves_active_reader_snapshot(tmp_path):
    path=tmp_path/'s.db'
    with Store(path) as reader:
        snapshot=populate(reader)
        with Store(path,cache_mb=MIN_PERSISTENT_MB) as collector:
            result=trim(collector)
            assert result['snapshots'] == result['units'] == 0
            assert len(list(reader.scan(snapshot))) == 1500
            assert result['after_bytes'] > QUOTA


def test_pressure_defers_for_unpublished_acquisition(tmp_path):
    path=tmp_path/'s.db'
    with Store(path) as builder:
        builder.put_unit('a',IR('a','python'),'h','v')
        with Store(path) as collector:
            collector.limit_bytes=1
            assert trim(collector)['deferred'] is True
            assert builder.find_unit('a') is not None


def test_regular_gc_can_free_pages_when_existing_db_exceeds_new_quota(tmp_path):
    path=tmp_path/'s.db'
    with Store(path) as store:
        populate(store)
    with Store(path) as store:
        populate(store,'b')
    with Store(path,cache_mb=MIN_PERSISTENT_MB) as store:
        # Reclamation must not roll back because allocated pages still include
        # the freelist. Ordinary insert transactions continue enforcing quota.
        result=collect(store,retain=1)
        assert result['snapshots'] == result['units'] == 1


def test_new_revision_reclaims_old_cache_before_ephemeral_fallback(tmp_path):
    from ken.kql2.retention import retain_unit
    path = tmp_path / 's.db'
    with Store(path) as previous:
        populate(previous)
        capacity = previous.allocated_bytes + 32_768
    with Store(path, cache_mb=capacity / 1_000_000) as store:
        new = IR('b', 'python', entities={f'b{i}': Entity(f'b{i}', 'CLASS', f'New{i}', 'b', 1, 1) for i in range(1000)})
        unit = retain_unit(store, 'new', new, 'h', 'v')
        assert store.find_unit('a') is None
        assert store.allocated_bytes <= capacity
        store.publish([unit], expected_parent=store.current)
    with Store(path, cache_mb=capacity / 1_000_000) as warm:
        assert warm.find_unit('new') == unit


def test_admission_never_discards_an_active_readers_facts(tmp_path):
    import pytest
    from ken.kql2.retention import retain_unit
    path = tmp_path / 's.db'
    with Store(path) as reader:
        snapshot = populate(reader)
        capacity = reader.allocated_bytes
        with Store(path, cache_mb=capacity / 1_000_000) as writer:
            new = IR('b', 'python', entities={f'b{i}': Entity(f'b{i}', 'CLASS', f'New{i}', 'b', 1, 1) for i in range(1000)})
            with pytest.raises(MemoryError):
                retain_unit(writer, 'new', new, 'h', 'v')
        assert len(list(reader.scan(snapshot))) == 1500

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Event

import pytest

from ken.kql2.cache import ArtifactCache, retained_size
from ken.kql2 import parse


def test_caches_immutable_ast_and_counts_slots():
    cache=ArtifactCache(1_000_000)
    tree=parse('language "kql/2"; module m; query q { select 1; }')
    assert retained_size(tree) > 500
    value,state=cache.get_or_compute('key',lambda:tree)
    assert value is tree and state=='miss'
    assert cache.get_or_compute('key',lambda:None)==(tree,'hit')
    assert cache.stats()['retained_bytes'] > retained_size(tree)


def test_eviction_is_lru_and_shrink_immediate():
    cache=ArtifactCache(10000)
    a=cache.get_or_compute('a',lambda:'a'*1000)[0]
    size=cache.stats()['retained_bytes']
    cache.configure(size*2)
    cache.get_or_compute('b',lambda:'b'*1000)
    cache.get_or_compute('a',lambda:None)
    cache.get_or_compute('c',lambda:'c'*1000)
    assert cache.stats()['entries']==2
    assert cache.get_or_compute('a',lambda:None)==(a,'hit')
    assert cache.get_or_compute('b',lambda:'new')[1]=='miss'
    cache.configure(1)
    assert cache.stats()['entries']==cache.stats()['retained_bytes']==0


def test_oversize_and_disabled_are_not_retained():
    cache=ArtifactCache(4)
    for _ in range(2):
        assert cache.get_or_compute('a',lambda:'x'*100)[1]=='miss'
    cache.configure(0)
    assert cache.get_or_compute('a',lambda:'new')[1]=='disabled'
    assert cache.stats()['entries']==0


def test_exception_not_memoized():
    cache=ArtifactCache(10000)
    def fail():
        raise ValueError('invalid query')
    with pytest.raises(ValueError):
        cache.get_or_compute('a',fail)
    assert cache.get_or_compute('a',lambda:'valid')==('valid','miss')


def test_single_flight_parallel_and_failure():
    for failing in (False,True):
        cache=ArtifactCache(10000)
        started, release = Event(), Event()
        calls=[]
        def compute():
            calls.append(1)
            started.set()
            assert release.wait(3)
            if failing:
                raise ValueError('compile failed')
            return 'compiled'
        with ThreadPoolExecutor(max_workers=8) as pool:
            leader=pool.submit(cache.get_or_compute,'q',compute)
            assert started.wait(3)
            # Followers synchronize at a barrier, then wait for the same flight.
            barrier=Barrier(7)
            def follower():
                barrier.wait(timeout=3)
                return cache.get_or_compute('q',compute)
            followers=[pool.submit(follower) for _ in range(7)]
            release.set()
            for f in [leader,*followers]:
                if failing:
                    with pytest.raises(ValueError):
                        f.result(timeout=3)
                else:
                    assert f.result(timeout=3)[0]=='compiled'
        if not failing:
            assert len(calls)==1
        assert cache.stats()['in_flight']==0


def test_clear_during_compilation_does_not_retain_stale_result():
    cache=ArtifactCache(10000)
    started,release=Event(),Event()
    def compute():
        started.set()
        assert release.wait(3)
        return 'old'
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(cache.get_or_compute,'q',compute)
        assert started.wait(3)
        cache.clear()
        release.set()
        assert pending.result()[0]=='old'
    assert cache.stats()['entries']==0
    assert cache.get_or_compute('q',lambda:'new')==('new','miss')


def test_object_graph_cycles_and_shared_references():
    x=[]
    x.append(x)
    assert retained_size(x)>0
    value='x'*1000
    assert retained_size([value,value]) < 1500

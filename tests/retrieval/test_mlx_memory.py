import pytest


@pytest.mark.parametrize("prior_mib", [0, 128, 512, 32768])
def test_local_model_caps_free_cache_and_respects_a_lower_host_limit(prior_mib):
    from ken.embedder.mlx_backend import bound_free_cache
    class Runtime:
        limit = prior_mib * 1024**2
        def set_cache_limit(self, limit):
            previous, self.limit = self.limit, limit
            return previous
    runtime = Runtime()
    bound_free_cache(runtime)
    assert runtime.limit == min(prior_mib, 512) * 1024**2

from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import resource
import sys
import ken
import ken.embedder.model2vec_backend as static
from ken.retrieval.best_resources import default_resources

package = Path(ken.__file__)
assert package.is_relative_to('/Users/andres/.local/share/uv/tools/ken-rank/')
digest = hashlib.sha256(Path(static.__file__).read_bytes()).hexdigest()
assert digest == 'df930906f6d381dd634b57c99c1a3c8043d7a687d686b6d4252abab981284b79'
import ken.retrieval.source_locator as loc
locator_digest = hashlib.sha256(Path(loc.__file__).read_bytes()).hexdigest()
assert locator_digest == '9f8d19888af89eb9d58cd619bff426893796b53dfdd69d691f62c4d4b7478ba4'
assert loc.symbol_locator('Locate the definition of reader::Reader.read_value.').qualname == 'Reader.read_value'
r = default_resources()
v = r.words.embed_query('find a stored value')
expanded = r.owner_ranker.prepare_query('¿Dónde se valida un valor?')
c = r.context.embed_query('find a stored value')
scores, _ = r.neural.score('find a stored value', ['def get(key): return values[key]'])
assert len(v) == 256 and len(c) == 768 and scores == [5.957465648651123]
assert list(r.context.providers) == list(r.neural.providers) == ['CPUExecutionProvider']
assert not set(sys.modules).intersection({'torch', 'transformers', 'sentence_transformers'})
direct_url = json.loads(metadata.distribution('ken-rank').read_text('direct_url.json'))
assert 'dir_info' not in direct_url
wheel = Path('/private/tmp/ken-best-default-11b0fd6/ken_rank-0.17.0-py3-none-any.whl')
receipt = {'status': 'VERIFIED_GLOBAL_NONEDITABLE_DEFAULT_WITH_QUALIFIED_IDENTITY',
    'source_commit': '11b0fd625999bc72cb613bfc94883e649e26b19e',
    'package_version': metadata.version('ken-rank'), 'package_file': str(package),
    'direct_url': direct_url, 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'wheel_bytes': wheel.stat().st_size, 'static_backend_sha256': digest, 'source_locator_sha256': locator_digest,
    'embedding_dimensions': len(v), 'context_dimensions': len(c), 'neural_scores': scores,
    'translation_sample': expanded, 'context_providers': r.context.providers,
    'neural_providers': r.neural.providers, 'heavy_imports': [],
    'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'private_source_or_queries': False, 'release_or_tag': False,
    'mcp_existing_process_restarted': False}
out = Path('/Users/andres/Projects/ken/output/uv-tool-best-default-install-v176.json')
out.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))

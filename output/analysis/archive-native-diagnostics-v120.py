"""Back up closed owned diagnostics; never private acceptance or foreign source."""
from pathlib import Path
from datetime import datetime, timezone
import gzip
import hashlib
import json

root = Path.cwd()
out = root / 'output/checkpoints/native-ranking-diagnostics-v120'
out.mkdir(exist_ok=False)
directories = [
    'output/development/verifiable-lexical-scope-v114',
    'output/development/verifiable-lexical-scope-blind-v114',
    'output/development/verifiable-lexical-scope-reuse-v114',
    'output/development/verifiable-lexical-scope-judgments-v114-extra',
    'output/development/verifiable-lexical-scope-report-v114',
    'output/development/verifiable-scope-composition-v116',
    'output/development/verifiable-scope-composition-blind-v116',
    'output/development/verifiable-scope-composition-reuse-v116',
    'output/development/verifiable-scope-composition-judgments-v116-extra',
    'output/development/verifiable-scope-composition-report-v116',
    'output/development/verifiable-lateon-control-v115',
    'output/development/native-ranking-diagnostics-owned-v120',
    'output/development/native-ranking-diagnostics-owned-report-v120',
    'output/analysis/owned-ranking-diagnostics-v120',
    'output/frozen/verifiable-lexical-scope-v114',
    'output/frozen/verifiable-scope-composition-v116',
    'output/frozen/verifiable-lateon-control-v115',
]
suffixes = {'.json', '.jsonl', '.py', '.md', '.log', '.toml'}
files = set()
for relative in directories:
    folder = root / relative
    if not folder.exists():
        # Historical v114 directory names differ; require the manifest below
        # to record only actually found artifacts, never invent a payload.
        continue
    files.update(p for p in folder.rglob('*') if p.is_file() and p.suffix in suffixes
                 and '__pycache__' not in p.parts and '.mypy_cache' not in p.parts)
clean = root / 'output/frozen/ranking-diagnostics-owned-v120'
manifest = json.loads((clean / 'SOURCE-MANIFEST.json').read_text())
base_git_files = []
for relative, expected in manifest['files'].items():
    p = clean / relative
    assert hashlib.sha256(p.read_bytes()).hexdigest() == expected
    if p.suffix in suffixes:
        files.add(p)
    else:
        # The original Git export already contains this tracked binary/text
        # asset. Record its exact hash rather than duplicate model binaries.
        base_git_files.append({'path': relative, 'sha256': expected})
files.add(clean / 'SOURCE-MANIFEST.json')
files.update([Path(__file__).resolve(), root / 'output/analysis/audit-diagnostics-and-composition-v120.py'])
archive = {'scope': 'Closed exposed development and owned clean source only; no private acceptance, foreign dirty source or binary model weights',
           'created_utc': datetime.now(timezone.utc).isoformat(),
           'base_git_commit': manifest['git_commit'], 'base_git_assets': base_git_files,
           'files': []}
for path in sorted(files):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    name = digest + '.gz'
    packed = out / name
    if not packed.exists():
        packed.write_bytes(gzip.compress(data, compresslevel=6, mtime=0))
    assert hashlib.sha256(gzip.decompress(packed.read_bytes())).hexdigest() == digest
    archive['files'].append({'path': str(path.relative_to(root)), 'archive': name,
                             'bytes': len(data), 'uncompressed_sha256': digest})
(out / 'MANIFEST.json').write_text(json.dumps(archive, indent=2))
summary = {'files': len(files), 'distinct_gzip_files': len(list(out.glob('*.gz'))),
           'compressed_bytes': sum(p.stat().st_size for p in out.glob('*.gz')),
           'manifest_sha256': hashlib.sha256((out / 'MANIFEST.json').read_bytes()).hexdigest(),
           'all_archive_payloads_hash_verified': True}
(out / 'VERIFIED.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary), flush=True)

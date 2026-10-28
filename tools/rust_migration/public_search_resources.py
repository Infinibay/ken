"""Describe and copy authenticated data inputs for the public native caller."""
from pathlib import Path, PurePosixPath
import json
import shutil

from .grammar_prepare import _manifest
from .native_json import identity, load, same_value
from .translation_cpu_build import verify_build

MODELS = (
    ('potion-code-16M-v2', 'KEN_POTION_SOURCE'),
    ('code-context-int8', 'KEN_CONTEXT_SNAPSHOT'),
    ('ettin-68m-fp32', 'KEN_ETTIN_SOURCE'),
    ('es-en-ct2-int8', 'KEN_TRANSLATION_SOURCE'),
)


def relative(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('unsafe public resource destination')
    return Path(name)


def plan(repo, environment):
    """Only registered source bytes enter the application resource installation."""
    repo = Path(repo)
    files, variables = {}, {}

    def source(variable):
        value = Path(environment[variable])
        if not value.is_absolute() or '..' in value.parts:
            raise ValueError('absolute public resource source required: ' + variable)
        return value

    def add(destination, path, artifact):
        relative(destination)
        if destination in files:
            raise ValueError('duplicate public resource destination')
        files[destination] = dict(source=str(path), artifact=artifact)

    for name, variable in MODELS:
        row = load(repo / 'crates/ken-models/resources' / (name + '.json'))
        row = row.get('source', row)
        root = source(variable)
        if root.name != row['revision']:
            raise ValueError('public model revision differs: ' + variable)
        destination = 'inputs/models/' + name + '/' + row['revision']
        variables[variable] = destination
        for member, artifact in row['artifacts'].items():
            add(destination + '/' + member, root / relative(member), artifact)

    registry = load(repo / 'crates/ken-models/resources/onnx-runtime-libraries.json')
    rows = [r for r in registry['libraries'] if (r['os'], r['arch']) == ('linux', 'x86_64')]
    if registry['format'] != 'ken-native-onnx/1' or len(rows) != 1:
        raise ValueError('one Linux x86 ONNX registration required')
    row = rows[0]
    destination = 'inputs/onnx/libonnxruntime.so.' + row['version']
    add(destination, source('KEN_ORT_LIBRARY'), {k: row[k] for k in ('bytes', 'sha256')})
    variables['KEN_ORT_LIBRARY'] = destination

    dense = load(repo / 'crates/ken-retrieval/resources/dense-runtime-x86_64.json')
    if (dense['format'], dense['platform']) != ('ken-dense-runtime/1', 'linux-x86_64'):
        raise ValueError('Linux x86 dense registration required')
    for name, artifact in dense['files'].items():
        add('dense-blas/' + name, source('KEN_DENSE_BLAS_DIR') / relative(name), artifact)

    lock = load(repo / 'crates/ken-syntax/grammars.lock.json')
    manifest = source('KEN_GRAMMAR_MANIFEST')
    if load(manifest) != _manifest(lock, 'linux-x86_64'):
        raise ValueError('public grammar manifest differs from lock')
    add('inputs/grammars/manifest.json', manifest, identity(manifest))
    for row in load(manifest)['libraries']:
        add('inputs/grammars/' + row['file'], manifest.parent / relative(row['file']),
            {k: row[k] for k in ('bytes', 'sha256')})
    variables['KEN_GRAMMAR_MANIFEST'] = 'inputs/grammars/manifest.json'

    ranks = repo / 'crates/ken-retrieval/resources/ranking'
    add('inputs/ranking/manifest.json', ranks / 'manifest.json', identity(ranks / 'manifest.json'))
    for row in load(ranks / 'manifest.json')['models'].values():
        add('inputs/ranking/' + row['file'], ranks / relative(row['file']),
            dict(bytes=row['compressed_bytes'], sha256=row['compressed_sha256']))
    variables['KEN_PUBLIC_RANKS'] = 'inputs/ranking'

    preparation = source('KEN_CT2_PREPARATION')
    if errors := verify_build(preparation.parent, repo, source('KEN_CT2_SDK')):
        raise ValueError('public translation build: ' + '; '.join(errors))
    built = load(preparation)
    runtime, = built['registration']['runtimes']
    module = 'inputs/ct2/libken_ct2_backend.so'
    add(module, Path(built['module_path']), runtime['module'])
    for name, artifact in runtime['libraries'].items():
        add('inputs/ct2/' + name, Path(built['core_root']) / relative(name), artifact)
    variables['KEN_CT2_PREPARATION'] = 'inputs/translation-runtime.json'
    translation = dict(registration=built['registration'], module_path=module, core_root='inputs/ct2')
    return dict(format='ken-public-search-inputs/1', files=files,
                environment=variables, translation=translation)


def stage(value, root):
    """Verify all inputs before writing, then verify independent readonly copies."""
    root = Path(root)
    for name, row in value['files'].items():
        destination = root / relative(name)
        if destination.exists() or destination.is_symlink():
            raise ValueError('public resource destination already exists')
        if identity(Path(row['source'])) != row['artifact']:
            raise ValueError('public resource bytes differ: ' + name)
    runtime = root / relative(value['environment']['KEN_CT2_PREPARATION'])
    if runtime.exists() or runtime.is_symlink():
        raise ValueError('translation input destination already exists')
    for name, row in value['files'].items():
        destination = root / relative(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Path(row['source']).open('rb') as source, destination.open('xb') as output:
            shutil.copyfileobj(source, output)
        if identity(destination) != row['artifact']:
            raise ValueError('public resource changed while copying: ' + name)
        destination.chmod(0o444)
    translation = dict(value['translation'])
    for key in ('module_path', 'core_root'):
        translation[key] = str(root / relative(translation[key]))
    runtime.write_text(json.dumps(translation, indent=2) + '\n')
    runtime.chmod(0o444)
    return {name: str(root / relative(path)) for name, path in value['environment'].items()}


def input_errors(value, repo, grammar_manifest, registration):
    """Reconstruct the data-only contract from archived registries and build proof."""
    try:
        repo, grammar_manifest = map(Path, (repo, grammar_manifest))
        expected, variables = {}, {}
        for name, variable in MODELS:
            row = load(repo / 'crates/ken-models/resources' / (name + '.json'))
            row = row.get('source', row)
            prefix = 'inputs/models/' + name + '/' + row['revision']
            variables[variable] = prefix
            expected.update({prefix + '/' + member: artifact for member, artifact in row['artifacts'].items()})
        onnx, = [r for r in load(repo / 'crates/ken-models/resources/onnx-runtime-libraries.json')['libraries']
                 if (r['os'], r['arch']) == ('linux', 'x86_64')]
        variables['KEN_ORT_LIBRARY'] = 'inputs/onnx/libonnxruntime.so.' + onnx['version']
        expected[variables['KEN_ORT_LIBRARY']] = {k: onnx[k] for k in ('bytes', 'sha256')}
        expected.update({'dense-blas/' + name: row for name, row in
                         load(repo / 'crates/ken-retrieval/resources/dense-runtime-x86_64.json')['files'].items()})
        grammar = load(grammar_manifest)
        if not same_value(grammar, _manifest(load(repo / 'crates/ken-syntax/grammars.lock.json'), 'linux-x86_64')):
            raise ValueError('retained grammar metadata differs from lock')
        variables['KEN_GRAMMAR_MANIFEST'] = 'inputs/grammars/manifest.json'
        expected[variables['KEN_GRAMMAR_MANIFEST']] = identity(grammar_manifest)
        expected.update({'inputs/grammars/' + r['file']: {k: r[k] for k in ('bytes', 'sha256')}
                         for r in grammar['libraries']})
        ranks = repo / 'crates/ken-retrieval/resources/ranking'
        variables['KEN_PUBLIC_RANKS'] = 'inputs/ranking'
        expected['inputs/ranking/manifest.json'] = identity(ranks / 'manifest.json')
        expected.update({'inputs/ranking/' + r['file']: dict(bytes=r['compressed_bytes'], sha256=r['compressed_sha256'])
                         for r in load(ranks / 'manifest.json')['models'].values()})
        runtime, = registration['runtimes']
        expected['inputs/ct2/libken_ct2_backend.so'] = runtime['module']
        expected.update({'inputs/ct2/' + name: row for name, row in runtime['libraries'].items()})
        variables['KEN_CT2_PREPARATION'] = 'inputs/translation-runtime.json'
        translation = dict(registration=registration, module_path='inputs/ct2/libken_ct2_backend.so', core_root='inputs/ct2')
        if (set(value) != {'format', 'files', 'environment', 'translation'}
                or value['format'] != 'ken-public-search-inputs/1'
                or not same_value(value['environment'], variables)
                or not same_value(value['translation'], translation)
                or set(value['files']) != set(expected)):
            raise ValueError('public resource inventory contains missing or foreign inputs')
        for name, row in value['files'].items():
            relative(name)
            if (set(row) != {'source', 'artifact'} or not Path(row['source']).is_absolute()
                    or not same_value(row['artifact'], expected[name])):
                raise ValueError('registered public resource identity differs: ' + name)
        return []
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [str(error)]

"""Adapt a frozen original graph fixture; expected vectors never come from Rust."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference
from .context_reference import capture

_BUILD = r'''
import hashlib, json, runpy, sys
from pathlib import Path
from tokenizers import Tokenizer, processors
request = json.load(sys.stdin)
helper = Path(request['reference'])/'tests/test_context_encoder.py'
module = runpy.run_path(str(helper))
snapshot, definition = module['contextual_model'].__wrapped__(Path(request['output']))
tokenizer = Tokenizer.from_file(str(snapshot/'tokenizer.json'))
assert tokenizer.add_special_tokens(['[CLS]', '[SEP]']) == 2
tokenizer.post_processor = processors.TemplateProcessing(single='[CLS] $A [SEP]',
    special_tokens=[('[CLS]',4),('[SEP]',5)])
tokenizer.enable_padding(length=64, pad_id=3, pad_token='[PAD]')
tokenizer.enable_truncation(max_length=3)
tokenizer.save(str(snapshot/'tokenizer.json'))
definition.update(query_prefix='find ', document_projection='test-source-projection')
definition['artifacts'] = {name: {'bytes': (snapshot/name).stat().st_size,
    'sha256': hashlib.sha256((snapshot/name).read_bytes()).hexdigest()}
    for name in ('onnx/model.onnx','tokenizer.json')}
print(json.dumps({'snapshot': str(snapshot), 'definition': definition,
    'helper': {'path': 'tests/test_context_encoder.py',
               'sha256': hashlib.sha256(helper.read_bytes()).hexdigest()}}))
'''


def build_fixture(reference: Reference, output: Path) -> tuple[Path, dict, dict]:
    if verify_reference(reference.root, reference.manifest_path): raise ValueError('reference source drift')
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-context-fixture-') as directory:
        sandbox = Path(directory)
        child = subprocess.run([str(reference.python), '-c', _BUILD], cwd=sandbox,
            env=reference_env(reference, sandbox), input=json.dumps({
                'reference': str(reference.root), 'output': str(output)}),
            text=True, capture_output=True, timeout=60)
    if child.returncode or child.stderr: raise ValueError(f'frozen graph fixture failed: {child.stderr}')
    if verify_reference(reference.root, reference.manifest_path): raise ValueError('reference source drift')
    value = json.loads(child.stdout)
    return Path(value['snapshot']), value['definition'], value['helper']


def fixture_cases() -> list[dict]:
    return [
        {'id': 'empty', 'prepare': False, 'calls': [{'op': 'passages', 'texts': []}]},
        {'id': 'prefix', 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': 'query', 'text': 'red'},
            {'op': 'tokens', 'kind': 'passage', 'text': 'red'},
            {'op': 'query', 'text': 'red'}, {'op': 'passages', 'texts': ['red']}]},
        {'id': 'mixed', 'prepare': True, 'calls': [
            {'op': 'passages', 'texts': ['red', '', 'red red', 'mystery']}]},
        {'id': 'policy', 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': 'query', 'text': 'red '*1000},
            {'op': 'tokens', 'kind': 'passage', 'text': 'red '*511},
            {'op': 'query', 'text': 'red '*1000}, {'op': 'passages', 'texts': ['red '*511]}]},
        {'id': 'unicode', 'prepare': True, 'calls': [
            {'op': 'passages', 'texts': ['café', 'cafe\u0301', '\x00🙂', ' \t']}]},
        {'id': 'repeat', 'prepare': True, 'calls': [
            {'op': 'query', 'text': 'red'}, {'op': 'query', 'text': 'red'}]},
    ]


def generate(reference: Reference, output: Path) -> dict:
    # This is explicit test-data preparation. Production has no ONNX Python
    # package dependency and no import/call path to this generator.
    import onnx
    from onnx import TensorProto, helper
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot, definition, provenance = build_fixture(reference, output / 'valid')
    (output / 'valid/definition.json').write_text(json.dumps(definition, indent=2)+'\n')
    capture(reference, snapshot, output / 'valid/oracle.json', definition=definition, cases=fixture_cases())
    original = onnx.load(snapshot / 'onnx/model.onnx')
    variants = {}
    bad = deepcopy(original)
    bad.graph.initializer[1].CopyFrom(helper.make_tensor('zeros', TensorProto.FLOAT, [1,765], [0.]*765))
    bad.graph.output[0].type.tensor_type.shape.dim[1].dim_value = 767
    variants['wrong-dimension'] = bad
    bad = deepcopy(original)
    bad.graph.node[-1].output[0] = 'raw'
    bad.graph.node.append(helper.make_node('Cast', ['raw'], ['sentence_embedding'], to=TensorProto.DOUBLE))
    bad.graph.output[0].type.tensor_type.elem_type = TensorProto.DOUBLE
    variants['wrong-dtype'] = bad
    bad = deepcopy(original)
    bad.graph.node[-1].output[0] = 'other'
    bad.graph.output[0].name = 'other'
    variants['wrong-output-name'] = bad
    bad = deepcopy(original)
    bad.graph.node[-1].output[0] = 'raw'
    bad.graph.node.append(helper.make_node('Concat', ['raw','raw'], ['sentence_embedding'], axis=0))
    bad.graph.output[0].type.tensor_type.shape.dim[0].dim_value = 2
    variants['extra-row'] = bad
    for name, value in [('nan', float('nan')), ('infinity', float('inf'))]:
        bad = deepcopy(original)
        bad.graph.node[-1].output[0] = 'raw'
        bad.graph.initializer.append(helper.make_tensor('nonfinite', TensorProto.FLOAT, [1,768], [value]*768))
        bad.graph.node.append(helper.make_node('Add', ['raw','nonfinite'], ['sentence_embedding']))
        variants[name] = bad
    bad = deepcopy(original)
    bad.graph.input[0].type.tensor_type.elem_type = TensorProto.FLOAT
    variants['wrong-input-dtype'] = bad
    variants['corrupt-graph'] = None
    invalid = []
    for name, graph in variants.items():
        folder = output / name
        target = folder / snapshot.name
        shutil.copytree(snapshot, target)
        path = target / 'onnx/model.onnx'
        if graph is None: path.write_bytes(b'not an ONNX graph')
        else: onnx.save(graph, path)
        registration = deepcopy(definition)
        registration['artifacts']['onnx/model.onnx'] = {
            'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (folder / 'definition.json').write_text(json.dumps(registration, indent=2)+'\n')
        accepted = True
        try:
            capture(reference, target, folder / 'original.json', definition=registration,
                    cases=[{'id': 'query', 'prepare': True, 'calls': [{'op': 'query', 'text': 'red'}]}])
        except ValueError as error:
            accepted = False
            (folder / 'original-error.txt').write_text(str(error).replace(str(target), '$SNAPSHOT')+'\n')
        if accepted != (name == 'extra-row'):
            raise ValueError(f'original graph outcome differs from intended fixture: {name}')
        invalid.append({'id': name, 'snapshot': str(target.relative_to(output)),
            'definition': f'{name}/definition.json', 'native_reject': True, 'original_accepted': accepted})
    files = [{'path': str(p.relative_to(output)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'manifest.json']
    manifest = {'format': 'ken-context-fixtures/1', 'helper': provenance,
        'valid': [{'snapshot': str(snapshot.relative_to(output)), 'definition': 'valid/definition.json',
                   'oracle': 'valid/oracle.json'}], 'invalid': invalid, 'files': files}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = generate(Reference.load(args.reference), args.out)
    print(json.dumps({'valid': len(result['valid']), 'invalid': len(result['invalid'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Capture original translation preparation and real inference in a frozen child."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .ettin_reference import source_state
from .reference import Reference, reference_env, verify_reference


def translation_cases() -> list[dict]:
    def row(name, *queries, **options):
        return {'id': name, 'queries': list(queries), **options}
    question = '¿Dónde está la función que elimina archivos?'
    rows = [row('english', 'Where are names normalized?'), row('empty', ''),
            row('repeated-one-word', 'busca busca'), row('two-distinct-words', 'busca la'),
            row('accent-aliases', 'que qué'), row('question-only', '¿'),
            row('spanish', question), row('spanish-lexicon', 'Busca la clase que contiene este método.'),
            row('protected-code', '¿Dónde se invoca `Client.send` con project_name?'),
            row('repeated-identifiers', '¿Cómo usa `Client.send` con `Client.send` y project_name?'),
            row('many-identifiers', '¿Cómo usa ' + ' y '.join(f'item_{i}' for i in range(24)) + '?'),
            row('literal-placeholder', '¿ ZXQ0QXZ y `example.value`'),
            row('long-s-casefold', 'buſca laſ clases'), row('dotted-i-casefold', 'İcómo convierte valores'),
            row('combining-boundary', 'cómo\u0301 convierte valores'),
            row('unicode', '¿Cómo convierte café y cafe\u0301 en 世界?'),
            row('emoji-nul', '¿Dónde está la clase? 👩🏽‍💻 🦀\x00世界'),
            row('newlines', '¿Cómo usa `one\ntwo`?\nBusca la clase.'),
            row('repeated-calls', question, question, question),
            row('empty-after-load', question, '', 'find the input parser')]
    for count in (511, 512, 513, 1023, 1024, 1025):
        # Characterized with original source.spm: question + repeated hola + EOS.
        rows.append(row(f'source-boundary{count}', '¿ ' + 'hola ' * (count - 2),
                        source_pieces_with_eos=count))
    rows.extend([row('error-then-english', '¿ ' + 'hola ' * 511, 'find the input parser'),
                 row('missing-assets-lazy', 'find the input parser', '', question,
                     'find the input parser', missing_assets=True),
                 row('corrupt-assets-lazy', 'find the input parser', question,
                     'find the input parser', corrupt_artifact='model.bin')])
    return rows


_CHILD = r'''
import hashlib,json,platform,resource,shutil,sys,time,unicodedata
from importlib.metadata import version
from pathlib import Path
import ken.model_assets as assets_module
import ken.retrieval.query_expansion as original
import ken.retrieval.translation_preparation as preparation
request=json.load(sys.stdin);reference=Path(request['reference']);definition=request['definition']
modules=[assets_module,original,preparation]
if any(not Path(module.__file__).resolve().is_relative_to(reference/'src') for module in modules):
 raise ValueError('original import escaped frozen tree')
source=Path(request['source']);destination=Path(request['destination'])
memory=[];observed=0
def sample(phase):
 global observed
 if sys.platform.startswith('linux'):
  raw=next(int(line.split()[1])*1024 for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:'))
 else:raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 if raw<=0:raise ValueError('missing native process peak')
 observed=max(observed,raw);memory.append({'phase':phase,'reported_hwm_bytes':raw,'observed_peak_bytes':observed})
sample('before-prepare');started=time.monotonic_ns()
preparation.prepare_translation(definition,destination,source_snapshot=source)
prepare_ns=time.monotonic_ns()-started;sample('after-prepare')
prepared_assets=assets_module.ModelAssets.from_dict(definition['derived'])
prepared_assets.verify(destination)
records={artifact.path:{'bytes':artifact.bytes,'sha256':artifact.sha256} for artifact in prepared_assets.artifacts}
rows=[];boundaries={}
for case in request['cases']:
 root=destination
 if case.get('missing_assets'):root=destination.parent/'missing'/destination.name
 if case.get('corrupt_artifact'):
  root=destination.parent/('corrupt-'+case['id'])/destination.name
  shutil.copytree(destination,root)
  path=root/case['corrupt_artifact'];data=bytearray(path.read_bytes());data[0]^=1;path.write_bytes(data)
 trace={};actual={}
 def loader(path):
  translator,source_spm,target_spm=original._load_cpu_runtime(path)
  actual.update(device=translator.device,compute_type=translator.compute_type,replicas=translator.num_translators)
  class Source:
   def encode(self,text,out_type=str):
    if out_type is not str:raise ValueError('original source encoding policy changed')
    trace['prepared']=text;trace['source_ids']=source_spm.encode(text,out_type=int)
    return source_spm.encode(text,out_type=str)
  class Translator:
   def translate_batch(self,rows,**options):
    trace['source_pieces_with_eos']=rows[0];trace['options']=options
    result=translator.translate_batch(rows,**options)
    trace['hypotheses']=result[0].hypotheses
    return result
  class Target:
   def decode(self,tokens):
    decoded=target_spm.decode(tokens);trace['decoded']=decoded;return decoded
  return Translator(),Source(),Target()
 started=time.monotonic_ns();encoder=original.LocalQueryExpansion(root,definition['derived'],load_runtime=loader)
 constructor_ns=time.monotonic_ns()-started;calls=[];sample(case['id']+'.before-calls')
 if 'source_pieces_with_eos' in case:
  import sentencepiece
  processor=sentencepiece.SentencePieceProcessor(model_file=str(destination/'source.spm'))
  count=len(processor.encode(case['queries'][0],out_type=str))+1
  if count!=case['source_pieces_with_eos']:raise ValueError(f'original source boundary mismatch: {count}')
  boundaries[case['id']]=count
 for index,query in enumerate(case['queries']):
  trace.clear();started=time.monotonic_ns();call={}
  try:call['output']=encoder(query)
  except (ValueError,RuntimeError,OSError) as error:
   call['error']={'type':type(error).__name__,'message':str(error)}
  call.update(wall_ns=time.monotonic_ns()-started,trace=dict(trace),runtime_loaded=encoder._runtime is not None)
  calls.append(call);sample(case['id']+f'.after-call{index}')
 rows.append({'id':case['id'],'calls':calls,'constructor_ns':constructor_ns,
  'identity':encoder.identity,'revision':encoder.revision,'actual_runtime':dict(actual)})
result={'format':'ken-translation-oracle/1','platform':platform.system(),'architecture':platform.machine(),
 'oracle':{'frozen_import':True,'runtime':{name:version(name) for name in ('ctranslate2','sentencepiece')},
  'unicode':unicodedata.unidata_version,
  'module_hashes':{module.__name__:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules}},
 'definition':definition,'cases':request['cases'],'results':rows,'prepared_artifacts':records,
 'recipe_sha256':hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest(),
 'prepare_ns':prepare_ns,'memory_samples':memory,'boundary_characterization':boundaries}
print(json.dumps(result,ensure_ascii=True,allow_nan=False))
'''


def capture(reference: Reference, source: Path, output: Path, *, cases: list[dict] | None = None,
            definition: dict | None = None) -> dict:
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    if definition is None:
        definition = json.loads((reference.root / 'src/ken/embedder/data/es-en-ct2-int8.json').read_text())
    source = source.resolve()
    before = source_state(source, definition['source'])
    cases = translation_cases() if cases is None else cases
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('distinct nonempty translation histories required')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-translation-original-') as directory:
        root = Path(directory)
        request = {'reference': str(reference.root), 'definition': definition, 'source': str(source),
                   'destination': str(root / 'prepared' / definition['derived']['revision']), 'cases': cases}
        child = subprocess.run([str(reference.python), '-c', _CHILD], cwd=root,
                               env=reference_env(reference, root / 'environment'), input=json.dumps(request),
                               text=True, capture_output=True, timeout=600)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode or child.stderr:
        raise ValueError(f'frozen translation capture failed: {child.stderr}')
    if source_state(source, definition['source']) != before:
        raise ValueError('source artifacts changed during capture')
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    result = json.loads(child.stdout)
    result.update(source_artifacts=before, reference_fingerprint=reference.fingerprint)
    result['oracle']['stderr'] = child.stderr
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + '\n')
    return result

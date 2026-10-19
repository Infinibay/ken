"""Characterize frozen Python lexical behavior independently of the Rust port."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

_CHILD = r'''
import hashlib,json,re,sys,tempfile,unicodedata
from pathlib import Path
from types import SimpleNamespace
import ken.retrieval.query_expansion as original
reference=Path(sys.argv[1]);mode=sys.argv[2]
module=Path(original.__file__).resolve()
if not module.is_relative_to(reference/'src'):raise ValueError('original import escaped frozen tree')
if unicodedata.unidata_version!='15.0.0':raise ValueError('original Unicode15.0.0 required')
common={'unicode':unicodedata.unidata_version,'source_sha256':hashlib.sha256(module.read_bytes()).hexdigest()}
if mode=='unicode':
 tables={'word':[],'decimal':[],'whitespace':[],'casefold':[]};digest=hashlib.sha256()
 def add_range(name,number):
  rows=tables[name]
  if rows and rows[-1][1]+1==number:rows[-1][1]=number
  else:rows.append([number,number])
 for number in range(0x110000):
  if 0xd800<=number<=0xdfff:continue
  char=chr(number);fold=char.casefold();encoded=fold.encode('utf-8')
  word=char.isalnum() or char=='_';decimal=char.isdecimal();space=char.isspace()
  assert word==bool(re.fullmatch(r'\w',char))
  assert decimal==bool(re.fullmatch(r'\d',char))
  assert space==bool(re.fullmatch(r'\s',char))
  flags=word|(decimal<<1)|(space<<2)
  digest.update(number.to_bytes(4,'big')+bytes((flags,len(encoded)))+encoded)
  for name,enabled in [('word',word),('decimal',decimal),('whitespace',space)]:
   if enabled:add_range(name,number)
  if fold!=char:tables['casefold'].append([number,fold])
 result=common|{'scope':'original-unicode-scalar-characterization','tables':tables,
  'digest':digest.hexdigest(),'regex_predicates_verified':True,
  'digest_encoding':'scalar-u32be,flags-u8(word|decimal<<1|space<<2),fold-utf8-length-u8,fold-utf8;ascending-scalars'}
elif mode=='policy':
 fixed=['','busca busca','busca la','que qué','Where are names normalized?',
  'buſca laſ','İcómo convierte','cómo\u0301 convierte','cómo\u200cconvierte',
  'cómo\u203fconvierte','cómo\u0661 convierte','¿','BUSCA LAS',
  '¿Dónde se invoca `Client.send` con project_name?',
  '¿ `one\ntwo` `` `three` a.b.c::d a_1 a_١ $one.two one.$two one.two$ x$one.two',
  '¿ '+' '.join(f'item_{i}' for i in range(24)),
  '¿ ZXQ0QXZ and `example.value`','¿ a.b\u0301c 𐐀a.b a.𐐀 a.\u2160 a_² a_١']
 parts=['a.b','a::b','a..b','a.:b','a_1','a_١','a_²','one.$two','$one.two','a.b$',
  'a.b$c','`a.b`','``','`a\nb`','a_','_a','a_.b','a.b_c','a.\u0301b','a.\u200cb']
 neighbors=['','a','_','$',' ','\n','\u0301','\u200c','\u203f','\u2160','𐐀']
 queries=fixed+[f'¿ {left}{part}{right}' for part in parts for left in neighbors for right in neighbors]
 rows=[]
 for query in queries:
  words=set(re.findall(r'\w+',query.casefold()))
  needed='¿' in query or len(words&original._SPANISH)>=2
  protected=[]
  def replace(match):
   protected.append(match[0]);return f'ZXQ{len(protected)-1}QXZ'
  prepared=original._PROTECTED.sub(replace,query) if needed else query
  rows.append({'query':query,'needs_translation':needed,'prepared':prepared,
   'protected':protected,'spanish_words':sorted(words&original._SPANISH)})
 restoration=[]
 controlled=[('spaces-and-case','¿ `Client.send` con project_name?',
  'Find Z X Q 0 Q X Z and z\x1cx\x1cq\x1c1\x1cq\x1cx\x1cz.'),
  ('multi-digit','¿ '+' '.join(f'item_{i}' for i in range(24)),
   'ZXQ0QXZ / zxq10qxz / Z X Q 2 3 Q X Z'),
  ('literal-collision','¿ ZXQ0QXZ `x.y`','ZXQ0QXZ ZXQ0QXZ'),
  ('damaged-key','¿ `x.y`','ZXQ0QX?'),
  ('replacement-literal','¿ `path\\raw.$1`','ZXQ0QXZ'),
  ('whitespace-empty','¿','\x1c\x1d\x1e\x1f \t\n')]
 with tempfile.TemporaryDirectory(prefix='original-policy-data-') as directory:
  root=Path(directory);artifacts={}
  for name in original.REQUIRED_ARTIFACTS:
   data=name.encode();(root/name).write_bytes(data)
   artifacts[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  registration={'model_id':'test/policy','revision':'a'*40,'artifacts':artifacts}
  for name,query,decoded in controlled:
   class Source:
    def encode(self,text,out_type=str):
     if out_type is not str:raise ValueError('original source encoding policy changed')
     return [text]
   class Translator:
    def translate_batch(self,rows,**options):
     if options!={'beam_size':1,'max_decoding_length':256}:raise ValueError('original decode policy changed')
     return [SimpleNamespace(hypotheses=[[decoded]])]
   class Target:
    def decode(self,tokens):return tokens[0]
   encoder=original.LocalQueryExpansion(root,registration,load_runtime=lambda path:(Translator(),Source(),Target()))
   row={'id':name,'query':query,'decoded':decoded}
   try:row['output']=encoder(query)
   except ValueError as error:row['error']=str(error)
   restoration.append(row)
 result=common|{'scope':'original-only-policy-characterization','cases':rows,'lexicon':sorted(original._SPANISH),
  'restoration_scope':'original-policy-only-controlled-decoder','restoration':restoration}
else:raise ValueError('unknown characterization mode')
print(json.dumps(result,ensure_ascii=True,allow_nan=False))
'''


def _generate(reference: Reference, output: Path, mode: str) -> dict:
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-translation-policy-') as directory:
        root = Path(directory)
        child = subprocess.run([str(reference.python), '-c', _CHILD, str(reference.root), mode],
                               cwd=root, env=reference_env(reference, root / 'environment'),
                               text=True, capture_output=True, timeout=120)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode or child.stderr:
        raise ValueError(f'frozen lexical characterization failed: {child.stderr}')
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    result = json.loads(child.stdout)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + '\n')
    return result


def generate_policy(reference: Reference, output: Path) -> dict:
    return _generate(reference, output, 'policy')


def generate_unicode(reference: Reference, output: Path) -> dict:
    return _generate(reference, output, 'unicode')

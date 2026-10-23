"""Reproduce the compiled Unicode15 compatibility data with the original Python."""
from pathlib import Path
import hashlib,json,tarfile,unicodedata
assert unicodedata.unidata_version=='15.0.0'
root=Path.cwd();archive=root/'.ken/rust-migration/m3-parsers/research/unicode_names2-1.2.0.crate'
import tomllib
package=next(p for p in tomllib.loads((root/'Cargo.lock').read_text())['package']if p['name']=='unicode_names2')
assert package['version']=='1.2.0'and hashlib.sha256(archive.read_bytes()).hexdigest()==package['checksum']
with tarfile.open(archive)as tar:
 def read(suffix):return tar.extractfile(next(m for m in tar if m.name.endswith(suffix))).read()
 data=read('/data/UnicodeData.txt');aliases=read('/data/NameAliases.txt')
 absent=[];start=None
 for line in data.decode().splitlines():
  fields=line.split(';');cp=int(fields[0],16);name=fields[1]
  if name.endswith(', First>'):start=cp;continue
  points=range(start,cp+1)if name.endswith(', Last>')and start is not None else[cp]
  absent.extend(point for point in points if unicodedata.category(chr(point))=='Cn');start=None
 ranges=[]
 for cp in absent:
  if ranges and ranges[-1][1]+1==cp:ranges[-1][1]=cp
  else:ranges.append([cp,cp])
 accepted={}
 for line in aliases.decode().splitlines():
  line=line.split('#',1)[0].strip()
  if not line:continue
  code,name,*_=line.split(';')
  try:value=unicodedata.lookup(name)
  except KeyError:continue
  if len(value)==1:accepted[name]=ord(value)
 result=dict(original_unicode='15.0.0',source_unicode='15.1.0',unicode_data_sha256=hashlib.sha256(data).hexdigest(),
  name_aliases_sha256=hashlib.sha256(aliases).hexdigest(),excluded_ranges=ranges,aliases=accepted)
 ranges=[]
 for cp in range(0x110000):
  if unicodedata.category(chr(cp))!='Nd':continue
  if ranges and ranges[-1][1]+1==cp:ranges[-1][1]=cp
  else:ranges.append([cp,cp])
 result['decimal_ranges']=ranges
 existing=json.loads((root/'crates/ken-syntax/src/python_unicode15.json').read_bytes())
 assert existing==result,'compiled Unicode compatibility data differs'
 print('Reproduced Unicode15delta:627new codepoints excluded in3ranges;473original aliases authenticated.')

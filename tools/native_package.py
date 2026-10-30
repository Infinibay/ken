"""Assemble an unqualified native candidate from authenticated existing owners.

Python is a build tool only. Installed activation, launcher and services are native.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,re,shutil,stat,subprocess,tempfile
from pathlib import Path, PurePosixPath
from tools.rust_migration import public_search_resources as resources
from tools.rust_migration.native_json import identity,load
from tools.rust_migration.native_binary import check_native_architecture

ENTRYPOINTS={'launcher':'ken','cli':'ken-rs','check_worker':'ken-check-worker','git':'git'}
COMPONENTS={'ken','rust','grammars','ranking','static','potion','context','ettin','translation','onnx','ct2','dense','elf','git'}
TARGET={'os':'linux','arch':'x86_64','device':'cpu'}

def _relative(value):
 if not isinstance(value,str) or '\\' in value or '\0' in value:raise ValueError('confined UTF8 package path required')
 return resources.relative(value)

def _record(value):
 if (not isinstance(value,dict) or type(value.get('bytes')) is not int or not 0<=value['bytes']<=16*1024**3 or not isinstance(value.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',value['sha256'])):raise ValueError('bounded SHA256 artifact identity required')
 return {key:value[key] for key in ('bytes','sha256')}

def _elf(path):
 tool=shutil.which('readelf')
 if not tool:raise ValueError('explicit build-host readelf tool is required')
 result=subprocess.run([tool,'-d','-V',str(path)],capture_output=True,text=True,check=False)
 if result.returncode:raise ValueError('cannot inspect native ELF closure: '+str(path))
 needed=re.findall(r'\(NEEDED\).*?\[([^\]]+)\]',result.stdout)
 sonames=re.findall(r'\(SONAME\).*?\[([^\]]+)\]',result.stdout)
 if any('libpython' in name.lower() or 'libtorch_python' in name.lower() for name in needed):raise ValueError('Python runtime is forbidden in native package ELF closure')
 paths={tag:re.findall(r'\('+tag+r'\).*?\[([^\]]*)\]',result.stdout) for tag in ('RPATH','RUNPATH')}
 if any('/'in name or ':'in name or not name for name in needed):raise ValueError('basename-only ELF dependencies required')
 if len(sonames)>1 or any('/'in name or ':'in name or not name for name in sonames):raise ValueError('distinct basename-only ELF SONAME required')
 return dict(needed=needed,soname=sonames[0]if sonames else None,rpath=paths['RPATH'],runpath=paths['RUNPATH'],version_requirements=sorted(set(re.findall(r'Name: ((?:GLIBC|GLIBCXX|CXXABI)_[A-Za-z0-9_.]+)',result.stdout))),inspection_sha256=hashlib.sha256(result.stdout.encode()).hexdigest())

def _loader_paths(values,logical,namespace):
 """Expand only portable ORIGIN paths inside the actual loader namespace."""
 result=[]
 for value in values:
  for member in value.split(':'):
   if member.startswith('${ORIGIN}'):suffix=member[len('${ORIGIN}'):]
   elif member.startswith('$ORIGIN'):suffix=member[len('$ORIGIN'):]
   else:raise ValueError('ELF RPATH/RUNPATH must use confined $ORIGIN: '+member)
   if suffix and not suffix.startswith('/'):raise ValueError('unsupported ELF loader token')
   parts=list(PurePosixPath(logical).parent.parts)
   for part in suffix.split('/'):
    if part in ('','.'):continue
    if part=='..':
     if not parts:raise ValueError('ELF loader path escapes its owned namespace')
     parts.pop()
    elif '$'in part or '\\'in part:raise ValueError('unsupported ELF loader path token')
    else:parts.append(part)
   result.append((namespace,'/'.join(parts)))
 return result

def _validate_elf_loader(files,measured,systems,plan,transformers):
 """Resolve dependencies in release/lib or each owner's declared private copy.

 This describes the Linux loader paths used by the launcher and native owners;
 an arbitrary staged basename is never a searchable directory.
 """
 if any(not isinstance(name,str)or Path(name).name!=name or not name for name in systems):raise ValueError('basename-only declared system libraries required')
 mappings={'release':{name:name for name in measured}};private=[]
 def private_owner(label,module,module_name,core_root,registration,deepbind=False,isolated=False):
  rows=registration.get('runtimes',[])
  selected=[row for row in rows if (row.get('os'),row.get('arch'))==('linux','x86_64')]
  if len(selected)!=1:raise ValueError('explicit Linux x86 native private-copy identity required')
  row=selected[0];members={module_name:module};expected={}
  if module not in files or _record(files[module]['artifact'])!=_record(row['module']):raise ValueError('native module differs from declared private-copy identity')
  for name,artifact in row['libraries'].items():
   _relative(name);source=(PurePosixPath(core_root)/name).as_posix()
   if source not in measured or _record(files[source]['artifact'])!=_record(artifact):raise ValueError('native dependency differs from declared private-copy identity')
   members[name]=source
   basename=(measured[source]['soname']or PurePosixPath(name).name)if isolated else PurePosixPath(name).name
   if basename in expected:raise ValueError('ambiguous private native dependency basename')
   expected[basename]=_record(artifact)
  mappings[label]=members;private.append((label,module_name,expected,deepbind,isolated))
 translation=plan['translation'];private_owner('ct2',translation['module_path'],'libken_ct2_backend.so',translation['core_root'],translation['registration'],True)
 if transformers:private_owner('torch',transformers['torch']['module_path'],'ken_model_backend.so',transformers['torch']['core_root'],transformers['torch']['registration'],isolated=True)
 # ONNX authenticates a single anonymous private copy, not its source directory.
 onnx=plan['environment']['KEN_ORT_LIBRARY'];mappings['onnx']={'runtime.so':onnx};private.append(('onnx','runtime.so',{},False,False))
 checked=set();used=set();edges=[];preloaded={}
 def visit(namespace,logical,inherited=(),environment=True,expected=None,preloads=None,active=None):
  expected=expected or {};preloads=preloads or {};active=set()if active is None else active
  original=mappings[namespace].get(logical)
  if original not in measured:raise ValueError('native loader root is not a declared ELF: '+logical)
  record=measured[original];own_rpath=_loader_paths(record['rpath'],logical,namespace);own_runpath=_loader_paths(record['runpath'],logical,namespace)
  rpaths=tuple(dict.fromkeys((own_rpath if not record['runpath']else [])+list(inherited)))
  key=(namespace,logical,rpaths,environment,tuple(sorted((name,row['sha256'])for name,row in expected.items())),tuple(sorted(preloads.items())))
  if key in active or key in checked:return
  if len(active)>=128:raise ValueError('ELF dependency graph exceeds128 loading steps')
  active.add(key);used.add(original)
  search=list(rpaths)+([('release','lib')]if environment else [])+own_runpath
  for needed in record['needed']:
   chosen=preloads.get(needed)
   if chosen is None:
    for context,directory in search:
     relative=(PurePosixPath(directory)/needed).as_posix();source=mappings[context].get(relative)
     if source is not None:chosen=(context,relative,source);break
   if chosen is None:
    if needed not in systems or needed in expected:raise ValueError(f'ELF dependency is not available in actual loader paths: {original}: {needed}')
    edges.append({'object':original,'needed':needed,'system':True});continue
   context,relative,source=chosen
   if context=='system':
    if needed in expected:raise ValueError('native private dependency is already supplied by an unauthenticated system library: '+needed)
    edges.append({'object':original,'needed':needed,'system':True});continue
   if needed in expected and _record(files[source]['artifact'])!=expected[needed]:raise ValueError('native private dependency is shadowed by different loader bytes: '+needed)
   edges.append({'object':original,'needed':needed,'resolved':source,'namespace':context})
   visit(context,relative,rpaths,environment,expected,preloads,active)
  active.remove(key);checked.add(key)
 # The launcher must start before it can establish release/lib for its child.
 visit('release','ken',environment=False)
 for root in ('ken-rs','ken-check-worker','git'):
  before=len(edges);visit('release',root)
  if root=='ken-rs':
   for edge in edges[before:]:
    if 'resolved'in edge:preloaded.setdefault(edge['needed'],(edge['namespace'],next(name for name,source in mappings[edge['namespace']].items()if source==edge['resolved']),edge['resolved']))
    elif edge.get('system'):preloaded.setdefault(edge['needed'],('system','', ''))
 for namespace,module,expected,deepbind,isolated in private:
  admitted={}if deepbind or isolated else preloaded
  if isolated:
   # The native owner explicitly pins each authenticated dependency in its own
   # glibc namespace before loading clients; LD_LIBRARY_PATH remains unchanged.
   names={measured[source]['soname']or PurePosixPath(name).name:name for name,source in mappings[namespace].items()if name!=module}
   visiting=set()
   def preload(name):
    source=mappings[namespace][name];soname=measured[source]['soname']or PurePosixPath(name).name
    if soname in admitted:return
    if name in visiting:raise ValueError('cyclic private native dependency graph')
    if len(visiting)>=128:raise ValueError('private native dependency graph exceeds128 loading steps')
    visiting.add(name)
    for needed in measured[source]['needed']:
     if needed in names:preload(names[needed])
    visit(namespace,name,expected=expected,preloads=admitted)
    admitted[soname]=(namespace,name,source);visiting.remove(name)
   for name in sorted(names.values()):preload(name)
  visit(namespace,module,expected=expected,preloads=admitted)
  for name in mappings[namespace]:
   if mappings[namespace][name]not in used:visit(namespace,name,expected=expected,preloads=admitted)
 # Direct grammar/dense libraries retain their real staged ORIGIN locations.
 private_sources={source for namespace in mappings if namespace!='release'for source in mappings[namespace].values()}
 for name in measured:
  if name not in used and name not in private_sources:visit('release',name)
 return {'scope':'launcher startup, child release/lib, declared private native copies and confined ORIGIN paths','edges':edges}

def _validate_provenance(provenance):
 if not isinstance(provenance,dict)or not all(isinstance(provenance.get(key),dict)for key in('source','build','runtime','qualification')):raise ValueError('explicit source/build/runtime/qualification provenance required')
 source=provenance['source'];commit=source.get('commit')
 if not isinstance(commit,str)or not re.fullmatch('[0-9a-f]{40}',commit)or type(source.get('dirty'))is not bool or type(provenance['qualification'].get('accepted'))is not bool:raise ValueError('explicit source and qualification state required')

def authenticate_bundle(directory):
 root=Path(directory).resolve();manifest_path=root/'FILES.json'
 if manifest_path.stat().st_size>2*1024*1024 or manifest_path.stat().st_mode&0o7777!=0o444 or manifest_path.stat().st_nlink!=1:raise ValueError('independent read-only bounded FILES.json required')
 manifest=load(manifest_path)
 if set(manifest)!={'format','target','entrypoints','resources','files','provenance'} or manifest['format']!='ken-native-package/1' or manifest['target']!=TARGET or manifest['entrypoints']!=ENTRYPOINTS or manifest['resources']!='resources/search.json':raise ValueError('Linux x86 CPU package declaration differs')
 files=manifest['files']
 if not isinstance(files,dict) or not 0<len(files)<=20000:raise ValueError('bounded exact package inventory required')
 actual=set();directories=set()
 for path in root.rglob('*'):
  if path.is_symlink():raise ValueError('package symlink forbidden')
  name=path.relative_to(root).as_posix();_relative(name)
  if path.is_dir():directories.add(name)
  elif path.is_file():actual.add(name)
  else:raise ValueError('special package file forbidden')
 if actual!=set(files)|{'FILES.json'} or any(not any(name.startswith(parent+'/') for name in actual)for parent in directories):raise ValueError('package inventory contains missing/foreign entries')
 total=0
 for name,row in files.items():
  _relative(name);expected=_record(row)
  if set(row)!={'bytes','sha256','mode'} or type(row['mode'])is not int or row['mode']not in(0o444,0o555):raise ValueError('immutable artifact mode required')
  path=root/name
  if path.stat().st_nlink!=1 or path.stat().st_mode&0o7777!=row['mode'] or identity(path)!=expected:raise ValueError('package artifact differs: '+name)
  total+=row['bytes']
 if total>64*1024**3:raise ValueError('package exceeds64GiB')
 for name in ENTRYPOINTS.values():
  if name not in files or files[name]['mode']!=0o555:raise ValueError('executable native entrypoint required')
  check_native_architecture(root/name,('linux','x86_64'))
 search=load(root/manifest['resources'])
 if search.get('format')!='ken-search-installation/1' or search.get('private_parent')!='../../../var/private' or search.get('cache_parent')!='../../../var/cache':raise ValueError('portable resources and external prefix/var runtime state required')
 def contained(value,file=False):
  if not isinstance(value,str)or Path(value).is_absolute():raise ValueError('relative resource path required')
  path=(root/'resources'/value).resolve()
  if not path.is_relative_to(root):raise ValueError('resource escapes package')
  if file and path.relative_to(root).as_posix()not in files:raise ValueError('resource file is undeclared')
  return path.relative_to(root).as_posix()
 for key in('grammar_manifest','bundled_npz'):contained(search[key],True)
 contained(search['ranking_directory'])
 for value in search['sources'].values():contained(value)
 if search.get('onnx_library'):contained(search['onnx_library'],True)
 for key in('translation','torch'):
  if search.get(key):contained(search[key]['module_path'],True);contained(search[key]['core_root'])
 if search.get('catalogue_extensions')is not None:
  declared=search['catalogue_extensions']
  if not isinstance(declared,dict)or set(declared)!={'path','bytes','sha256'}:raise ValueError('strict catalogue declaration required')
  name=contained(declared['path'],True)
  if _record(declared)!=_record(files[name]):raise ValueError('catalogue declaration differs from authenticated inventory identity')
 provenance=manifest['provenance']
 _validate_provenance(provenance)
 return dict(root=str(root),manifest_sha256=identity(manifest_path)['sha256'],file_count=len(files),total_bytes=total,provenance=provenance)

def build_bundle(repo,environment,binaries,destination,provenance):
 repo=Path(repo).resolve();destination=Path(destination).absolute()
 if destination.exists()or destination.is_symlink():raise ValueError('fresh package destination required')
 if set(binaries)!=set(ENTRYPOINTS):raise ValueError('all four native entrypoints are required')
 binding=None
 if environment.get('KEN_NATIVE_BUILD'):
  from tools.native_release import bind_build
  binding=bind_build(Path(environment['KEN_NATIVE_BUILD']),binaries)
  if not re.fullmatch('[0-9a-f]{40}',binding.get('source_commit')or ''):raise ValueError('native build must retain its source commit before package assembly')
 _validate_provenance(provenance)
 legacy=provenance.get('legacy_runtime')
 if not isinstance(legacy,dict)or legacy.get('format')!='ken-legacy-runtime/1':raise ValueError('explicit versioned legacy runtime profile required')
 plan=copy.deepcopy(resources.plan(repo,environment))
 files=plan['files']
 def add(name,source,record):
  _relative(name);source=Path(source)
  if name in files or not source.is_absolute()or source.is_symlink()or not source.is_file()or identity(source)!=_record(record):raise ValueError('duplicate/changed/invalid declared package input: '+name)
  files[name]=dict(source=str(source),artifact=_record(record))
 static=repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz';static_record=load(repo/'crates/ken-models/resources/legacy-compatibility.json')['static_table']
 static_name='inputs/static/ken__static-qwen3-r512-v2.npz';add(static_name,static,static_record)
 for role,name in ENTRYPOINTS.items():
  source=Path(binaries[role]);check_native_architecture(source,('linux','x86_64'));add(name,source,binding['artifacts'][role]if binding and role in binding['artifacts']else identity(source))
 transformers=None
 if environment.get('KEN_PACKAGE_TRANSFORMERS'):
  transformers=load(Path(environment['KEN_PACKAGE_TRANSFORMERS']))
  if transformers.get('format')!='ken-package-transformers/1'or not isinstance(transformers.get('files'),dict)or not isinstance(transformers.get('sources'),dict)or not isinstance(transformers.get('torch'),dict):raise ValueError('explicit native transformer declaration required')
  for name,row in transformers['files'].items():add(name,Path(row['source']),row)
  for key in ('module_path','core_root'):_relative(transformers['torch'][key])
  if transformers['torch']['module_path']not in files:raise ValueError('transformer module is undeclared')
  for value in transformers['sources'].values():_relative(value)
 try:license_index=load(Path(environment['KEN_PACKAGE_LICENSES']));closure=load(Path(environment['KEN_PACKAGE_ELF_CLOSURE']))
 except KeyError as error:raise ValueError('declared package ELF closure and license index are required')from error
 if license_index.get('format')!='ken-native-package-licenses/1'or set(license_index.get('components',[]))!=(COMPONENTS|({'torch'}if transformers else set())) or not license_index.get('files'):raise ValueError('complete declared native component license index required')
 for name,row in license_index['files'].items():
  if not name.startswith('licenses/'):raise ValueError('license payloads must be in licenses/')
  add(name,Path(row['source']),row)
 add('licenses/ken-LICENSE',repo/'LICENSE',identity(repo/'LICENSE'))
 if closure.get('format')!='ken-native-elf-closure/1'or not isinstance(closure.get('system_libraries'),list)or not isinstance(closure.get('files'),dict)or not isinstance(closure.get('baseline'),str):raise ValueError('explicit ELF closure and system baseline required')
 for name,row in closure['files'].items():
  if Path(name).name!=name or 'libpython'in name.lower()or'libtorch_python'in name.lower():raise ValueError('native basename-only ELF closure required')
  add('lib/'+name,Path(row['source']),row)
 measured={}
 for name,row in files.items():
  path=Path(row['source'])
  with path.open('rb')as stream:header=stream.read(4)
  if header==b'\x7fELF':
   check_native_architecture(path,('linux','x86_64'));record=_elf(path)
   measured[name]=record
 loader=_validate_elf_loader(files,measured,set(closure['system_libraries']),plan,transformers)
 destination.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.ken-package-build-',dir=destination.parent)as temporary:
  stage=Path(temporary)/'ready';stage.mkdir();resources.stage(plan,stage)
  translation=copy.deepcopy(plan['translation']);translation['module_path']=str(Path(translation['module_path']).relative_to('inputs'));translation['core_root']=str(Path(translation['core_root']).relative_to('inputs'))
  runtime=stage/plan['environment']['KEN_CT2_PREPARATION'];runtime.unlink();runtime.write_text(json.dumps(translation,indent=2)+'\n');runtime.chmod(0o444)
  (stage/'resources').mkdir()
  sources={}
  for name,variable in resources.MODELS:
   declaration=load(repo/'crates/ken-models/resources'/(name+'.json'));declaration=declaration.get('source',declaration);sources[declaration['model_id']]='../'+plan['environment'][variable]
  installed=dict(format='ken-search-installation/1',grammar_manifest='../'+plan['environment']['KEN_GRAMMAR_MANIFEST'],ranking_directory='../'+plan['environment']['KEN_PUBLIC_RANKS'],private_parent='../../../var/private',cache_parent='../../../var/cache',bundled_npz='../'+static_name,sources=sources,acquisition='offline',legacy_runtime=legacy,onnx_library='../'+plan['environment']['KEN_ORT_LIBRARY'],translation=dict(registration=plan['translation']['registration'],module_path='../'+plan['translation']['module_path'],core_root='../'+plan['translation']['core_root']))
  if transformers:
   installed['torch']=dict(registration=transformers['torch']['registration'],module_path='../'+transformers['torch']['module_path'],core_root='../'+transformers['torch']['core_root'])
   installed['sources'].update({name:'../'+value for name,value in transformers['sources'].items()})
  (stage/'resources/search.json').write_text(json.dumps(installed,indent=2)+'\n');(stage/'resources/search.json').chmod(0o444)
  records={}
  for path in sorted(stage.rglob('*')):
   if path.is_file():
    name=path.relative_to(stage).as_posix();mode=0o555 if name in ENTRYPOINTS.values()else 0o444
    path.chmod(mode);records[name]=dict(**identity(path),mode=mode)
  captured=copy.deepcopy(provenance);captured.pop('legacy_runtime',None)
  captured['build'].update(package_builder=identity(Path(__file__)),binaries={role:_record(files[name]['artifact'])for role,name in ENTRYPOINTS.items()},source_binary_binding_verified=binding is not None)
  if binding:
   captured['source'].update(sha256=binding['source_sha256'],commit=binding['source_commit'],dirty=binding['source_dirty'])
   captured['build']['native_build']=binding
  captured['runtime'].update(baseline=closure['baseline'],system_libraries=closure['system_libraries'],elf=measured,loader=loader,licenses=identity(Path(environment['KEN_PACKAGE_LICENSES'])))
  captured['qualification']={'accepted':False,'scope':'authenticated package assembly; behavioral qualification remains external','supplied':provenance['qualification']}
  manifest=dict(format='ken-native-package/1',target=TARGET,entrypoints=ENTRYPOINTS,resources='resources/search.json',files=records,provenance=captured)
  (stage/'FILES.json').write_text(json.dumps(manifest,sort_keys=True,indent=2,ensure_ascii=True)+'\n');(stage/'FILES.json').chmod(0o444)
  result=authenticate_bundle(stage)
  if destination.exists()or destination.is_symlink():raise ValueError('package destination appeared during assembly')
  stage.rename(destination)
 return {**result,'root':str(destination)}

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
 for role in ENTRYPOINTS:parser.add_argument('--'+role.replace('_','-'),type=Path,required=True)
 parser.add_argument('--provenance',type=Path,required=True);args=parser.parse_args(argv)
 result=build_bundle(args.repo,os.environ,{role:getattr(args,role)for role in ENTRYPOINTS},args.destination,load(args.provenance));print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

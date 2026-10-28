"""Build the owned translation ABI against the authenticated CPU SDK."""
from pathlib import Path
import json, platform, re, shlex, subprocess
from .translation_cpu_prepare import registration, verify_sdk
from .native_json import identity, load
from .native_binary import check_native_architecture

SOURCES = ('CMakeLists.txt', 'include/ken_translation_api.h', 'src/translation.cpp')
PROOF_FILES = ('commands.json','0.stdout','0.stderr','1.stdout','1.stderr',
    'build/CMakeCache.txt','build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake',
    'build/CMakeFiles/ken_ct2_backend.dir/link.txt','build/compile_commands.json',
    'compiler.stdout','compiler.stderr')
CMAKE_ID={'bytes':18814840,'sha256':'576c050dab1e1418b6703b5cfb523330567683dad0c60a5ff9cc23128143812e'}

def commands_for(repo,sdk,out,cmake):
    core=sdk/'lib/libctranslate2-fd146744.so.4.8.2'
    return [[str(cmake),'-G','Unix Makefiles','-S',str(repo/'native/ken-ct2-backend'),'-B',str(out/'build'),
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DKEN_CT2_SDK='+str(sdk),'-DKEN_CT2_CORE_LIBRARY='+str(core)],
        [str(cmake),'--build',str(out/'build'),'--parallel','2']]

def cache_values(path):
    result={}
    for line in path.read_text().splitlines():
        if not line or line.startswith(('#','//')):continue
        match=re.fullmatch(r'([^:=]+):[^=]+=(.*)',line)
        if not match or match[1]in result:raise ValueError('invalid or duplicate CMake cache entry')
        result[match[1]]=match[2]
    return result

def compiler_values(path):
    text=path.read_text();result={}
    for key in('COMPILER','COMPILER_ID','COMPILER_VERSION','COMPILER_ABI','SIZEOF_DATA_PTR'):
        matches=re.findall(r'^set\(CMAKE_CXX_'+key+r' "([^"\n]*)"\)$',text,re.M)
        if len(matches)!=1:raise ValueError('one CMake compiler declaration required: '+key)
        result[key]=matches[0]
    return result

def proof_errors(saved,proof,repo,module,sdk_manifest):
    """Validate semantic build inputs, including transported original paths."""
    try:
        required={'format','sources','sdk','cmake_version','cmake_identity','commands','proof_files','registration',
            'module_path','core_root','source_root','sdk_root','output_root','compiler'}
        if set(saved)!=required or saved['format']!='ken-translation-cpu-build/1':raise ValueError('complete versioned translation build proof required')
        source,sdk,out=map(Path,(saved['source_root'],saved['sdk_root'],saved['output_root']))
        if any(not p.is_absolute()or'..'in p.parts for p in(source,sdk,out)):raise ValueError('absolute recorded build paths required')
        cmake=Path(saved['commands'][0][0])
        if not cmake.is_absolute()or saved['commands']!=commands_for(source,sdk,out,cmake):raise ValueError('registered CMake command structure differs')
        if load(proof/'commands.json')!=saved['commands']:raise ValueError('recorded CMake commands differ')
        if saved['cmake_version'].splitlines()[0]!='cmake version 3.31.10'or saved['cmake_identity']!=CMAKE_ID:raise ValueError('pinned CMake binary/version differs')
        if saved['sources']!=source_files(repo)or saved['sdk']!=sdk_manifest:raise ValueError('registered source or SDK manifest differs')
        if saved['core_root']!=str(sdk/'lib')or saved['module_path']!=str(out/'build/libken_ct2_backend.so'):raise ValueError('registered build destinations differ')
        runtime=dict(os='linux',arch='x86_64',core_version='4.8.2',abi=1,module=module,libraries=registration(repo)['libraries'])
        if saved['registration']!=dict(format='ken-native-translation/1',runtimes=[runtime]):raise ValueError('registered compiled module/core differs')
        if saved['proof_files']!={name:identity(proof/name)for name in PROOF_FILES}:raise ValueError('translation compiler/build proof bytes differ')
        cache=cache_values(proof/'build/CMakeCache.txt');compiler=compiler_values(proof/'build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake')
        wanted={'CMAKE_BUILD_TYPE':'Release','CMAKE_CXX_FLAGS':'','CMAKE_CXX_FLAGS_RELEASE':'-O3 -DNDEBUG',
            'CMAKE_SHARED_LINKER_FLAGS':'','CMAKE_SHARED_LINKER_FLAGS_RELEASE':'','CMAKE_GENERATOR':'Unix Makefiles',
            'CMAKE_EXPORT_COMPILE_COMMANDS':'ON','CMAKE_HOME_DIRECTORY':str(source/'native/ken-ct2-backend'),
            'CMAKE_CACHEFILE_DIR':str(out/'build'),'KEN_CT2_SDK':str(sdk),
            'KEN_CT2_CORE_LIBRARY':str(sdk/'lib/libctranslate2-fd146744.so.4.8.2')}
        if any(cache.get(key)!=value for key,value in wanted.items()):raise ValueError('registered source/SDK/compiler cache configuration differs')
        stamp=saved['compiler'];compiler_path=compiler['COMPILER']
        if(compiler['COMPILER_ID']not in('GNU','Clang')or compiler['COMPILER_ABI']!='ELF'or compiler['SIZEOF_DATA_PTR']!='8'
           or cache.get('CMAKE_CXX_COMPILER')!=compiler_path or not Path(compiler_path).is_absolute()
           or set(stamp)!={'path','id','version','binary'}or stamp['path']!=compiler_path
           or stamp['id']!=compiler['COMPILER_ID']or stamp['version']!=compiler['COMPILER_VERSION']
           or set(stamp['binary'])!={'bytes','sha256'}or type(stamp['binary']['bytes'])is not int or stamp['binary']['bytes']<=0
           or not re.fullmatch('[0-9a-f]{64}',stamp['binary']['sha256'])):raise ValueError('actual CMake compiler identity differs')
        if compiler['COMPILER_VERSION']not in(proof/'compiler.stdout').read_text():raise ValueError('actual compiler version output differs')
        if any((proof/name).read_bytes()for name in('0.stderr','1.stderr','compiler.stderr')):raise ValueError('unexpected compiler/build diagnostics')
        compiled=load(proof/'build/compile_commands.json');src=source/'native/ken-ct2-backend/src/translation.cpp';obj='CMakeFiles/ken_ct2_backend.dir/src/translation.cpp.o'
        if len(compiled)!=1 or compiled[0]['directory']!=str(out/'build')or compiled[0]['file']!=str(src)or compiled[0]['output']!=obj:raise ValueError('one registered C++ compilation unit required')
        actual=shlex.split(compiled[0]['command']);standards=[v for v in actual if v.startswith('-std=')]
        if len(standards)>1 or any(v not in('-std=gnu++17','-std=c++17')for v in standards):raise ValueError('unregistered C++ language standard')
        actual=[v for v in actual if v not in standards]
        wanted=[compiler_path,'-Dken_ct2_backend_EXPORTS','-I'+str(source/'native/ken-ct2-backend/include'),'-I'+str(sdk/'include'),
            '-O3','-DNDEBUG','-fPIC','-fvisibility=hidden','-fvisibility-inlines-hidden','-Wall','-Wextra','-Werror','-o',obj,'-c',str(src)]
        if actual!=wanted:raise ValueError('registered C++ compiler flags/includes/source differ')
        actual=[v.replace('\\$ORIGIN','$ORIGIN')for v in shlex.split((proof/'build/CMakeFiles/ken_ct2_backend.dir/link.txt').read_text())]
        dependency='-Wl,--dependency-file=CMakeFiles/ken_ct2_backend.dir/link.d'
        if actual.count(dependency)>1:raise ValueError('duplicate linker dependency output')
        actual=[v for v in actual if v!=dependency]
        wanted=[compiler_path,'-fPIC','-O3','-DNDEBUG','-Wl,--disable-new-dtags','-Wl,-rpath-link,'+str(sdk/'lib'),
            '-shared','-Wl,-soname,libken_ct2_backend.so','-o','libken_ct2_backend.so',obj,'-Wl,-rpath,$ORIGIN',str(sdk/'lib/libctranslate2-fd146744.so.4.8.2')]
        if actual!=wanted:raise ValueError('registered link dependencies or private $ORIGIN policy differ')
        if 'Built target ken_ct2_backend'not in(proof/'1.stdout').read_text():raise ValueError('actual native compilation completion absent')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,AttributeError)as error:return[str(error)]

def source_files(repo):
    root = Path(repo) / 'native/ken-ct2-backend'
    return {name: identity(root / name) for name in SOURCES}

def verify_build(out, repo, sdk):
    try:
        out, repo, sdk = map(Path, (out, repo, sdk))
        if errors := verify_sdk(sdk, repo):
            raise ValueError('SDK: ' + '; '.join(errors))
        saved = load(out / 'PREPARATION.json')
        record = registration(repo)
        module = out / 'build/libken_ct2_backend.so'
        runtime = dict(os='linux', arch='x86_64', core_version='4.8.2', abi=1,
                       module=identity(module), libraries=record['libraries'])
        if (saved['sources'] != source_files(repo)
                or saved['sdk'] != identity(sdk / 'PREPARATION.json')
                or saved['registration'] != dict(format='ken-native-translation/1', runtimes=[runtime])
                or saved['module_path'] != str(module)
                or saved['core_root'] != str(sdk / 'lib')):
            raise ValueError('translation module build inputs or binary differ')
        if module.is_symlink():
            raise ValueError('regular translation module required')
        if(saved['source_root'],saved['sdk_root'],saved['output_root'])!=(str(repo),str(sdk),str(out)):
            raise ValueError('local translation build roots differ')
        if errors:=proof_errors(saved,out,repo,identity(module),identity(sdk/'PREPARATION.json')):raise ValueError('; '.join(errors))
        if identity(Path(saved['commands'][0][0]))!=saved['cmake_identity']or identity(Path(saved['compiler']['path']))!=saved['compiler']['binary']:
            raise ValueError('actual CMake/compiler executable differs')
        check_native_architecture(module, ('linux', 'x86_64'))
        return []
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [str(error)]

def build(repo, sdk, out, *, cmake):
    repo, sdk, out, cmake = map(Path, (repo, sdk, out, cmake))
    if errors := verify_sdk(sdk, repo):
        raise ValueError('SDK: ' + '; '.join(errors))
    if out.exists() or out.is_symlink():
        raise ValueError('fresh translation build destination required')
    if any(not p.is_absolute() for p in (repo, sdk, out, cmake)):
        raise ValueError('absolute translation build paths required')
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('Linux x86 translation build host required')
    version = subprocess.run([str(cmake), '--version'], check=True, capture_output=True, text=True).stdout
    if version.splitlines()[0] != 'cmake version 3.31.10'or identity(cmake)!=CMAKE_ID:
        raise ValueError('registered CMake 3.31.10 required')
    record = registration(repo)
    core = next(name for name in record['libraries'] if name.startswith('libctranslate2-'))
    sources = source_files(repo)
    sdk_identity = identity(sdk / 'PREPARATION.json')
    commands = commands_for(repo,sdk,out,cmake)
    out.mkdir(parents=True)
    (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    for index, command in enumerate(commands):
        with (out / f'{index}.stdout').open('wb') as stdout, (out / f'{index}.stderr').open('wb') as stderr:
            subprocess.run(command, stdout=stdout, stderr=stderr, check=True)
    if source_files(repo) != sources or identity(sdk / 'PREPARATION.json') != sdk_identity:
        raise ValueError('translation build inputs changed during compilation')
    module = out / 'build/libken_ct2_backend.so'
    compiler=compiler_values(out/'build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake')
    with(out/'compiler.stdout').open('wb')as stdout,(out/'compiler.stderr').open('wb')as stderr:
        subprocess.run([compiler['COMPILER'],'--version'],stdout=stdout,stderr=stderr,check=True)
    report = dict(format='ken-translation-cpu-build/1', sources=sources, sdk=sdk_identity,
                  source_root=str(repo),sdk_root=str(sdk),output_root=str(out),
                  compiler=dict(path=compiler['COMPILER'],id=compiler['COMPILER_ID'],version=compiler['COMPILER_VERSION'],binary=identity(Path(compiler['COMPILER']))),
                  cmake_version=version, cmake_identity=identity(cmake), commands=commands,
                  proof_files={name:identity(out/name)for name in PROOF_FILES},
                  registration=dict(format='ken-native-translation/1', runtimes=[dict(
                      os='linux', arch='x86_64', core_version='4.8.2', abi=1,
                      module=identity(module), libraries=record['libraries'])]),
                  module_path=str(module), core_root=str(sdk / 'lib'))
    (out / 'PREPARATION.json').write_text(json.dumps(report, indent=2) + '\n')
    if errors := verify_build(out, repo, sdk):
        raise ValueError('; '.join(errors))
    return report

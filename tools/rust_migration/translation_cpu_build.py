"""Build the owned translation ABI against the authenticated CPU SDK."""
from pathlib import Path
import json, platform, subprocess
from .translation_cpu_prepare import registration, verify_sdk
from .native_json import identity, load
from .native_binary import check_native_architecture

SOURCES = ('CMakeLists.txt', 'include/ken_translation_api.h', 'src/translation.cpp')
PROOF_FILES = ('commands.json','0.stdout','0.stderr','1.stdout','1.stderr',
    'build/CMakeCache.txt','build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake',
    'build/CMakeFiles/ken_ct2_backend.dir/link.txt')

def source_files(repo):
    root = Path(repo) / 'native/ken-ct2-backend'
    return {name: identity(root / name) for name in SOURCES}

def verify_build(out, repo, sdk):
    try:
        out, repo, sdk = map(Path, (out, repo, sdk))
        if errors := verify_sdk(sdk, repo):
            raise ValueError('SDK: ' + '; '.join(errors))
        saved = load(out / 'PREPARATION.json')
        if saved['proof_files'] != {name:identity(out/name)for name in PROOF_FILES}:
            raise ValueError('translation module compiler/build proof differs')
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
    if version.splitlines()[0] != 'cmake version 3.31.10':
        raise ValueError('registered CMake 3.31.10 required')
    record = registration(repo)
    core = next(name for name in record['libraries'] if name.startswith('libctranslate2-'))
    sources = source_files(repo)
    sdk_identity = identity(sdk / 'PREPARATION.json')
    commands = [[str(cmake), '-G', 'Unix Makefiles', '-S', str(repo / 'native/ken-ct2-backend'), '-B', str(out / 'build'),
                 '-DCMAKE_BUILD_TYPE=Release', '-DKEN_CT2_SDK=' + str(sdk),
                 '-DKEN_CT2_CORE_LIBRARY=' + str(sdk / 'lib' / core)],
                [str(cmake), '--build', str(out / 'build'), '--parallel', '2']]
    out.mkdir(parents=True)
    (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    for index, command in enumerate(commands):
        with (out / f'{index}.stdout').open('wb') as stdout, (out / f'{index}.stderr').open('wb') as stderr:
            subprocess.run(command, stdout=stdout, stderr=stderr, check=True)
    if source_files(repo) != sources or identity(sdk / 'PREPARATION.json') != sdk_identity:
        raise ValueError('translation build inputs changed during compilation')
    module = out / 'build/libken_ct2_backend.so'
    report = dict(format='ken-translation-cpu-build/1', sources=sources, sdk=sdk_identity,
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

"""Produce native grammar packets; validation policy lives in grammar_extension."""
from __future__ import annotations
import gzip,json,platform,shutil,subprocess,tarfile
from pathlib import Path
from .native_json import identity,load
from .parser_validate import run_parser_capture,source_identity,LIMIT
from .grammar_prepare import native_platform
from .grammar_extension import ORIGINAL_FILES,PREDECESSOR_FILES_SHA,read_reference,restore_fixture_original,native_cases,verify_grammar_capture,require

def capture_packet(repo:Path,manifest:Path,out:Path):
    require(not(out/'HOST.json').exists(),'grammar packet already captured')
    host=native_platform();original=out/'original';original.parent.mkdir(parents=True,exist_ok=True)
    if host=='linux-x86_64':
        fixture=repo/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz'
        reference=restore_fixture_original(fixture,original);shutil.copyfile(fixture,out/'reference.json.gz')
    else:
        proof=repo/'docs/validation/rust-migration-2026-10-23/m3-parsers-review'
        require(identity(proof/'FILES.json')['sha256']==PREDECESSOR_FILES_SHA,'accepted ARM parser receipt differs')
        name=('macos'if host=='macos-arm64'else'linux')+'-capture.tar.gz'
        row=next(row for row in load(proof/'FILES.json')['files']if row['path']==name)
        require(identity(proof/name)=={key:row[key]for key in('bytes','sha256')},'preserved ARM original archive differs')
        original.mkdir()
        with tarfile.open(proof/name,'r:gz')as archive:
            for name in ORIGINAL_FILES:
                member=archive.getmember('original/'+name);require(member.isfile()and member.size<=LIMIT,'unsafe original parser archive member')
                (original/name).write_bytes(archive.extractfile(member).read())
        name=('macos'if host=='macos-arm64'else'linux')+'-capture.tar.gz'
        shutil.copyfile(proof/name,out/'original-source.tar.gz');shutil.copyfile(proof/'FILES.json',out/'PREDECESSOR-FILES.json')
        (out/'reference.json.gz').write_bytes(gzip.compress((original/'reference.json').read_bytes(),mtime=0))
        reference=read_reference(out/'reference.json.gz')
    sources=source_identity(repo);(out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n')
    probe=repo/'target/debug/examples/parser_probe';(out/'bin').mkdir();shutil.copy2(probe,out/'bin/parser-probe')
    run_parser_capture(repo,probe,manifest,native_cases(reference,repo),out/'native')
    host_record=dict(format='ken-grammar-host/1',platform=host,system=platform.system(),machine=platform.machine(),python=platform.python_version(),rustc=subprocess.check_output(['rustc','--version'],text=True).strip(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip())
    (out/'HOST.json').write_text(json.dumps(host_record,indent=2)+'\n')
    errors=verify_grammar_capture(out,repo);require(not errors,'; '.join(errors))
    return host_record

def snapshot_packet(repo:Path,out:Path):
    sources=source_identity(repo);require(sources==load(out/'SOURCES.json'),'grammar sources changed after execution')
    validation=[p for folder in ('tools/rust_migration','tests/rust_migration')for p in(repo/folder).glob('*.py')]
    validation.extend(repo/name for name in ('.github/workflows/rust-syntax.yml','.github/actions/restore-validation-fixtures/action.yml'))
    tooling={str(path.relative_to(repo)):identity(path)for path in sorted(validation)}
    records=dict(sources);records.update(tooling)
    for name in ('docs/validation/rust-migration-2026-10-18/baseline.json','docs/superpowers/specs/2026-10-24-rust-x86-grammars-design.md','docs/superpowers/plans/2026-10-24-rust-x86-grammars.md'):
        records[name]=identity(repo/name)
    with tarfile.open(out/'source-snapshot.tar.gz','w:gz')as archive:
        for name in sorted(records):archive.add(repo/name,arcname=name,recursive=False)
    (out/'SNAPSHOT.json').write_text(json.dumps(records,indent=2)+'\n')
    (out/'VALIDATION-SOURCES.json').write_text(json.dumps(tooling,indent=2)+'\n')

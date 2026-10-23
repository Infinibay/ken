"""Replay the repaired M3a receipt, with no inference or production writes."""
from pathlib import Path
import hashlib,json,re,sys,tarfile,tempfile
from tools.rust_migration.integration_validate import _manifest_errors,rust_gate_errors
from tools.rust_migration.receipts import junit_states
from tools.rust_migration.reference import verify_reference
from tools.rust_migration.source_validate import source_identity
from tools.rust_migration.source_evidence import verify_source_capture


def verify(proof:Path,repo:Path,current:bool=False):
    errors=_manifest_errors(proof);assert not errors,errors
    index=json.loads((proof/'INDEX.json').read_bytes())
    assert index['format']=='ken-source-review-repair/1'
    assert index['sources']==source_identity(proof/'native-sources')
    if current: assert index['sources']==source_identity(repo),'current source differs'
    predecessor=repo/index['predecessor']['path']/'FILES.json'
    assert hashlib.sha256(predecessor.read_bytes()).hexdigest()==index['predecessor']['sha256']
    baseline=repo/'docs/validation/rust-migration-2026-10-18/baseline.json'
    assert not verify_reference(repo,baseline),'original files changed'
    owners={r['path']:r['sha256'] for r in json.loads(baseline.read_bytes())['files']
        if r['path'] in ('src/ken/_paths.py','src/ken/gitignore_filter.py')}
    originals={s:json.loads((proof/f'reference-{s}.json').read_bytes()) for s in ['macos','linux']}
    assert originals['macos']['cases']==originals['linux']['cases']
    assert originals['macos']['definitions']==originals['linux']['definitions']
    for system,original in originals.items():
        runtime=original['runtime']; execution=original['execution']
        assert original['sources']==owners and runtime['pathspec']=='1.1.1' and runtime['python']=='3.12.9'
        assert (runtime['system'],runtime['machine'])==(('Darwin','arm64') if system=='macos' else ('Linux','aarch64'))
        assert execution['exit']==0 and json.loads(execution['stdout'])==dict(cases=original['cases'],runtime=runtime)
        assert len(original['cases'])==28 and sum(len(c['ignored']) for c in original['cases'])==432
        assert sum(len(c['walks']) for c in original['cases'])==83
        invalid=json.loads((proof/f'invalid-original-{system}.json').read_bytes())
        assert invalid['exit']==0 and invalid['sources']==owners and json.loads(invalid['stdout'])==invalid['rows']
        assert [r['rule'] for r in invalid['rows']]==['a[z-a].py','a\\','!','a[a--b].py','a[.py','a[].py','a[!].py']
        assert [r.get('error',{}).get('type') for r in invalid['rows']]==['error','GitIgnorePatternError','GitIgnorePatternError','error',None,None,None]
        assert all(r.get('ignored') is False for r in invalid['rows'][4:])
        gates=proof/'gates'/system
        assert not rust_gate_errors((gates/'rust-list.log').read_text(),(gates/'rust-tests.log').read_text())
        assert len(re.findall(r'^([^\n]+): test$',(gates/'rust-list.log').read_text(),re.M))==34
        states=junit_states(gates/'python.xml')
        discovered={p[:-3].replace('/','.')+'::'+n for p,n in re.findall(
            r'^(tests/rust_migration/test_source_[^:\n]+\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)}
        assert len(discovered)==24 and set(states)==discovered and set(states.values())=={'passed'}
        clippy=(gates/'clippy.log').read_text()
        assert 'Finished `dev` profile'in clippy and 'error:'not in clippy and 'warning:'not in clippy
        assert (gates/'fmt.log').read_bytes()==b''
        native=index['platforms'][system]['native_sha256']
        with tempfile.TemporaryDirectory(prefix='ken-source-replay-') as t:
            capture=Path(t)
            with tarfile.open(proof/f'{system}-capture.tar.gz') as archive:
                archive.extractall(capture,filter='data')
            prior=json.loads((repo/index['predecessor']['path']/'originals'/f'{system}.json').read_bytes())
            for corpus,reference in [('baseline',prior),('review',original)]:
                errors=verify_source_capture(capture/corpus,reference,index['sources'],native,system)
                assert not errors,(system,corpus,errors)
            for i,row in enumerate(json.loads((capture/'invalid.json').read_bytes())):
                folder=capture/f'invalid-{i}'
                assert row['rule']==invalid['rows'][i]['rule']
                observed=json.loads((folder/'stdout.json').read_bytes())
                assert observed==row['actual'] and observed['entries']==[] and observed['errors']
                assert all(e==dict(kind='invalid_rules',path='.gitignore') for e in observed['errors'])
                receipt=json.loads((folder/'execution.json').read_bytes())
                assert receipt['exit']==0 and receipt['native_sha256']==native
                assert 'libpython'not in (folder/'stderr.log').read_text()
                if system=='linux':
                    trace=(folder/'exec.trace').read_text()
                    assert len(re.findall(r'\bexecve(?:at)?\(',trace))==1 and not re.search(r'\bconnect\(',trace)
    return dict(passed=True,M3a_accepted=True,M3_accepted=False,
        per_platform=dict(Rust=34,Python=24,matcher_decisions=702,walks=134),review_findings_repaired=6)

if __name__=='__main__':
    print(json.dumps(verify(Path(__file__).resolve().parent,Path.cwd(),'--current'in sys.argv),indent=2))

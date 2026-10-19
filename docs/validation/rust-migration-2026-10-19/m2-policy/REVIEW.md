# Final independent review — model policy

Reviewer /root/m2_policy_final_review, gpt-6-astra/xhigh/fresh context/read-only.
Range97262af3..1e435210. Verdict: With fixes. Critical0, Important2, Minor0.

Strengths: policy ownership and all5ReviewFocus behaviors correct; actual original
SQLite/config/discovery oracle; coherent forwarding/typed comparison/release and
recursive receipt binding. Independent checks27focusedPython/process+7compiledRust
passed; bothnativeoutputs matchoriginal, all211artifacthashes and1066originalhashes
verified; currentmatrixPolicy_accepted=true,M2_accepted=false.

Important1: oracle requiresPython3.12.9 while CI selects3.12. Locations
policy_compare.py:60-64, policy_reference.py:136-138, rust-models.yml:25-26,
.python-version:1. Changing only oracle.python to3.12.10 rejects otherwise equal
policy replay; ordinary regression test also affected. Explicitly select registered
interpreter or establish tested compatibility with actualpatch retained asprovenance.

Important2: aggregate_policies policy_validate.py:79-99 authenticates summaries only,
not requiredoutputs/traces/logs/manifests. ChangedLinux nativeproject.model towrong/model
stillaccepted; deletingallfilesexcepttwo summary.json stillaccepted. Bind required
executionartifacts toreceipts andverify presence/hashes includingnestedproof;
recompare authenticatedpolicy output asappropriate. Add changed-output/missing-file
mutations. Existing publishedartifacts themselves verifiedcorrect.

Declined to judge (exhaustive, raw reviewer wording):
- Native SQLite/schema/vector-presence extraction and discovery failures — this cut consumes established facts; those adapters remain pending.
- Transactional pin publication, concurrent writers, crash recovery, and durability — InitialModelPin is only a proposed value.
- Config-file writing, malformed-file recovery, and live reload — the public API owns an already-read snapshot.
- Non-UTF-8 ingestion and unpaired-surrogate JSON configuration — future ingestion adapters must define this boundary; the current product API accepts Rust strings.
- Backend factories, acquisition, encoder singleton/reset behavior, and cache lifecycle — explicitly outside this pure policy cut.
- Applying prompts during inference, document-generation parsing, and reembedding — policy outputs are verified; those integrations remain pending.
- Additional model runtimes and end-to-end CLI/daemon promotion — no new implementation or installed promotion occurs here.
- Platforms beyond Darwin/arm64 and Linux/aarch64 — outside the registered acceptance matrix.
- Unrelated pre-existing implementation defects — prior accepted cuts remain baseline; their new integration effects were reviewed.
- Future doctest coverage — there are no current Rust documentation code blocks; the changed --all-targets invocation was assessed against present tests.
- Remote CI execution — configuration was reviewed; no remote run was performed.
- Overall M2 and M3–M8 completion — this review covers only the stated policy plan.

Ready to merge: With fixes. Nativepolicy sound within declaredboundary; interpreter
selection mismatch andartifact-integrity acceptance gap must be resolved before plan
acceptance. No secondreview; oneCritical/Important TDDcorrectionpass is required.

## Implementer severity audit and one correction pass

Both findings remain Important by user-visible effect; no Critical/Minor findings.
Fix commit90a23af2. No second reviewer or repeated review was dispatched.

1. Python patch: the regression failed on original.oracle.python:value differs,
then passed after allowing stable3.12.x only with exact Unicode15/owner/results/
observations/prompts and current verified Reference. Invalid minor/prerelease/
Unicode/source/output mutations still reject. Actual patch provenance is retained.
An isolated real3.12.10 replay is published in python-patch-replay; it matched all
1292histories/23prompts while retaining the original3.12.9 interpreter.
Preparation initially created an unintended uv launcher outside the project; its
exact private-runtime target was verified and that owned link was removed. Future
private preparation uses --no-bin and an absolute install directory.
2. Execution proof: all12 missing/changed/re-sealed output, omitted trace/proof,
log, malformed/missing manifest, summary-only, unsafe-path and symlink regressions
first demonstrated acceptance of bad evidence. The new verifier binds saved bytes
by hash/size, requires the complete named prior proof/log/XML/benchmark/trace tree,
compares raw nested summaries to embedded receipts and re-compares authenticated
policy/original output. All14 receipt/evidence tests and4 comparator tests pass.
The manifest excludes only root self-reference files and runtime environment caches.
Existing registered Linux core warnings remain governed by their prior owner.

All12 declined scopes have individual implementer rulings with costs in EXECUTION.
Whole updated BOTH28 candidate verification CLOSED0 on both platforms. Each ran
15702Python passes plus the same10historicxfail,141Rust passes and85process passes;
no new failures/skips/missing baseline IDs/typing errors or ignored Rust tests.
All153required execution artifacts and26current fingerprints passed the actual
public-tree matrix: Policy_accepted=true,M2_accepted=false. The plan is accepted
after the single correction pass; no second review was performed. The native
policy itself required no code change.

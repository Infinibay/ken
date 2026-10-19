# SDD ledger — plan: docs/superpowers/plans/2026-10-19-rust-m2-model-policy.md

Spec: docs/superpowers/specs/2026-10-19-rust-model-policy-design.md
Profile base97262af3, documentation9e98e95f. Native inline, one final reviewer;
no implementer/per-task agents. All originals/user work preserved.

## Pre-flight

| Producer -> consumer | Shared interface | Check |
|---|---|---|
| T1 -> T2 | id/input facts/config/forced variants and actual original results | logical facts supplied; no source_setup reaches product API |
| T1 -> T3 | exact ordered case IDs, original observations/runtime/source hashes | both original platforms agree before Rust; native never generates expected values |
| T2 -> T3 | public ModelPolicy DTOs and actual model_policy_probe JSON | prospective pins are values; no DB writer or model runtime |
| T3 -> prior validators/tests | optional policy_probe:Path, explicit absolute KEN_POLICY_PROBE | six forwarding layers checked; frozen reference strips native vars |
| existing Unicode owner -> T2 | Python15 space predicate | reuse private owner, no new table or current-toolchain whitespace drift |

Ruling: Continue spec/plan/implementation without new stage approval — the user's
explicit continuous/native/no-confirmations instruction governs this next M2 cut —
cost if wrong: design corrections require TDD/final review; no original removal,
installed promotion or external integration is inferred.
Ruling: Keep policy in ken-models and storage/core independent — reuse the one
fixed Unicode owner and feed explicit established facts at orchestration — cost
if wrong: later adapters need a small mapping; no tensor dependency added to core.
Ruling: A supplied false file-vector presence means proven absence, not unknown
schema/discovery failure — this pure API does not migrate the reader/writer — cost
if wrong: storage cut must add its own format/atomicity proof before applying pins;
M2 cannot close from these policy tests alone.
Ruling: Preserve missing versus present-empty metadata and raw override strings —
these are observable original decisions, including unusual legacy values — cost
if wrong: original awkward configuration remains until explicitly repaired.

Task 1: pending (independent original oracle)
Task 2: pending (pure native policy/probe)
Task 3: pending (both-platform28gate proof/final review)

Task1 BASE9e98e95fb5df6d6923321509fac4162121a6d857. Read exacttask-1brief.
RED task-1-red.log:4expected ModuleNotFoundError failures before any nativecode.
GREEN task-1-green-first.log/XML:4/4. Implemented only originaloracle tooling,
1292histories/6forcedvariants/23promptnames, realSQLite/config/marker, sourceguard,
logicalrowpreservation andobservedconfigure metadata delta. No nativepolicyyet.
FullPythonregressionexec43681RUNNING; logtask-1-python-full.log/XML here, proper
localsocketpermissions. ActualfrozenMacoriginalcaptureexec77907 to.ken/m2-policy/
oracle-macos.json; cases.json publishedinputsonly. BothOS originalcapture required
beforeTask2. No productdependencies/originalchanges/deletions.

Task1 originalMac77907CLOSED0 andLinux31104CLOSED0:1292histories/23promptnames,
6forcedvariants each. Logicalresults,observations,prompts and3sourceownerhashes
EXACTLYequalbetweenplatforms. Publishedcases/reference.json BEFOREanynativepolicy
implementation. Source_setup isoracle-only; nativewillreceiveid/inputonly.
FullPython43681stillrunning (last18%); mustcompletebeforeTask1commit/taskdone.

Linux extra four-tests first attempt failed because inherited /app pytest pythonpath selected the old tools package; isolated -c /dev/null with explicit rootdir/confcutdir passed4/4 (exec98659 CLOSED0,2.21s). Actual original capture was already successful. No product change; preserve both attempt receipts. FullPython43681 last86%.

FullPython43681 CLOSED0:15685 total,15675passed/same10historicxfail,0fail/error,656.896s. compare_python baseline: no newfailures/skips/missing IDs; comparison JSON retained. All1066original hashes unchanged. Task1 all Expected outputs met; scoped oracle/fixtures commit made.
Task 1: complete (commits 9e98e95..8a091c7, tests: .venv/bin/python -m pytest tests/rust_migration/test_policy_reference.py -q → ....                                                                     [100%])

Task2 BASE8a091c79601736670e7279d67b6f780fe96e3377; exactbriefread. REDtask-2-red.log CLOSED101: missing public model_policy module. GREENfive public-usage tests passed. Probe twoextra boundarytests observed missing run RED then2GREEN; check all frozen histories and strict missing/type/unknown/duplicate-ID/expected-injection rejection. Native owns configuration/results, no I/O/global model state or dependencies. Formatcheck CLOSED0. FullRust/alltargets39609 and Clippy in progress.

Task2 fullRust first attempt stopped on5 healthtests socket PermissionDenied (full log retained), not policy failures. Correct local-socket-permitted rerun70642 in progress. Clippy/alltargets CLOSED0. Release20309 CLOSED0. Actual copied nativeprobe outsidecheckout with sentinelPATH/no modelenv CLOSED0;1292results/23prompts EXACTLYequalboth originaloracles,empty stderr; receipt retained.

Task2 fullRust70642 CLOSED0:141passed/29sections/0failed/ignored. Formats/Clippy passed, five API+two probe tests passed after expected RED; exactactualstandalone process equality/empty stderr retained. Original1066 unchanged. All Expected met and scoped nativepolicy/probe/tests committed.
Task 2: complete (commits 8a091c7..82d2e97, tests: .ken/rust-migration/m2/prepared-macos-env cargo test --locked -p ken-models --test model_policy → test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.10s)

Task3 BASE82d2e975f517e3e0c25962d1dca5c7cacbdac82e. Exactbriefread.
RED missing policy_compare/policy_environment; initial11comparator/input/matrix
tests GREEN. Typed policy_probe forwarded through all6priorvalidators and baseenv.
Ruling: Bind fresh original replay to its verified current manifest, retaining
exact historical owner hashes/results, and bind current reference_source to26FPs —
full manifest fingerprints include unrelated checkout files, so historical full-
manifest equality falsely rejects CI's new checkout even with identical source —
cost if wrong: ancillary full-checkout equality is to current Reference, not the
historic manifest; all sourceowner/hash/original baseline gates remain required.
Parent translation comparator receives the same current-verified identity; exact
source-module/runtime/history checks remain. Actual policy recapture on a separately
frozen source observed this mismatch; new REDs cover bothcomparators and stale
source receipt. Full raw manifest fingerprint remains provenance. Missing-probe
preflight independently observed RED (missing registration error instead of probe)
before restored executable guard. Evidence task-3-current-manifest-red.log and
-task-3-missing-probe-red.log, GREEN in progress.

Current-manifest correction GREEN24 tests (task-3-current-manifest-green.log),
including actual recapture, parent translation provenance, strict JSON and source
receipt mutation; no source/hash weakening. Prior6forwarding GREEN7tests.
Ruling: Rust gates execute --all-targets, and preparation compiles them with
--no-run — the new probe unit contracts must execute on both platforms, not merely
compile; prior600s runtime deadline is unchanged — cost if wrong: slightly more
runtime for2small probe tests; the full141-test macOS run already passed.
Task3 real policyprocessMac36383 and fulltooling21962 running; no candidate or
both28gates frozen/executed yet. CI inputs/export and top28gate command updated;
remote CI is not claimed run. No reviewer yet.

Task3 nativepolicyMac36383 CLOSED0:3process tests; tooling21962 CLOSED0:115tests/0skip/error,56.006s. No remaining running tests. Docs/CI ready; next scoped implementation commit, immutable candidate, Linux+Mac preparation, BOTH28realgates, public proof/matrix, finalreview.

CandidateT3 source frozen5471files,manifest6c0240c82059dc4b932a283ed40b226f36c1e34bf850804f56b6cd4845bf8cbc; BOTHcopiedfilesverified. Macrelease64913 CLOSED0 and alltargettestpreparation CLOSED0; Mac28gates65117 RUNNING (properlocal-socketpermissions). Linuxrelease84952 CLOSED0 (16.24s), alltargetcompilepreparation juststarted. Wrappers/run-local-t3 private paths, both reusepreparedmodels/cores/Cargo/OpenBLAS cache; no deadlines changed.

Linuxalltargets7890 CLOSED0; BOTHprepared. Linux28gates juststarted (tool session returned). Mac28gates65117 in Pythonfull. Current26FPs written candidate-t3-fingerprints.json. No current failure; summaries pending do not imply pass.

MacT3 Pythonfull finished15689passed/same10historicxfail/1historicwarning,704.962s; exactbaselinecomparison no newfailure/skip/missing IDs, no currentfailures; JSON retained. Both28gates stillrunning Mac65117/Linux50109 (Linux last69%). Do not mark Task3done/acceptpolicy before fullmatrix/review.

T3 MacRust complete141passed/29sections/0failed/ignored, now85process suite. Linuxoriginalfull15689passed/same10historicxfail/1warning,957.300s; Linuxmypy0issues. Linuxpolicy-only process70131 CLOSED0:3tests, actualdependency/oneexec proof passes; fullLinuxRustnowrunning. Both28gates still65117/50109, no acceptance claim.

MacT3 whole28gates65117 CLOSED0. Top/nested26/23/20/18/16 allpassed, noexecutionerror. Macfull15689passed/10historicxfail, Rust141/0failed/ignored, process85/0skip/fail/error;26FPscurrentmatch. PublishingactualMacreceipt now. Linux50109 stillRust, no matrixacceptance orreviewyet.

Macpublish first invocation lacked PYTHONPATH for tools import; no destination written. Corrected explicitRootPYTHONPATH invocation CLOSED0; actualMacpublic12files/102rawhashes, policywall319216375ns, sourcecut6c0240... and all28current/26identities verified. Linux50109 still running, policy3preflight alreadygreen. No reviewer/matrix/Task3done yet.

Linux28gates50109 CLOSED0; top28/nested26/23allpassed, no executionerror.
Linux15689passed/same10historicxfail0failure, native141/29sections0failed/ignored,
85process0failure/error/skip(365.887s). Actualbothplatform28ready, copyingLinuxraw
beforepublication/matrix. Current26inputs remainequal; matrix/reviewpending.

CurrentRoot matrix30043 CLOSED0: Policy_accepted=true,M2_accepted=false, exact26FPs,
BOTHcurrent28. All1066original hashes unchanged. PublishedactualLinux109rawhashes,
Mac102; no failures/skips/ignored hidden. FullPython each15689passed/10historicxfail,
Rust141each,85processeach. No reviewer yet.
Ruling: Execute Task3's final-review bullet once in the plan-final lifecycle after
Task3 matrix/task-done — executing-plans requires the fresh review after all tasks,
so this bullet belongs to final review rather than blocking its own task-done —
cost if wrong: implementation/matrix completion is distinct from plan acceptance;
no later migration cut starts until final review and verified fixes are complete.

Ruling: Final review covers the entire current-plan range97262af3..HEAD, including
spec/oracle/native/pipeline/proof, while prior accepted cuts remain baseline —
this is the plan's whole change, and all prior native gates were re-executed on
current source — cost if wrong: unrelated pre-existing defects may remain outside
this review; all new integration/forwarding effects and ReviewFocus stay in scope.

# SDD ledger — plan: docs/superpowers/plans/2026-10-19-rust-m2-translation.md

Spec: docs/superpowers/specs/2026-10-19-rust-translation-design.md
Whole migration branch: codex/rust-migration. Profile base: 1ae4bb97.
Execution: native inline; no implementer agents. User explicitly requests continuous
completion of all stages, no new confirmation pauses, preserving originals.

## Pre-flight

| Producer → consumer | Shared contract | Check |
|---|---|---|
| T1 → T2 | independent tiny normalized bytes, full recipe, Unicode15/policy histories | fixture/source hashes retained; normalizer must preserve insertion order and config-only newline |
| T1 → T3 | actual real CT2/SPM histories and platform identities | source/derived5pins, raw+restored text and512/1024error boundaries; no oracle from Rust |
| T2 → T3 | PreparedTranslation owns verified bytes; QueryExpansionPlan owns one query | no unchecked constructors, per-call placeholders, laziness before I/O |
| T1/T2/T3 → T4 | explicit source/probe/build prerequisites and actual outputs | current-source26gate matrix composes prior23; typed inputs propagate to nested validators |
| shared assets::python_json → all native profiles | sorted object order and ASCII strings | only extend recursive arrays; no serde preserve_order; rerun prior identities/parity |

Ruling: Continue spec/plan/implementation without asking for another stage approval —
the user's explicit whole-migration/no-confirmations instruction takes precedence
over skill approval pauses — cost if wrong: design corrections are caught by TDD
and the required fresh review; no original removal or installed promotion.

Ruling: Keep private feasibility probes disposable and outside product dependencies —
backend differences must be understood before claiming a native profile — cost if
wrong: extra private build/cache disk and investigation time, no product fallback.

Ruling: Pin the original platform float backends in addition to int8 Ruy — Ruy-only
changed degenerate511token Mac and511/512Linux results; Mac Accelerate24/24 now exact —
cost if wrong: larger build requirements and explicit Linuxlibgomp dependency.

Ruling: Use openblas-src/system directly, never ct2rs/system — the latter skips CT2
compilation and requests unavailableCUDA archives on Linux even in this CPU setup —
cost if wrong: native build fails visibly; no CUDA/Python workaround admitted.

Ruling: Bound normalization to the fixed profile's ordered scalar/array/object JSON
subset and reject floats/duplicates/unpaired surrogates explicitly — actual public
config/vocabulary need none; retain exact verified bytes rather than an unproven
Python-number formatter — cost if wrong: a future different/custom model requires
an explicit normalization extension instead of silently acquiring a wrong recipe.

## Tasks

Task 1: pending (independent oracle/fixtures)
Task 2: pending (native policy/preparation)
Task 3: pending (native runtime)
Task 4: pending (both-platform26gates/fresh review)

## Task 1 execution

BASE 0e1ee05d562b4b11a77ba98e5a626618d2530a2a. Read task-1-brief.
RED: task-1-red-complete.log, seven expected missing-module failures.
GREEN: task-1-green-first.log and task-1-green-refactor.log,13/13
(seven new oracle tests plus six unchanged original translation tests).
Implemented only migration oracle/fixture tooling; NO native product source/deps yet.
BothOS original29histories captured before product implementation; all5source/
derived pins, original3module hashes, full recipe and boundary counts agree.
Original511/512repeated-token OUTPUTS DIFFER BETWEEN OS: keep explicit per-platform
oracles, no cross-platform text equality. Private runtime24cases eachOS matched
its own original after correct backends. Kenmemory rust-migration-ct2-platform-float-backends saved.

Public fixtures: crates/ken-models/tests/fixtures/translation/{tiny,policy.json,unicode.json}.
Public evidence: docs/validation/rust-migration-2026-10-19/m2-translation/
{cases.json,reference.json,VIABILITY.json,IMPLEMENTATION.md}.
Tools: translation_reference.py,translation_fixtures.py,translation_unicode.py.
Tests: tests/rust_migration/test_translation_reference.py (7).

Additional full-project diagnostic run python-t1.log/xml was interrupted after
three socket failures in unchanged original tests. Actual worker logs prove
PermissionError socket.bind(Operation not permitted). Named failures:
- tests/kql2/test_automatic.py::test_new_cli_processes_reuse_service_and_return_updated_sources
- tests/kql2/test_automatic.py::test_automatic_client_handles_mcp_threads_and_budget_reset
- tests/kql2/test_automatic.py::test_cli_recovers_dead_owner_and_rpc_rejects_bad_requests
No tests/budgets/source were changed. Same3tests with proper local-socket permission
passed3/3 (python-t1-socket-recheck.log). Full suite now running with proper permission,
python-t1-prepared.log/xml, exec session42899. This is not final immutable26gate proof.
Do not repeat/relabel the restricted attempt as a passing run.

Next: await/read full-suite result; inspect own changes, verify1066originalhashes,
finish T1 plan checkboxes/commit/task-done13tests. Continue T2 via task-start/readbrief,
write RED before any product change. T2 additionally needs an out-of-order/nested
Unicode JSON public-usage fixture: original tiny/real config keys are sorted and
would not alone distinguish an incorrect sorting normalizer. Hand literal expected
bytes or independent original capture; never native-generated expectations.

PrivateLinux paths:
- own container codex-ken-rust-m2 as before (2CPU/3GB), Docker config own.m2;
- /app/.ken/rust-migration/m2/runtime-research/ct2-viability contains native binary,
  build-tools/cmake/data/bin, openblas-prefix include/lib, vendor, locks andalllogs;
- successful Linux staticprobe aa83ff385c3adc83ed6ccd85e4140146e1c78681c7ba08cb90b26abee1995ddf.
- CT2 compile env PATH=privatecmake:$PATH, PKG_CONFIG_PATH=prefix/lib/pkgconfig,
  DEP_OPENBLAS_INCLUDE=prefix/include,DEP_OPENBLAS_LIBRARY=prefix/lib,
  CARGO_BUILD_JOBS=2,CMAKE_PARALLEL=2. OpenBLAS-src/system early pkg-config return
  does not emit DEP paths, so explicit paths avoid ct2rs env unwrap failure.
- Use ONLY openblas-src/system, never ct2rs/system. Native compiled flags currently
  ct2rs(defaultfalse)+ruy+sentencepiece+[Macaccelerate/Linuxopenblas+openmp-runtime-comp].
- OpenBLASsource0.3.26 SHA4e6e4f5cb14c209262e33e6816d70221a2fe49eb69eaf0a06f065598ac602c68,
  verifiedofficialreleaseMD5bd496a1c81769ed19a161c1f8f904ccd,24,404,912B.
- NativeSPM0.13.2 embeds0.2.1, matches originalSPM0.2.1.
- Linux retained current and Ruyonly/failed attempts in host
  .ken/rust-migration/m2/runtime-research/ct2-viability/linux-viability-receipts/.
- Final Macnativee30e4b3f717e98f3301616976a1b16707dc8607acd95436a04725c68a7449af7,
  dependenciesonlysystemAccelerate/iconv/libc++/libSystem. Linuxonlygomp/stdc++/m/gcc/libc/loader.
- Original captures .ken/rust-migration/m2-translation/original-{macos,linux}.json.
  Linuxsource-of-oracle own /app/.ken/rust-migration/m2-translation/t1-source
  (not product/current-source final proof). All originalimports usefrozen reference-t4.
Task 1: complete (commits 0e1ee05..8f5a27b, tests: .venv/bin/python -m pytest tests/rust_migration/test_translation_reference.py tests/retrieval/test_local_query_expansion.py tests/retrieval/test_translation_preparation.py -q → .............                                                            [100%])

Full Python T1 sanity completed:15651passed,0failures,10unchanged historicxfail,
no missing original baseline IDs,70addedtestIDs versus original baseline. Raw
python-t1-prepared.log/xml and python-t1-result.json retained. Original1066hashes
verifiedunchanged. T1 completed0e1ee05..8f5a27b with task-done13/13.

Task2BASE8f5a27b49d4d6ccf2560ef47a101d24dd5161d72; task-2-brief read.
Policy RED actualunresolved public API task-2-policy-red.log; Unicode unit RED
4missing actual predicates/folder task-2-unicode-red.log. Implemented native
query_policy.rs/python_unicode.rs andembedded independentUnicode15tables,
workspace/onig6.5.3 defaultfalse (alreadylockedtransitive; lockdiff ONLY
ken-models directonig dependency). Original2438policy cases +6restoration and
sequentialcollision/independentplan tests GREEN3/3; whole-scalar digest GREEN1/1.
Additional source-derived completelexicon coverage retained in oraclefieldlexicon,
not a new runtime capability; strengthened native test covers each originalword,
its repetition and uppercase with adifferentanchor. Green/clippy logs pendingread.
No translation_model/preparation/JSON normalizer or CT2 productruntime yet.

Task2: Ruling: compatible_identity returns exactoriginalidentity object; add
compatible_revision(profile) for the separateSHA — avoids ambiguous wrapperblob
and keeps identity/hash ownership inmodel — cost ifwrong: futurecaller rename,
noinstalledcallerexists. Plan interface clarifiedbefore task2 started.

Nativepolicy strengthened checks: whole-scalar unit1/1 (1.28s), originalcorpus/
restoration/independence +full38-memberlexicon4/4, alltargetken-modelsclippy -Dwarnings
pass, fmtworkspacecheckpass. The firstlexicon attempt compiled before the generator
finished writing its newfield and therefore read the prior fixture(None); retained
firstlog shows3pass/1fixturefailure. Waited for generator completion, confirmed
lexicon38/cases2438, rebuilt exactsamecode:4/4pass. This was executor ordering,
not a productfix or changedexpectation; future dependent sessions must finish
before consumers are launched.

Task2preparation RED: task-2-preparation-red.log and-red-complete.log unresolved
TranslationModel/FrozenTranslationRuntime public API (12integrationtests writtenfirst).
Task2: Ruling: JSON declaration/normalization max4194304bytes andstandardserde128
recursion limit — actualsourcevocabulary1.34MB/config233B fit; concrete bound avoids
unbounded unsupported-profile parsing — costifwrong: futurelarger/customJSONprofile
needs anexplicitguard increase. Native testpins exact4MiB accepted/+1rejected.
Out-of-order/nestedUnicode fixture has independent handliteralbytes; separate
nonASCIIattribution recipeSHA2614c9... from independentPython beforeimplementation.

Task2nativeprep/model/orderedJSON implemented aftermissingAPI RED. First actual
runtime run task-2-preparation-first-runtime.log:10/12passed INCLUDING actual5file
registeredpreparation, atomicreuse/concurrency/ownership/regularity andnestedorder.
Two intended regressions FAILED: defaultrecipe6fcf... vs1af342..., andnonASCIIarray
metadata0a021... vs2614c9.... Cause: sharedassets::python_json delegatedArrays to
compactnonASCIIserde output, unlikePython separators/recursiveASCII. Added only
recursiveArray branch after observedRED, preservingObjectorder andStringowner.
Now combinedpolicy+prep GREEN running task-2-preparation-green.log (exec17442).
Task 2: complete (commits 8f5a27b..f4a93f3, tests: env KEN_TRANSLATION_SOURCE=/Users/andres/Projects/ken/.ken/rust-migration/m2/runtime-research/ct2-viability/source-cache/models--Prukario--opus-mt-es-en-ct2-int8/snapshots/ad91ad1697ea1761111ff4c179400796d085b347 cargo test --locked --offline -p ken-models --test query_policy --test translation_preparation → test result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 11.70s)

Task2 completed9d96acef policycut andf4a93f35 preparationcut, BASE8f5a27b.
BothfullRustworkspaces125reportedpasses/24sections,0failed/ignored; fmtandall-target
workspaceclippy passbothOS. Actual13prep/4policy/1wholeUnicode15unit executed.
Original13Python tests pass; original1066hashes unchanged. LinuxownSourceT2
fingerprint1c030b5f78e611fa6e8c8c64ff1456bcf2c7a9e8ebc5c4f20474a23ed3f54976
matchedROOT before documentationstatus edits. PublicTASK2.json/IMPLEMENTATION updated.
Task-done namedtargetcommand17tests passed andrecordedcomplete8f5a27b..f4a93f3.

Task3BASEf4a93f352d464bf3bffe85aefbfa27fe174bd0be. Task-3-briefread.
No Task3product source/deps/tests yet. ExistingprivateCT2probe NEVERcopyasproduct;
implementfreshafterRED. SPMcrate0.13.2 read actualfrom_serialized_proto(&[u8]),
encode returnsVec<PieceWithId{piece,id,span}>; decode_pieces usesCString perpiece;
fixedregisteredsharedvocabulary65000containsNO NUL pieces, so this limitation
cannotaffectfixed-model output (inputencoding length handlesNUL, actualrawcasepassed).
Processor upstreamunsafeSend/Sync declared; stillserializewholecoreusewithMutex.

Task3: Ruling: expose expand_detailed(query)->ExpandedQuery{text,trace:Option<TranslationTrace>}
with per-callownedprepared/tokens/hypotheses/decoded andhaveexpandforwardtext —
rawinference proof must observe the actual same product operation, never a second
probe-onlyimplementation orsharedlast-result cache — costifwrong: small extra
public diagnostic surface/ownedtraceallocation. PlanInterfaces clarified beforeRED.
PrivateCoreSession translate is real productmethod andcan beunit-tested against
24raworiginalhistories (inclplainEnglish/empty/degenerate511/512 notreachable
throughlanguagegate); publicraw-reference.json now preserves pre-product original
expectations separately from29publicexpand histories. Sourceexact5pin provenance
fromT1; finalT4mustbind thisnewraworacle too.

Task3 RED observed: task-3-red.log unresolvedLocalQueryExpansion (5realintegration
caller tests), task-3-core-red.log missingprivateNativeSession (24rawcore histories).
Implementedfresh query_expansion.rs: private retained80MBauthenticatedmaterialization,
CPU/int8/2threads/1replica C++pool +from_serializedSPM, directsourcepieces+oneEOS,
exactopts/ownedtrace, oneMutex throughloading/calls, retryableResultfailures, English
beforeI/O. Original privateprototype notcopied. Cargo deps fixedCT2rs0.10.1+SPM0.13.2,
Macaccelerate/Linuxopenblas+OpenMP COMP; directopenblas-src0.10.14/system only.
PrivatePRODUCTCargoHome prepared by copying publiccrates.io cachearchives/index
ONLY from rootcache andprivateviabilitycache; nevercredentials/config/uservenv.
Path:.ken/rust-migration/m2-translation/cargo-home. Use it plusprivateCMakePATH,
CARGO_BUILD_JOBS2,CMAKE_PARALLEL2 forTask3builds. Initialnativecompile/test running
exec77128, task-3-first-native.log; inspectbeforefurtherdependentwork.
AllproductRustcurrentlyuncommittedTask3WIP; Task2HEADf4a93f35 remainsgreen.

Task3firstnative build compiled allnewC++/Rust dependencies offline, then failed
E0107: storedTranslationOptions needs explicit<String,String> (actualupstream
struct hastwoAsRefstr typeparams). Readupstream signature, fixedfieldonly; retry
exec64283 /task-3-native-integration.log. NO testresults inferredfromcompile.
Cargo.lock adds53packages, ZEROexistingregistry package versions/checksums changed
(checkedoldHEAD/newlock package tuples). OwnCargoHomecopycompleted(88711closed0).
Nativeproductsourcequery_expansion.rs +5integrationtests +1private24rawcoreunit
arefreshTDDimplementation anduncommitted; planTask3stillopen. Rawcore unittest
mustrun explicitlyafterintegration andthenbothOS/workspace/fmt/clippy/integrity.

Task3integrationactual:4/5pass; all29historytestFAILS on511token QUESTION-prefix
history after~80s. No tolerance/expectationchanged. Actual restoredtext diverges
mid-generation, normalcases/English/retry/owneddata/concurrency pass. Private24
rawviabilitywasRELEASE/plainholaboundary, so cannotinferpublicquestionboundary.
Hypothesis toverify: C++DebugvsRelease floating-point compilation affects sensitive
longgreedy path; alternativect24.8.2vs4.8.3/version/policy mustnotbeassumedaway.
InspectingactualCMakeCaches/backendflags andrunningEXACTSAME producthistorytest
in --release(task-3-release-diagnosis.log); awaitactualresultbeforeanypolicyfix.
T3notaccepted; productsource/tests stillWIP. Initial4/5failure fullyretained.

Task3rootcauseexperiment: SAMEproductall29history test --release PASSED1/1,
4filtered,11.94s; build2m23s. task-3-release-diagnosis.log,78208closed0.
ActualCMakeCache diagnostic: debugcoreDebug/-g, prototypecorrectcoreRelease/-O3
-DNDEBUG; bothAccelerateON/RuyON/OpenMPNONE/samecompilerarch/deploymentflags.
Nooutput/fixture/tolerance changed. Added [profile.dev.package.ct2rs]
opt-level3/debugfalse tokeep C++numericalcoreRelease inRustdev/test too; fresh
normalprofile test runningtask-3-stable-core-integration.log. Mustverifyits actual
CMakeCacheRelease andall5tests BEFORE declaringcausefixed. Originalfullpublic
histories selectsourceIDs/hypotheses assertionsBEFORErestoredtextnow (sameassertions,
strongerfailurelocalization, noexpectedchanges). Ruling/provenancefinalizeafterGREEN.

CONFIRMED GREEN: normal cargo test withct2rs-onlyopt3/debugfalse passedALL5
integrationtests incl29originalhistories,102.83s; task-3-stable-core-integration.log,
81483closed0. SourceSPMremainsDebug, RustappremainsDebug; onlyCT2optimizedcore
changed. ActualnewCMakeCachect2rs-7b9548f9c45b18f7 isRelease/AccelerateON/RuyON,
oldfailing003600f5c9a44462 isDebug. Sameoriginalexpecteddata unchanged.

Task3: Ruling: keepct2rs C++coreRelease inRustdev/test via packageoverride
opt-level3/debugfalse — actualdefaultDebug altered511token greedytranslation,
sameproductRelease29casespassed, andisolatedct2rs-onlyoverride fixednormal5/5 —
costifwrong: longerC++builds andlessC++debug info; disablingtheoverride forfeits
registerednumericparity. NoRustoverflow/assertioncheck wasdisabled. CargoBook
profiles/test inheritsdev +cachedcmake0.1.58get_profile read toverifymechanism.
T4mustbindRootCargo.toml andrecordactualcorebuildpolicy, notassumeRustdebugflag.

CurrentSourceT3snapshot .ken/rust-migration/m2-translation/source-t3,
fullinputfingerprint7a351741306790c298a2b46a3234d9e166d1e01a8ff7d9cc028594dcb945cb8d.
Source/vendorinput-t3.tar.gz packing exec10284; waitbeforecopy. Allvendor cached
publiccrates gatheredOFFLINE successfully(task-3-vendor.log,56451closed0).
Private24rawcore unit running14254/task-3-raw-core.log. AfterreadGREEN:
Macfullworkspace(withall5preparedvars),fmt/clippy; LinuxsameSourceT3withvendor,
privateCMake/OpenBLASprefix+DEPpaths and2jobs; actualcppReleasecachechecked.
NO T3completion/profileacceptance untilbothOS testsread/committed/taskdone.

SourceT3archive delivered/extracted (74387/8067closed0), fullcopiedmanifest
verifiedALLbytes beforebuild; hostandLinuxfp7a351741...cb8d. Raw24coreunit1/1
GREEN confirmed; original/oracle13Python task3testsGREEN. Original1066hashverified.
Macfullworkspace71447 andLinuxfullworkspace76727 RUNNING. LinuxSOURCE:
/app/.ken/rust-migration/m2-translation/t3-bundle/source, vendor../vendor.
Linuxlog:/app/.ken/rust-migration/m2-translation/task-3-workspace-linux.log.
BuildSourceenv explicitprivateCMake/OpenBLASprefix/DEPpaths/jobs2;5model/corevars.
Do notredoRED orreimplement. Waitactualfullresults, thenfmt/clippyboth andcommit.

Task3 full Mac first runtime workspace confirmed131passes/25sections,0failed/ignored.
Macclippy found cloned_ref_to_slice_refs in the new translate_batch call; retained
RED task-3-clippy-macos.log. Read exact native generic signature and borrowed-input
lifetime: replace cloned one-element vector with std::slice::from_ref, same owned
trace/result. Fixed all-target workspaceclippy GREEN (52610closed0). No suppressions,
expected-output change or new behavior. Existing runtime tests are the regression
coverage; no implementation-mirroring clone test added. Fresh Mac full workspace
running58169/task-3-workspace-macos-fixed.log. New immutableSourceT3b fingerprint
b0504724e43743398de3dcaacf69de591edaf75e19a913942e46d91050fddf50; copy toLinux
must complete before verification/new build. PriorLinuxsource remains immutable
while its first fullsuite76727 runs. ActualLinuxCMakeCache Release/OpenBLASON/
RuyON/OPENMP_RUNTIMECOMP verified. Full13original/oracle tests re-running21187.

Task3 fixedsource firstMacfull invocation omitted socket permission; five existing
ken-core::health tests failed socket.bind EPERM at health.rs49/119 before model
targets. All five names/output retainedtask-3-workspace-macos-fixed.log. Samefull
command correctly elevated running57280/task-3-workspace-macos-prepared.log.
No code/test/timeout changed. Not an autoreview rejection. FirstPythonrecheck had
7oracle+3localtests=10passes (21187closed0); previous13included3originalpreparation
tests too. Finalexplicit13set withJUnit running8867, truthfulcount fromJUnit.

Task3 firstLinux fullworkspace76727closed0:131passes/25sections,0failed/ignored,
including29public+24raworiginalhistories exact. Fullrawlog copiedlocally. Fresh
fixedSourceT3b copied48418closed0 andverifiedALL5408manifestfiles beforeuse;
fmtLinux+Mac GREEN. FixedLinux fullworkspace thenalltargetclippy running15626,
logs task-3-workspace-linux-fixed.log/task-3-clippy-linux-fixed.log incontainer.
Macfixed fullpreparedsuite57280 running; clippyfixed52610closed0. Final13Python
JUnit verified13passed/zerootherstates. No stage acceptance inferred yet.
Private executable env wrappers macos-native-env/linux-native-env retaincomplete
prepared/model/CMake/OpenBLAS inputs; allscopedtothismigration, nouserenvmutation.

Task3 finalfixedSourceT3b verifiedbothcompleteRust131/25sections,0fail/ignored;
fmt+alltargetclippyBOTHOS GREEN. Linux15626closed0; copiedlogs/hashchecks andactual
CMakeRelease/backendflags retained. Mac57280closed0. PublicTASK3.json generated
onlyafterreadingbothcompleteoutputs andcheckingnativeinputsunchangedagainstthe
immutableb0504724manifest. Original1066verifyGREEN,13PythonJUnitallpassed.
Committed4f2e5e47 ONLY11ownedimplementation/test/dependency/docpaths. Nooriginal
orunrelatedworkstaged/committed. Finaltask-done runs deploymentRelease5tests.
Task3: Ruling: final completion command additionally uses --release — ordinary
workspace5/5andall131tests already passedbothOS, while actual deployment-profile
Rust also deserves a direct integration check — costifwrong: extra build time;
no normal-profile coverage is replaced or weakened.
Task 3: complete (commits f4a93f3..4f2e5e4, tests: .superpowers/sdd/2026-10-19-rust-m2-translation/macos-native-env cargo test --release --offline --locked -p ken-models --test query_expansion → test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 12.52s)

Task3taskdone54098closed0: deploymentRelease5/5passed12.52s; complete ledgerline
above. Task4started BASE4f2e5e47d02eeb99bb7bb0a5474f387ed3682743,briefread.
Task4: Ruling: add an owned ExpansionAttempt containing the normal Result and
optional actually encoded TranslationInput, and have expand_detailed consume its
Result — original failing position histories retain input tokens before inference
fails; the independent probe must observe those actual inputs without re-tokenizing
later or inventing trace data — costifwrong: small diagnostic API/one input clone
per translated call. No sharedlastresult state and no second inference path.
Task4: Ruling: include explicit native build prerequisites in typed preparation,
including CMAKE executable and Linux OpenBLAS prefix/header/archive identities —
model/probe paths alone cannot reproduce the platform numerical core — costifwrong:
more preparation configuration; missing/corrupt prerequisites fail acceptance
instead of being hidden by a precompiled target cache.

Task4ownedattempt TDD: missingexpand_attempt RED task-4-attempt-red.log; normal
expand/expand_detailed nowconsume ExpansionAttempt.result, actualcoretranslate
fills ownedTranslationInput BEFORE inference. Successfulltraceunchanged; English/
failedloadhaveNone. Newerror-input/recovery testcase plusold5 Release6/6GREEN,
62469closed0,12.56s. Private24rawunit adapted onlyto newownedinputobserverargument.

Task4comparator6unit tests GREEN, exactbothOSfrozenoriginalfixture expectations.
Wrongtokens/pieces/hypotheses/decoded/text/lexicalstate/errors/identity/backend/
recipe/artifacts/timings/peakenvelope rejected; platformselector rejects ambiguity.
NativeprocessinitialRED missingcompare function/probe example. Firstactual run
caught two tooling/setup errors: topdocumenthasoraclesonly/cases.json is separate
list; fakebinarytestoutputdircollidedwithfakefile. Bothfixedattheirownowner,
nooriginalexpectationschanged. NativeprobeunusedPathimportremovedafterwarning.
FixedactualMacprocess9/9GREEN85791closed0; task-4-process-fixed.xml/log. Includes
29actualnativehistories+freshoriginalreplay+independentfreshpreparation/cache reuse,
copiedbinary/sentinelPATH/systemAccelC++dependency audit; falsebinary/scripts and
malformedinput/expectedoutputinjection rejected; tiny English stayslazy. No26gate
acceptance yet. Probe consumes actualExpansionAttempt, never re-tokenizes failures.

Task4: Ruling: internal Rust artifact failures use ModelError::Artifact instead of
Python ValueError, with explicit missing-source/corrupt-artifact diagnostic mapping
in the comparator — native preparation owns the absent-source check; preserve the
original failure boundary, empty trace and lazy state, and require exact native
position-error messages — costifwrong: an internal caller depending on Python's
literal exception wrapper must adapt; no fallback or arbitrary error is accepted.

Task4typedinputs REDmissingPreparedNativeTranslation, then11/11input/priorEttin
preparation testsGREEN. PreparedTranslationBuild{cmake,optionalopenblas_prefix}
produces explicitCMAKE/PKG_CONFIG_PATH/DEP_OPENBLAS_INCLUDE/LIBRARY; typedtranslation
source/probe/build overrideambient, noos.environmutation. Optionaltranslation
keyword nowpropagatedthroughEttin/context/table/model/_validation_environment.
Nativebuildvariablesremovedfromcopiedbaseenv beforeexplicitforwarding; originals
stillstripallnativeKENkeys. Testscoverallfourcomposedboundaries.

Task4buildproof4tests GREEN73467closed0: missingmoduleRED then Cargo-selected
ct2rs0.10.1 outdir insidefreshrelease target only, actualCMake3.31.10/Release/
Ruy/platformbackend/compiler data; staleunselectedcache cannotstandin, missing/
wrongCMake/prerequisites andwrongflags rejected. EmptyCMakeoutput additionalRED
IndexError4806closed1; guardedemptylines fixnowinpartialtoolingGREENrun80697.
RealMacreleaseallbins/examples JSONbuild78198closed0; observedbuildproofsaved
 task-4-build-macos-first.json. Actualcompiler AppleClang21.0.0.21000334,
CMakebinary23563536B/SHA93f2fdbb4a671796a4660f51b1838e8a93ee903f8d345355440ce538fe187e0e.

LinuxrealOpenBLASsourcepreparation7668closed1 AFTERactualmake succeeded: helper
incorrectly assumedrootopenblas_config.h exists. OfficialpinnedMakefile.install
showsheadergeneratedonlybyinstall. Fixedhelperusesactualmakeinstallinsideprivate
stagebeforecopyingheaders; nocopied/fabricatedABIheader. FirstCLIerror andfullmake
attemptlogretainedincontainer. Fixedhelpercopycompleted; retry81099RUNNING,
/app/.ken/rust-migration/m2-translation/task-4-openblas-prepare-install.log.
Destination/app/.ken/rust-migration/m2-translation/openblas-t4, originalsource
archive.../m2/runtime-research/ct2-viability/OpenBLAS-0.3.26.tar.gz SHA/sizechecked.
Mutablebuild-driver-t4 containscopiedvalidationtoolssourceONLY; nevermodifyimmutable
source-t3b. DriverarchiveBSDxattrwarnings harmlessandretained; noacceptanceclaim.
NeedwaitactualhelperGREEN beforeusingnewprefixincandidatefreshnativebuild.

NEXT: compose translation_validate26gates+matrixTDD; addobservednative_identityto
processreceipt andassertit. Nativebuildproofmustconsume release.logCargoJSONfrom
actualbasegatehash; add--message-format=jsonto model_validate release command.
Thenmissing/corruptprereq tests/CI/helper; fullimmutablefreshbothOSall26gates,
originalbaselineID/fullPython/mypy/Rust/fmt/clippy/allpriorparity/benchmark/integrity.
CurrentTask4changesuncommitted; HEAD4f2e5e47. No finalreview yet, no wholeM2closure.

Task4: Ruling: bind all eligible crate src/data and tests/fixtures bytes in shared
native_source fingerprint — actualRED test showed embeddedUnicode JSON and model
fixture mutation left previousfingerprint unchanged; Rust includes/reads those
bytes, so sourcebindingwasincomplete — costifwrong: more artifact hashing and
intentional invalidation of oldsource receipts. Allpriorfullgates must berebuilt
asplanned. Use eligiblefiles toavoidignoredOSmetadata drift, keeporiginalsources.

Task4 composedvalidator REDmissingmodule, then13/13validator/build/inputtestsGREEN
84645closed0. translation_validate composes23prior+3newgates=26; currentFPs bind
raw/publicoracles/modeldefinition/source/preparedbytes andallnativeembeddeddata.
WholebaseEttinproof recursivelychecked, releasebindingmatchesprocess, selected
CargoJSONlogSHAcheckedagainstactualnestedreleasegate; requiresactualCMake/backend/
compiler/OpenBLASproof plusnativeidentity, oracleSHA, source/version/platform,
empty stderr, outsidecheckout/nochchildren/Linux1exec. Newidentityreceiptassertion
firstfailedKeyError21629closed1, thenactualprocess3/3GREEN6763closed0 incl29histories.

Fullmigrationtooling96/96passed77214closed0, nofail/skips; Macworkspacealltarget
clippy67019closed0. Original1066verify/diffcheckGREEN. CIYAMLparses; workflow now
preparesCMake3.31.10/privateOpenBLAS andsourceassets, forwardsnativepaths, runs26gate
validator/matrix. MacCIoriginalCT24.8.3 explicitlyprepared(separateCIvenvonly),
Linux4.8.2fromlock. No remoteCIrunclaimed. Guide/spec/planinterfacesupdated;
Task4checkboxesstillpendingfullmatrix+freshreview.

LinuxOpenBLASfixedmakeinstall81099closed0: actual22.008585218sbuild,
1051378BlibSHAe5e5011ce926b86236ff5e1943575e249bed46bac07e57d1a4aa8cfbb55a0f17,
samearchiveasprivateviability. Source24,404,912B/SHA4e6e4f5c...0268;
compiler/usr/bin/aarch64-linux-gnu-gcc-12 Debian12.2.0-14+deb12u1.
Preparedprefix/app/.ken/rust-migration/m2-translation/openblas-t4 authenticated
source/header/lib/pkgconfigreceiptken-build.json. Firstfailedattemptretained.

ImmutableSourceT4a fullfingerprintc312f13eccb077b5bcc884a3359c4b9919151412053904abdd9a81ec27534f80,
.ken/rust-migration/m2-translation/source-t4a. Allcode/tests/CI/configsourcesfixed
now; do noteditnative/validatoruntilfailure/reviewrequiresnewcandidate.
MacownauditGitinit/commit+venvlink35728closed0. ArchiveCOPYFILE_DISABLE=1/--no-xattrs
createdcompleted0 andcopied27867closed0. Linuxextract/verifyALLfiles/auditGitconfig
setupRUNNING(lasttoolcall; awaitexecIDfromresult). No acceptedprofileyet.
Macfreshallbins/examplesreleaseprebuild18173RUNNING, logtask-4-prebuild-macos-t4a.log.
Privatewrappermacos-acceptance-t4a setscandidatecwd/explicitCMAKE/oldpreparedmodels/
probevars, offlineCargo/RUSTUP_HOME; noCARGO_TARGET_DIR, per-candidatefresh target.
Source/currentfingerprintcomparison93773RUNNING; await/readbeforegate.
LinuxbaselineDIRconfirmed/app/.ken/rust-migration/m0-m1 (python-baseline.xml+mypy).
OriginalLinuxReference=/app/.ken/rust-migration/m2-context/reference-t4 asbefore.
NEXT: finishLinuxsetup, createT4runnerexplicitnewOpenBLASprefix/CMAKE/privateCargoHome/
probes/nativeRUSTUP_HOME=/usr/local/rustup/PYTHONPATH; freshprebuild. Afterboth
prebuildscomplete launchfull26gatevalidate_translationonBOTHimmutablecopies with
properMacsocketpermissions, log/outoutsidecandidate. NeedfullPythonIDs/mypy/Rust/
fmt/clippy/allpriorprocess+benchmark+integrity. PublishcurrentmatrixONLYafteractual
passes, thenONEfreshgpt-6-astra wholeplanreview/forknone asrequired. No per-task
agents/reviews, no wholeM2closure; continueotherM2/M3–M8afterprofileacceptance.

SourceT4a readyBOTH: all5418Linuxmanifestfilesverified, ownGit+venvsetup7114closed0.
Macprebuild18173closed0(2m41s), Linuxprebuild6857closed0(3m47s). Full26gatesNOW
runningMac49121 andLinux25867. LogsTHISDIR/task-4-gates-macos-t4a-prepared.log and
container.../task-4-gates-linux-t4a.log. Outputsacceptance-t4a/{macos,linux}.
BothfullPythoncurrentlyrunning; priorcontractsfinished. LinuxCppbuildproof6960
closed0 actualGNU12.2.0/Release/OpenBLAS0.3.26/Ruy/COMP; selectedcacheSHAd0753fab...
initialprovenanceJSONcopiedprivately. Matchingall24FPsverifiedhost/candidate/Linux;
native_sourceba58a3dc...721a2/validator1c29541a...884e. Noacceptanceclaimyet.
FirstMacgateinvocationfailedonlydriverrelativepathafterwrappercd, neverstarted
validator; absolutepathcorrectedbefore49121, failedlogretained. No source/test
changes afterimmutableSourceT4a freeze. Bothfullvalidatorsareproperlypermissioned.

T4a fullPythonMacXML examined:15670passed/10historicalskipped(xfail), no newfailures,
newskips ormissingbaselineIDs; mypy2previous/2current,0newerrors. Macfmt/clippy
completed; Rustworkspacecurrentlypublicqueryhistories. LinuxfullPythonlogfinished
15670passed/10xfailed/1warning in921.37s; Linuxtypingrunning. BOTHfull26gatesstill
running49121/25867; no completedmatrixyet. Candidate/native/validatorunchanged.

T4a MAC FULL26GATES CLOSED0 (49121): scope translation-local,passedtrue,26gates,
errors[],noexecution_error. Rustlog132passes/25sections,0failed/ignored confirmed.
Python15670passed/10historicxfailIDs,0newfailure/skip/missing; mypy2old/2current,
0new; fmt/clippy/profileprocesses/benchmark/integrity all26actuallypassed.
Linux25867stillrunningRust; no matrix/profileacceptance beforeLinux+freshreview.

T4aLinuxattempt25867CLOSED1, all26ran, failedrust_tests(exit124),parity_tests(exit1),
Ettinprep/parity andtranslationprep/parity. FullPython15670/10xfailpassed. Actual
Rustelapsed: compile2m14s plus~470sruntimeexceededunchanged600s deadline; timedout
atstatic_table,114reported/20sections, finaltokenization/preparationtargetsneverran.
ParentCargo timeoutleftonebriefchildfinishinglogaftertimeout(no liveorphanremains);
receiptcorrectlyfailed. No suitebudget increased/no tests skipped.

Actualparityfailures areEIO writes/sync ofmodel.onnx/model.bin inprivate/tmp
preparation; no token/hypothesis/textdifference. HostAPFSwas805Mi→504Mifree(100%),
Dockerthinfilesystemreported377Gvirtualfree; cgroupoom/oomkill0. Hoststoragepressure
confirmed. RemovedONLYoursRoot/target/debug7.5GdisposableRustbuildcache after
assertnooriginalmanifestfileunder target; source/currentcandidate/release/models/
trash/originals preserved. Cleanup45382closed0, host8.2Gifree afterward.
FirstfailedLinuxacceptance-t4a/linux outputsunchangedretained.

Linuxprecompilealltestexecutables cargo test --locked --offline --workspace
--no-run CLOSED0. AddedsameexplicitpreparationtoCI (CIonly, outside24runtime/tool
FPs; T4a runtime/source unchanged). Ruling: compiletestbinariesduringprerequisite
preparation before600s executiongate — coldcompile2m14scausedtheactualdeadline
failure while actualruntime~470sfits; keepALLtestsand600s limit — costifwrong:
extra preparationtime; colderunprepared callersstillfailthehonestdeadline.
I/Ofsync100MBdiagnosticcurrentlyrunning(lasttoolresult). NeedactualhealthyI/Oand
repeatrealEttin/translationprocesssmokes BEFOREpayingforsecondfullLinux26run.
Newfullattemptmustseparateoutlinux-preparedandretainfailedattempt. No native/
validatorcodechange, soMac26proofstillcurrentNativeFPba58/validator1c29.

Postcleanup100MBwrite+fsyncdiagnosticCLOSED0. ActualEttin+translationnativeprocess
smokes33228CLOSED0/2passedwithfreshoriginalreplay (readXML,noerrors/skips). Confirms
EIOresolved; no nativecode/expectedresult/stderr/tolerancechanged. LinuxfreshFULL26
retry95399RUNNING, output.../acceptance-t4a/linux-prepared, logcontainer...
/task-4-gates-linux-t4a-prepared.log. Runtime/sourcecandidateSTILLT4a c312f13e;
all24currentFPsunchanged. Failedfirstattempt.../acceptance-t4a/linux retained.
Mac26CLOSED0proofpublished11filesdocs/.../m2-translation/macos; all65rawevidence
fileshashmanifest/privateoutretained, no environmentcache/weightscommitted.
MustawaitactualLinuxfullpass beforematrix/taskdone/finalfreshreview.

Linuxretry95399fullPythoncompleted15670passed/10historicxfail/1warning888.83s.
FreshXMLbaselinecomparisonverified0newfailures/0newskips/0missingIDs; Linuxmypy
0previous/0current. Rusttestpreparationnow0.16s(actualFinishedtestprofile), leaving
unchanged600sforactualsuite. Rustcontexttargetcurrentlyrunning. No app/native/
validator changes sinceT4a; no resultclaimbeforeall26closed.

LinuxretryRustworkspacecompleted132passes/25sections,0failed/ignored, noFAILEDor
validationtimeoutmarkers. Preparation0.16s preserved600s executionlimit. Native
processparity-testsnowrunning; full26stillpending95399. No sourcechanges.

Linuxretry95399CLOSED0: all26gatesactuallypassed, errors[], noexecution_error.
FullPython15670passed/10historicxfailIDs,0newfailures/skips/missing; mypy0old/0new.
Rust132passes/25sections/0failed/0ignored, actual486.598s belowunchanged600s.
Allpriornativeprocess/model/table/context/Ettin/benchmark/integrity gatespassed;
translationnativeoutsidecheckout/sentinelPATH actual1exec/emptystderr. Actual
CMakeRelease/OpenBLAS0.3.26/Ruy/COMP/GNU12.2.0 proofboundtoCargoselectedoutdir.
All24FPs matchcurrentRoot+bothcandidates. Linux11publicfilespublished with66raw
artifacthashmanifest; Mac11/65 retained. Original1066hashesfreshverifiedunchanged.
MatrixCLIprintedpassedtrue/errors[]; MATRIX.json reportsTranslation_acceptedtrue,
M2_acceptedfalse. FirstfailedLinuxattemptretainedunchanged.

Ruling: Perform the one whole-plan review in the executing-plans final phase
after Task4 task-done, leaving the review checkbox pending until then — task-done
records the actual both-platform26gate contract and the mandatory final review
remains a separate closure gate — cost if wrong: a review correction needs a new
immutable-source validation, with extra time; no premature profile promotion.

Publication note: first Linux publication script used the wrong XML basename
python-full.xml and stopped after copying receipt/logs/manifest. The real gate
produces python-final.xml; corrected publication reads that existing XML, then
finishes measurements and verifies original integrity. No validation/source/test
change, and no failed attempt was overwritten.

# Linux x86_64 native CPU runtime cores

The user explicitly requests x86_64 support for the migrated engine. Linuxx86_64
is the current target. Grammar and denseBLAS prerequisites are accepted;next
establish authenticated native ONNX/Torch CPU cores,then complete x86model/index/
retrieval acceptance. This first runtime slice must not claim those later gates.

Current Rust declarations already accept x86_64. Preparation is the obstacle:
context_compare.core_for_platform only maps ARM;transformer_prepare picks Torch
by OS alone,so adding another Linux entry would still choose ARM. Native ONNX
callers compile an ignored historical two-ARM registration. Old records/receipts
must remain untouched and available to their archived validators.

Executor choice: canonical versioned ONNX resource metadata plus the existing
Torch-core registry,with additional x86records and unchanged ARM records. A pure
native_target(system,machine) owns canonical host identity;Torch selection owns
exact backend/OS/architecture matching. Model inference,tokenization,numerical
bounds and model catalogs remain their existing owners. Reusing generic OS-only
selection risks the wrong ABI;adding x86conditions independently to every caller
would duplicate the rule. No new trait/crate/framework is needed.

Representative use:core_for_platform(registration,'Linux','x86_64') returns the
unique pinned ONNX1.25.1/API25 record;transformer_core(registry,'Linux','x86_64',
 'torch') returns its CPU2.9.0 native closure. Missing/duplicate/foreign targets
reject;there is no ARM fallback. Existing canonical ARM targets retain identity.

Native sources:official PyPI onnxruntime1.25.1 CPU wheels and official
https://download.pytorch.org/whl/cpu/torch/ Torch2.9.0CPU wheels. The x86Python
package may use the explicit2.9.0+cpu packaging suffix;record that actual source,
verify the SDK/runtime's actual core version rather than relabeling it. Preserve
upstream2.9.0,ORT1.25.1/API25,Rust1.95.0,Python3.12.9/Unicode15,tch0.22.0 and all
Cargo versions. No CUDA/libpython libraries may enter the native closure.

Authenticate source wheel SHA from official metadata before extraction;pin
selected library bytes/SHA,architecture,licenses and source provenance. Keep
archives,SDKs,logs locally;only consumed registration/provenance metadata belongs
in Git. Preparation uses a fresh explicit destination and preserves foreign
existing bytes. Python/uv may prepare data;native tests run standalone libraries
without importing Torch/ORT Python or spawning Python. Reuse existing strict SDK
copying and native loaders rather than a second authentication implementation.

Verification:outside-in target selection RED→GREEN including mixed Linux records,
exact retained ARM digests,wrong SDK/binary/bytes failure without publication,
actual x86ONNX API loading and actual standalone native Torch backend tests;
complete affected tooling and native runtime tests on allthreehosts with pinned
SDKs,fmt/strictClippy. Numericalmodel tests using old ARM goldens must not be
reported as x86model acceptance. Fresh x86model observations and full indexing
history are subsequent required slices. Existing fullM4sourcepiece/syntax gates
remain regression obligations,not a substitute for runtime tests.

One fresh final whole-plan review,one Important/Critical TDDrepair pass if needed,
no implementation agents/no routine approval stop. No original recapture,no
oldreceipt rewrite,no installedKen replacement,merge,release or tag. After this
slice continue complete Linuxx86_64validation of models,indexing and migrated
retrieval before returning to remaining M4dcomposition. M4/global remain false.

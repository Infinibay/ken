# Requested-piece ranking calibration — prospective development protocol v147

The public145 default scored177/200top1 on the now-consumed independent cohort,
with symbols38/50. Only aggregates were exposed to the implementer. No individual
query/Gold from that cohort will be used for fitting or model selection here.
Original exposed200 stage diagnosis: native170, piece191, neural168, final191;
per-kind native/piece/neural/final:class44/50/47/49,symbol45/45/44/46,
module43/49/39/48,file38/47/38/48. Thus unconditional equal-rank fusion loses
some strong native/piece decisions and cannot express score margin/confidence.
It also bypasses requested-piece learning for symbols. Three known original
misses are retrieval failures and cannot be fixed by permuting ten candidates.

Hypothesis: a small source-agnostic calibration model can learn when native,
piece and neural evidence is reliable, retaining real margins instead of using
only equal reciprocal ranks. Reuse existing frozen signals; no extra encoder,
GPU, model calls, source text generation or query-specific exceptions. The pool
must remain the same ten canonical units. Identity and source checks unchanged.

Development: original exposed typed200 plus new exposed symbol200 curated from
source-only before ranking, with first SHA256(repo+'\0'+path)byte<128 and opaque
375file exclusions. Fresh balanced200 reserve uses complementary>=128partition;
Gold private, never selects this model. Existing consumed independent200 is
feedback only, not a new acceptance test. No private rows are read.

Capture all numeric features and model scores without labels using frozen145
public API/source and verify original answers exactly match closed real MCP145.
Neural input text remains v102; presentation remains independent.

Two predeclared bounded development candidates, same fixed original fitting
recipe (Lambdarank160trees,15leaves,min_child40,lambda2,learning_rate.08,
truncation5,1thread,seed42):
A. Low-dimensional score calibration: native score/rank/margins, piece
score/rank/margins, neural logit/rank/margins, RRF rank, request kind, exact and
source test/data roles. All features query/candidate numeric source evidence;
no repo/path text/query IDs/Gold. Define exact schema before label fitting.
B. Same calibration plus existing262 requested-piece features, including their
source lexical/semantic coverage. No new embeddings or pretrained weights.
Fit/score leave-one-repository-out on all development, retaining every query in
reports including missing-positive pools. Positive-containing training groups
only. Equal total training query weight per piece type; no query-level tuning.
Select better observed overall held-out top1; tie chooses A. Require original200
>=180/197 and new-symbol development held-out >=90% before final reserve run;
otherwise diagnose missing signals before any private reserve evaluation.
Final production uses one pooled model with the selected fixed recipe. No
runtime fold/repository routing. Export and bit-exact NumPy-vs-LightGBM checks.
Do not claim pooled development scores as independent validation.

Every behavioral adjustment is measured separately on original200; retain top10
membership and CPU/RAM envelope. Freeze final full public CLI/MCP source/models,
close all new reserve captures, independent scorer preflight then single Gold
opening. Required outcome >=90%top1,>=98.5%top10; report pertype/language/intent,
latency/RAM, no lowered criteria. If it fails, report failure and keep reserve
status consumed before any further development.

Feature-schema checkpoint before any new development fitting: CALIBRATION_FEATURES has34columns; FULL_FEATURES adds262existing source columns (296total). Exact definitions in experiments/search-engine/score_calibration.py, SHA256 4e6eb5dd419e5a234c9b5abac99020ed8522eb5c77ca35ad240aa15d5643ff3f. Numerical alignment/finite/stable-tie tests first failed10/10 with missing calibration_features, then all10passed. Frozen145source and original actual public MCP order remain guarded by observer.

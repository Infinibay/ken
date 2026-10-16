# Production static encoder extraction

The public default is not fully integrated yet. This slice makes the winning
static encoder portable and shares its exact implementation with the benchmark
compatibility name. It does not claim that an embedding alone achieves90%.

PotionCode16Mv2 at e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b runs as a native
Model2Vec table:256dimensions,float16weights,normalizedfloat32outputs,no batch
padding/hidden tokenizer truncation,512token cap,batch1024,no multiprocessing.
Public data files are downloaded at immutable revisions, then size/SHA256
checked before use; there is no runtime Torch or remote Python model code.
Existing project model pins and the global recommendation remain unchanged in
this slice; default promotion waits for the complete public pipeline.

45real-source/syntheticinputs produced bit-identical vectors and identical
registered profile identity to frozen134, including empty,unknown,long,Spanish
and Japanese inputs. The runtime usednumpy2.4.4,model2vec0.9.0,tokenizers0.22.2
and safetensors0.8.0. New filesystem tests use a real tiny native static model,
verify same-size corruption,offlinecache handling and transformer-free imports
in an isolated subprocess. Existing benchmark assertions remain intact.

A fresh frozen complete200query replay then used the extracted implementation
as its only ranking-path change. All200returned cards,units,pool hashes and
all native/piece/final orders equal134. Therefore identity is still180/200
(90%) and native top10 membership/recall remain197/200(98.5%). No new Gold
was read. Frozen source receipt:
93c08ae1ffa5f312b44f57b5f89a98714fabd88fc7f04bb9c8de740dd88f90ee.

Observed p502435.639ms,p953713.356ms,peakRSS2106949632bytes. These times are
descriptive: small filesystem/model-boundary tests and metadata downloads
occurred during the run. They are not evidence of another performance gain.
Prepared assets/load/warmup remain separately recorded.

Full compatibility suite:14859passed,10existingexpectedfailures in504.29s,
before final corruption/context probes.57embedding/profilechecks subsequently
passed with the pinned tokenizer. Additional contextual/translation components
are a following slice and need actual pretrained parity and their own replays.

35gzip payloads and a byte manifest in output/checkpoints/production-static-v136
preserve frozen overlays,all actual outputs/performance,parity audit and queue
controller; every archive was decompressed and checked. The new200controls
run public-only with frozen132/134; their Gold is still closed. The complete
public production arm must be frozen and closed before independent grading.

Model sources: [PotionCode16Mv2](https://huggingface.co/minishlab/potion-code-16M-v2),
[Model2Vec](https://github.com/MinishLab/model2vec).

# Same-weight FP32 control before another ranking model

Development diagnostic, not private acceptance. v103 source-free tests showed
INT8 batch-dependent scores while the same17M FP32 graph was stable. Test
whether that numerical difference matters on the actual200 queries before
discarding the small model or selecting a larger one.

Use exactly the closed v102 baseline top10 cards, expanded queries and exact
bypass, not new v105 evidence. This isolates precision from changed content.
Same published revision/tokenizer/head, pad50283, CPU2intra/1inter, batch4 and
max512 pair tokens. Reuse the verified CPUReranker, no Torch or GPU. Three fixed
orders: raw FP32, RRF60 with equal Ken/model ranks, and RRF60 with75%Ken/25%model.
Ties retain native positions. No candidate is removed or added, no fit or
hyperparameter selection; all arms and outputs are retained. No Gold in producer.

Record truncation, load, scoring-only latency and whole replay-process peak RAM;
never label those complete Ken pipeline costs. Once ALL outputs close, identity
may be compared with the old INT8 arm and original Ken order. Any new utility
claim requires exact-opinion reuse or independent current-card blind judgments.
The new acceptance reserve remains closed. No default/model adoption follows
from this diagnostic; successful evidence and end-to-end resource checks remain
necessary. Same-corpus identity gains cannot substitute for90%joint utility.

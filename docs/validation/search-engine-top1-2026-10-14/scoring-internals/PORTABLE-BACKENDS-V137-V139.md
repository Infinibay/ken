# Portable CPU model preparation and inference

These support components are implemented and tested, but the complete public
search default is still pending. They remove benchmark-workspace model paths
from production loaders and keep search math unchanged.

- ContextEncoder: fixed CodeRankEmbed INT8 source/tokenizer,raw768CLS,CPU2,
  batch1,512tokens,no batch padding.8actual source-free vectors are bit equal to
  the original adapter. Model identity remainsaed8c3a8ed338b26f9fd61c5cb6798687d5700dae60fe71dfc2be4e6356512ed.
- Translation: pinned public Prukario CT2INT8 has the exact measured model/SPM
  bytes. Config/vocabulary contain equal JSON values; deterministic formatting
  reproduces all measured files and expansion identity.4real source-free
  translations equal the old adapter. No Torch conversion or new weights host.
- Neural preparation: pinned public FP32 backbone plus full published head
  assembles to the existing274035078B graphSHA
  8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf.
  Includes CLS,Dense,exactGELU,LayerNormeps1e-5,Dense and raw logits.6actual
  source-free scores are bit equal. No Torch/transformers are imported.
- Neural inference: batch1/CPU4/512,published right padding,one finite score per
  native document,max10. Empty pools require no assets; long queries fail with
  an actionable message. Preparation/cache publication is atomic and verified.

Each change was then run separately across all200original questions:137context,
138translation,139neural scorer. Every returned card,unit,pool hash and all
native/piece/final orders equal136(and134). All three preserve180/200top1 and
197/200top10, including exact native membership. No new Gold was opened.
Preparation/load/warmup remain separate from prepared query timing. These are
functional parity results, not an isolated new speedup or public-default claim.

Full compatibility suite:14882passed,10preexistingexpectedfailures in498.50s.
Follow-up47focused tests cover native tiny static models,real tiny ONNX graphs,
complete head math,offlineasset handling,source corruption,padding,cardinality
and actual expansion interfaces. Mypy348sourcefiles passed. Additional piece
catalog/card work follows separately. Gzip checkpoint portable-backends-v137-v139
contains139payloads,1188338B,manifestSHA
1a1cb59e6bbd51ef48a222a2647974aec53809c001a61ec3adee0860ce180121.
Every archive was decompressed and checked. It also preserves CLOSED UNGRADED
new200baseline132/optimized134 outputs and source/runtime receipts. No private
reference payloads are included. Complete public production arm must be frozen
and closed before the independent scorer opens those references.

Sources: [CodeRankEmbed INT8](https://huggingface.co/mrsladoje/CodeRankEmbed-onnx-int8),
[public CT2 weights](https://huggingface.co/Prukario/opus-mt-es-en-ct2-int8/blob/ad91ad1697ea1761111ff4c179400796d085b347/model.bin),
[published Ettin model](https://huggingface.co/cross-encoder/ettin-reranker-68m-v1/tree/d166fa88ddde3c42bc3ee92f7df476d941c8204a).

# Tokenizer fixtures

`potion-tokenizer.json` is unmodified public model data from
https://huggingface.co/minishlab/potion-code-16M-v2/tree/e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b
(MIT). SHA-256:
`107bbdcbad4bff1d299b7a4c3a2fb17c52890688b7dd0e4c9deab79d3c4f3d45`.
Keeping this 1 MB tokenizer fixture permits exact public token tests offline,
without requiring the 32 MB weights for unit tests.

`policy-tokenizer.json` is a synthetic WordLevel tokenizer with added UNK/PAD,
five tokens, serialized padding length 8 and truncation length 1. Tests require
the native Model2Vec policy to disable both hidden limits before use.

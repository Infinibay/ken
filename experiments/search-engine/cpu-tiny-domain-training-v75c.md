# Tiny adaptation75c: pretrained cache tensor serialization boundary

All75b/75 parameters, expected producer bindings,16-fold exclusion, pause before
fit, four controls, tie rules, budgets and unchanged acceptance criteria apply.
75b failed before any fit while comparing cached tensor key sets. The official
checkpoint includes one additional nonpersistent `bert.embeddings.position_ids`
buffer that Transformers4.57 does not save; its41 persistent tensors match the
cached official-base export. Preserve75b's failed output/freeze/script.

75c requires this sole official extra buffer to equal the exact canonical
`arange(512).reshape(1,512)`, then compares all41 remaining tensor names, shapes,
dtypes and values exactly with the cached native model. No tensor or prediction
is changed. Still require hash-bound official assets, graph/export/source/cache
receipts and16 label-free bit-identical live pair probes before independent
pre-fit review. No fit or quality inspection preceded this serialization fix.
No model, training, mining, scoring or acceptance parameter changes.

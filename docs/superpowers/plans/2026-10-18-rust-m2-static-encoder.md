# M2: Verified Assets and Native Model2Vec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Native execution is the user's preserved choice.

**Goal:** Ejecutar el encoder Potion registrado con artefactos, tokenizer y aritmética nativos, demostrando equivalencia con la referencia congelada antes de portar consumidores.

**Architecture:** `ken-models` posee registros/bytes verificados, tokenización y pooling. Un probe de validación consume ese mismo motor; tooling Python prepara expectativas y compara procesos, sin formar parte del runtime Rust. Otros backends y datos se mantienen explícitamente pendientes en M2.

**Tech Stack:** Rust 1.95.0/edition 2024 y workspace existente; tokenizers =0.22.2 sin defaults, feature onig; safetensors =0.8.0; half =2.7.1; sha2 =0.10.9; serde/serde_json/thiserror/tempfile del workspace. Sin HTTP, Torch, ONNX ni Python dentro de este corte de producto.

**Spec:** [Contrato M2 de modelos](../specs/2026-10-18-rust-model-runtime-design.md) y [contrato general](../specs/2026-10-18-rust-migration-design.md).

## Global Constraints

- M1 se acepta antes de ejecutar este plan. Su revisión independiente se resuelve antes de acumular nuevos consumidores.
- Rama `codex/rust-migration`; preservar todos los originales y cambios previos. No sustituir `ken` ni sus integraciones.
- Sin fallback Python, stubs, skips por falta de modelos ni mezcla de espacios. Un error de preparación falla explícitamente.
- Potion: revisión `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b`, artefactos y SHA-256 del registro original; ninguna revisión flotante.
- Tokenizer sin padding/truncado oculto; conteo sin límite; encode usa política Model2Vec y límite 512, lotes de 1024.
- Conservación de tipos F16/F32, media, normalización y salida F32. Registrar promociones por fila vacía y caché de términos.
- Identidad compatible y runtime efectivo se informan por separado; no fingir paquetes Python instalados para justificar hashes.
- Linux/macOS observados; CPU obligatoria. La aceptación de este corte no acredita otros backends ni cierra M2.
- Nuevas dependencias exactas, lock compartido, fmt/clippy sin supresiones y tests sin ignorar.

## Review Focus

1. Un registro válido y bytes cambiados entre verificación y carga no deben ejecutar datos distintos de los acreditados. T2 usa bytes propios verificados.
2. Caracteres Unicode, UNK y tokenizer con política serializada no deben cambiar la secuencia por usar bytes, special tokens o truncado implícito. T3 fija las fronteras.
3. Un texto vacío dentro del lote cambia el dtype de normalización de sus vecinos en el oráculo; T4 prueba esa promoción y los límites 1024/1025.
4. Repetir términos ya cacheados no debe perder copias independientes, recencia o el presupuesto de 8 MiB/8192 entradas. T4 prueba historia de llamadas y whitespace Unicode/C0 reconocido por Python.
5. Un probe que sólo importe el motor pero use Python para producir salidas no acredita inferencia nativa. T5/T6 exigen proceso real, PATH vacío, dependencias y traza Linux.

## Archivos y responsabilidades

| Archivos | Responsabilidad |
| --- | --- |
| `tools/rust_migration/model_reference.py`, `tests/rust_migration/test_model_reference.py` | Captura independiente de entradas, tokens, outputs y huellas del oráculo |
| `crates/ken-models/{Cargo.toml,src/lib.rs,src/assets.rs}`, `tests/assets.rs` | Registro y bytes verificados; identidad compatible |
| `crates/ken-models/src/{tokenization,model2vec,term_cache}.rs`, `tests/{tokenization,model2vec}.rs` | Política léxica, aritmética y caché con sus propietarios |
| `crates/ken-models/examples/model_probe.rs` | Protocolo de validación, sin añadir comandos incompletos de usuario |
| `migration_tests/test_model2vec_parity.py`, `tools/rust_migration/model_compare.py`, `tests/rust_migration/test_model_compare.py` | Paridad de procesos y controles negativos |
| `docs/validation/rust-migration-2026-10-18/m2-static/` | Casos fijados, evidencia, medidas y decisiones |
| `.github/workflows/rust-models.yml`, `docs/rust-migration.md` | Validación independiente y reproducción del primer perfil |

### Task 1: Fijar casos y capturar el oráculo real

**Interfaces:** `capture(reference: Reference, snapshot: Path, output: Path) -> dict`; CLI `python -m tools.rust_migration.model_reference --reference PATH --snapshot PATH --out PATH`. Verifica el registro Potion original y ejecuta un hijo del intérprete congelado; devuelve identidad, versiones reales, artefactos, entradas, tokens, salidas F32 y orden de llamadas.

- [ ] Escribir `test_capture_uses_frozen_model_and_rejects_drift`: fixture sintética de tokenizer/pesos y proceso real; rechazar referencia alterada, artefacto cambiado y ruta no fijada. `test_model_cases_pin_boundaries` exige vacío/espacios/español/NFC/NFD/emoji/código/UNK/511–513 tokens/lotes mixtos/repeticiones/1024–1025 entradas, sin quitar casos fallidos.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/rust_migration/test_model_reference.py -q`; observar FAIL por módulo ausente.
- [ ] Implementar captura y escribir `m2-static/cases.json` antes del motor Rust. El hijo debe demostrar `ken.__file__` congelado y `model2vec==0.9.0`; validar todos los bytes registrados. Identificar cache público local o preparar sólo los datos públicos fijados en un directorio de la tarea, sin tocar fuentes.
- [ ] Ejecutar los tests y capturar salidas reales. Fijar tolerancias antes de Rust: tokens exactos; F32 atol=2e-6/rtol=1e-5/coseno>=0.999999; F16 atol=2e-4/rtol=2e-3/coseno>=0.99999. Son cotas por redondeo F16 y acumulación; no certifican ranking. Cero esperado se compara exactamente; NaN/Inf fallan. Guardar todos los casos y la precisión del oráculo.
- [ ] Commit sólo tooling/casos/recibo público de esta tarea. Gate: tests anteriores y verificación de originales/referencia.

### Task 2: Registros y artefactos verificados

**Interfaces:** `ModelAssets::from_json(&str) -> Result<ModelAssets, ModelError>`, `fingerprint(&self) -> String`, `verify(&self, snapshot: &Path) -> Result<VerifiedSnapshot, ModelError>`; `VerifiedSnapshot::artifact(&self, name: &str) -> Result<&[u8], ModelError>`. Los bytes usados son los mismos que se verificaron; `VerifiedSnapshot` no es construible con datos no verificados desde fuera del módulo.

- [ ] Escribir integración `assets.rs`: fingerprint idéntico al registro Python, Unicode escapado en JSON compatible, tamaños/hashes exactos; rechazar paths absolutos/vacíos/`.`/`..`, duplicados, hashes/revisiones inválidos y bytes cambiados. Aceptar symlinks de cache a blobs con datos correctos; cambiar el archivo después no cambia bytes ya acreditados.
- [ ] `cargo test --locked -p ken-models --test assets` debe fallar porque el miembro no existe.
- [ ] Añadir el miembro y dependencias exactas junto con implementación funcional de validación y errores. El codec de identidad reproduce JSON Python ordenado con espacios/ASCII para los tipos del registro; no necesita un serializador numérico general. No descargar modelos desde este módulo.
- [ ] Ejecutar tests, `cargo fmt --all -- --check`, `cargo clippy --locked --workspace --all-targets -- -D warnings`. Comparar hash real del registro con Python y verificar originales.
- [ ] Commit propio; cerrar tarea con `cargo test --locked -p ken-models --test assets`.

### Task 3: Tokenización y límites exactos

**Interfaces:** `ModelTokenizer::load(bytes: &[u8]) -> Result<Self, ModelError>`; `token_ids(&self, text: &str, max_length: Option<usize>) -> Result<Vec<u32>, ModelError>`; `token_count(&self, text: &str) -> Result<usize, ModelError>`. Mediana por longitudes Unicode del vocabulario ordenado por ID, política UNK del modelo, special tokens desactivados; deshabilitar padding/truncation serializados.

- [ ] Escribir tests `matches_reference_tokens`, `bounded_encode_preserves_character_prefix_and_unknown_policy`, `count_has_no_hidden_limit`, `unicode_length_is_not_utf8_bytes`. Usar tokens del T1, además de tokenizer sintético distinguible; no definir expectativas leyendo el resultado Rust.
- [ ] `cargo test --locked -p ken-models --test tokenization`: observar FAIL por interfaz ausente.
- [ ] Implementar la política de Model2Vec 0.9.0: prefijo de caracteres si hay límite, tokenize, quitar UNK, limitar IDs. No eliminar PAD real ni añadir prompts.
- [ ] Ejecutar tests y contrastar IDs de los artefactos reales. Rechazar tokenizer corrupto y vocabulario incompatible con los pesos.
- [ ] Commit; gate de tarea `cargo test --locked -p ken-models --test tokenization`.

### Task 4: Pooling, normalización y caché de términos

**Interfaces:** `Model2VecEncoder::load(snapshot: &VerifiedSnapshot) -> Result<Self, ModelError>`; `dim(&self) -> usize`; `token_ids(&self, text: &str, max_length: Option<usize>) -> Result<Vec<u32>, ModelError>`; `embed_passages(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ModelError>`; `embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError>`. El encoder posee pesos/tokenizer y caché; la API no obliga a conservar el snapshot.

- [ ] Escribir `mean_and_norm_match_weight_dtype`, `empty_row_promotes_its_batch`, `batch_boundary_1024_is_preserved`, `cache_matches_call_history_and_returns_independent_values`, `corrupt_shapes_and_nonfinite_weights_fail`. Pesos sintéticos no simétricos distinguen media/suma y normalización F16/F32; incorporar salidas del oráculo.
- [ ] `cargo test --locked -p ken-models --test model2vec`: observar FAIL por encoder ausente.
- [ ] Implementar carga de `embeddings` F16/F32 safetensors, forma y vocabulario registrados, pooling de IDs y normalización con los redondeos observados. Validar salidas finitas. Mantener 1024 entradas por lote y orden.
- [ ] Implementar caché sólo para texto no vacío de hasta 128 caracteres sin whitespace Unicode: 8*1024*1024 bytes, 8192 entradas, coste `vector.len()*4 + utf8.len() + 256`, recencia y copias; no acumular pasajes. Tests de presupuesto y concurrencia usan vectores/entradas suficientes sin cargar modelos adicionales.
- [ ] Ejecutar tests, fmt/clippy y contraste real T1. Documentar cualquier divergencia antes de decidir; no ampliar tolerancias para hacer pasar el port.
- [ ] Commit; gate `cargo test --locked -p ken-models`.

### Task 5: Probe nativo y comparación de procesos

**Interfaces:** ejemplo `model_probe` recibe un JSON por stdin con registro/snapshot/lista ordenada de llamadas (`tokens`, `count`, `passages`, `query`), devuelve un JSON con identidad compatible, runtime efectivo, dimensión y resultados. Error: exit 1, stderr explícito, sin stdout exitoso. `compare_models(reference, native_probe, snapshot, cases, output) -> dict` exige IDs completos, tokens exactos y tolerancias del T1.

- [ ] Escribir `test_empty_or_mutated_probe_cannot_pass`, `test_wrong_token_order_and_nonfinite_vectors_fail`, y pruebas de proceso real en `migration_tests/test_model2vec_parity.py`. Un hijo falso debe fallar aunque devuelva vectores del tamaño correcto.
- [ ] Ejecutar tests nuevos; observar FAIL por probe/comparador ausentes.
- [ ] Implementar ejemplo como adaptador del encoder real y comparador. Usar copias independientes de fixtures, conservar orden/historia de llamadas y todos los errores; no llamar Python desde Rust ni usar salidas esperadas para producir resultados nativos.
- [ ] `cargo build --release --locked -p ken-models --example model_probe`; ejecutar paridad con artefactos reales, PATH vacío y sentinelas, fuera del checkout. Linux exige strace y sólo exec inicial; auditar librerías/Cargo sin libpython/pyo3/cpython.
- [ ] Commit; gate de tarea: tests de comparador y suite de paridad del modelo con binario explícito ya construido; sin skip/fallback si falta.

### Task 6: Evidencia multiplataforma y cierre del primer perfil

**Interfaces:** recibo `m2-static/summary.json` con alcance preciso, huellas de fuentes/registro/pesos/tokenizer/casos, versiones reales, tolerancias, casos, autonomía e integridad. Aceptación de este corte requiere Linux y macOS comparables; `M2_accepted` permanece false hasta completar todos los runtimes y los datos.

- [ ] Probar que el agregador rechaza artefactos o casos distintos, plataforma ausente y fallo de inferencia. Observar rojo antes de ampliar tooling.
- [ ] Añadir workflow independiente y documentación de preparación/reproducción del probe. Preparar únicamente artefactos registrados; conservar los recibos fallidos. No modificar la CI Python original, publicar ni hacer push.
- [ ] Ejecutar fmt/clippy/tests workspace, regresiones M1, comparación del encoder y pruebas de autonomía en Linux/macOS. Suite Python completa al cerrar; comparar IDs/errores con baseline, sin debilitarlo.
- [ ] Medir preparación/carga/inferencia/RSS por separado sobre entradas publicadas; informar todos los intentos sin establecer un SLA nuevo.
- [ ] Actualizar matriz: sólo Potion pasa a `paridad_verificada`; registrar los demás runtimes y datos como pendientes. Revisar el conjunto con un único reviewer fresco según ejecución nativa y resolver sus Critical/Important mediante TDD.
- [ ] Commit de evidencia/docs propios y cierre del plan; conservar originales y avanzar al siguiente plan de runtimes M2.

## Autorrevisión

Registro → tokenización → encoder → probe → comparación tienen interfaces
definidas antes de sus consumidores. Los cinco focos tienen pruebas concretas.
El primer corte prueba un modelo real y no introduce crates vacíos ni comandos
de usuario aparentes. No se confunde aceptación de Potion con cierre M2/M8.
Las versiones de tokenizers, safetensors, half y sha2 se contrastaron con sus
fuentes/documentación oficiales antes de escribir el plan; compilación y
viabilidad se demuestran durante las tareas, nunca por este documento.

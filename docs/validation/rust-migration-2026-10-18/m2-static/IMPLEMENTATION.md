# M2: primer perfil estático nativo

**Implementado y con matriz Linux/macOS aprobada por pruebas; revisión independiente pendiente.**
Este corte acredita Potion registrado, no cierra M2 ni la migración completa.
Los demás runtimes y el almacenamiento siguen pendientes del contrato general.

`ken-models` posee artefactos verificados, tokenización Model2Vec, pooling F16/F32
y caché de términos. `model_probe` es un adaptador de validación del motor real;
no agrega comandos de búsqueda incompletos ni sustituye el `ken` instalado.
Los 1.066 originales y el oráculo congelado siguen sin cambios.

## Contrato y pruebas

Los [18 casos](cases.json) y sus [salidas Python](potion-reference.json) se fijaron
antes de escribir Rust. Cubren vacío/espacios, español, NFC/NFD, emojis, código,
UNK/PAD, 511–513 tokens, prefijo Unicode, caché y lotes de 1024/1025 filas.
El registro fija Potion e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b, cuatro artefactos
con SHA-256 y pesos F16 de 63.457×256. No se normalizó otra vez en F32 para ocultar
la aritmética del oráculo: PAD y promoción F64 por vacío conservan su comportamiento.

Ambas plataformas pasaron los 16 gates con las mismas seis huellas y Rust1.95.0:
15.613 pruebas Python, los mismos 10 xfail, 46 pruebas Rust distintas, 70 pruebas
de migración, los 18 historiales completos del modelo y los 62 casos M1.
No hay nuevos fallos/skips ni tests originales omitidos. Se observó una advertencia
upstream de hf_xet; macOS conserva los dos errores históricos de mypy por ausencia
de transformers, mientras Linux pasó sobre los 409 fuentes.

[MacOS](macos/summary.json), [Linux](linux/summary.json), [matriz](matrix.json).
La [traza Linux](linux/native-exec.trace) registra exactamente un exec inicial.
El probe se copió fuera del checkout, ejecutó con sentinelas en PATH y pasó la
auditoría de librerías/Cargo. Ningún runtime Rust llamó Python. Los controles
negativos rechazaron procesos falsos, tokens reordenados, dimensiones incorrectas,
ceros alterados, NaN/Inf y artefactos corruptos.

Los tests sintéticos distinguen F16/F32, media y norma, promoción por vacío,
límites de lote, recencia/copia de caché, 8MiB/8192entradas, whitespace C0 y
concurrencia. Una regresión adicional observó primero la aceptación indebida de
IDs duplicados en un tokenizer y luego su rechazo. No se amplió ninguna tolerancia.

## Medidas observadas

Cada motor ejecutó 30 cargas nuevas por workload dentro de un proceso, sin
eliminar muestras. Query contiene `alpha beta`; passages contiene 64 textos
alternados de código/español publicados con los inputs completos en el recibo local.

| Plataforma | Motor | Construcción mediana | Query mediana | Lote64 mediana |
| --- | --- | --- | --- | --- |
| macos | native | 66.605 ms | 34.251 µs | 1.092 ms |
| macos | python | 101.165 ms | 215.750 µs | 1.955 ms |
| linux | native | 75.876 ms | 43.312 µs | 1.512 ms |
| linux | python | 122.864 ms | 219.333 µs | 2.198 ms |

[Todas las muestras macOS](macos/benchmark.json) y [Linux](linux/benchmark.json)
conservan mediana/p95/máximo por fase y picos post-exec. Son mediciones del probe:
los picos son acumulativos entre cargas, no asignaciones aisladas. Linux usa
VmHWM propio, macOS getrusage propio. Python vuelve a verificar archivos en cada
construcción; Rust construye desde bytes ya verificados y mide esa verificación
por separado. No se inventó un SLA ni se atribuye mejora global de la aplicación.

## Alcance pendiente

La matriz técnica sólo cambia Potion a `paridad_verificada`. No acredita tablas
NPZ, contextual ONNX, reranker Ettin, CT2/SentencePiece, catálogo FastEmbed,
Sentence Transformers, Qwen3/MLX, juez causal, política completa ni datos M2.
La aceptación del perfil sigue pendiente de su única revisión independiente.
Los formatos Model2Vec cuantizados con mapping/weights se rechazan explícitamente
en este primer encoder; no se ignoran esos tensores.

`compatible_identity` conserva los metadatos del espacio Python observado;
`runtime` declara las bibliotecas Rust/CPU efectivas. No se declara que los
paquetes Python sean parte del binario. Los índices actuales no se reescriben.

Los [comandos de reproducción](../../../rust-migration.md) y los workflows
independientes identifican la preparación. No hubo push, PR ni CI remota.
Logs/JUnit y salidas completas permanecen inalterados en `.ken/rust-migration/m2/validation/`
y `.ken/rust-migration/m2/linux-receipts/validation/`, con hashes registrados.

## Decisiones de ejecución

- Ruling: continue in existing migration branch/checkout — a new clean worktree omits the preserved dirty Python oracle; no original changes enter migration commits — risk if wrong: using a different source as reference.

- Ruling: retain previous plan workspace temporarily — its Linux input bind and raw receipts are still needed for reproducible model validation; public M1 decisions and acceptance are committed — risk if wrong: premature cleanup would destroy evidence or break Linux preparation.

- Task 1: Ruling: deduplicate identical passage output vectors with a complete ordered row-index list in captured evidence — retain all 1024/1025 outputs without duplicating public bytes — risk if wrong: comparator must expand rows strictly, never ignore duplicates.

- Task 1: Ruling: run full Python suite at the plan's explicit T6 gate, and all targeted original/tooling contracts per task — no original source changes and M1 already certified full baseline; avoid six redundant 15-minute runs — risk if wrong: unexpected cross-task tooling regression appears at final gate; never advance M2 stage before it passes.

- Task 4: Ruling: real-weight integration is mandatory and explicitly requires KEN_POTION_SNAPSHOT — offline synthetic/token tests remain portable, but full workspace validation must prepare registered weights rather than silently skip real inference — risk if wrong: undocumented preparation could look like a product regression; add reproduction instructions at T6.

- Task 4: Ruling: reject extra/quantized tensors in this first unquantized encoder — registered Potion contains embeddings only; mapping/weights variants remain pending rather than ignored — risk if wrong: broader Model2Vec formats must receive their own native implementation before M2 closure.

- Task 5: Ruling: compatible_identity retains the validated frozen Python space metadata; runtime separately declares actual Rust libraries and CPU — no Python-package installation claim and no persistence consumer enabled — risk if wrong: callers might confuse compatibility metadata with the runtime actually executing it.

- Task 5: Ruling: local Linux exec tracing and both-platform gate close under T6, which owns platform aggregation — macOS functional probe is implemented and proven; no Linux claim is inferred from macOS — risk if wrong: platform-specific defects must still block profile acceptance.

- Task 6: Ruling: benchmark30 new encoder instances per workload inside one process per engine; preserve every sample and label cumulative post-exec phase peaks — Linux /proc VmHWM avoids the inherited pre-exec wait4 floor; macOS self getrusage measures actual process peak — risk if wrong: peaks are not isolated allocations, and Python construction additionally re-verifies artifacts; no memory/SLA speedup is claimed.

- Task 6: Ruling: M1 validation now forwards only explicitly prepared KEN_POTION_SNAPSHOT/KEN_MODEL_PROBE to native workspace tests, while frozen oracle environment keeps stripping them — adding a real-weight crate made old CI's workspace suite require model preparation; RED→GREEN environment boundary test ensures unrelated KEN_PROJECT_ROOT stays excluded — risk if wrong: CI could silently fail on missing model inputs or oracle isolation could weaken.

- Task 6: Ruling: reject duplicate vocabulary IDs as well as out-of-range IDs — valid safetensors row count alone cannot distinguish two tokens aliased to one row; new duplicate-ID regression observed RED before adding uniqueness validation — risk if wrong: corrupt synthetic/custom registrations could silently select the wrong embeddings; real Potion remains unchanged.

- Task 6: Ruling: use M2 plan base e1ae714b for its fresh whole-plan review — M0/M1 already received its one independent review and TDD fix pass; review all M2 changes including affected M1 tooling, with foundation report available as context — risk if wrong: a cross-stage regression could be missed; fullworkspace suites and all62 M1 parity cases passed onbothOS.

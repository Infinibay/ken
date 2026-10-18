# M2: viabilidad y contrato de modelos nativos

Fecha: 2026-10-18. Continúa el contrato general aprobado y la instrucción del
usuario de completar la migración, manteniendo ejecución nativa y los originales.
Este documento concreta M2 antes de implementar. M1 debe estar aceptado antes de
añadir capacidades Rust de esta etapa. Los runtimes se verifican antes de portar
masivamente consumidores; una biblioteca anunciada no constituye inferencia probada.

## Problema y alcance

Un índice existente pertenece a un espacio vectorial concreto. Leer sus datos y
generar consultas con otro tokenizer, pooling, prompt, precisión o revisión puede
producir resultados plausibles pero incorrectos. La migración debe ejecutar los
modelos actuales sin Python, conservar la identidad del espacio y demostrar
equivalencia antes de habilitar escrituras. No basta producir vectores del mismo
tamaño ni sustituir un modelo por otro que una biblioteca Rust soporte.

M2 se divide en planes verificables: artefactos y primer encoder estático;
restantes runtimes; almacenamiento relacional y vectorial. La etapa sólo se
acepta cuando se cumplen los tres. M3 no empieza con perfiles obligatorios o
integridad de almacenamiento pendientes. Búsqueda y reglas de ranking pertenecen
a M4, pero su inventario de recursos determina qué inferencia debe probar M2.

## Conceptos y responsabilidades

| Concepto | Responsabilidad |
| --- | --- |
| Registro de modelo | Declarar artefactos, revisión inmutable y semántica de inferencia |
| Artefactos verificados | Acreditar tamaños y hashes de datos locales antes de consumirlos |
| Tokenización | Aplicar el tokenizer exacto, sus tokens especiales y sus límites declarados |
| Encoder | Transformar preguntas o pasajes en vectores según el registro |
| Runtime | Ejecutar operaciones tensoriales y declarar proveedor, versión y dispositivo reales |
| Política de modelo | Conservar pins existentes y resolver el modelo de proyectos nuevos |
| Recibo de equivalencia | Comparar tokens, salidas, integridad y autonomía de dos procesos reales |

El núcleo de proyecto no depende de los runtimes. Los modelos tendrán un crate
`ken-models` cuando se incorpore el primer encoder funcional. La CLI de usuario
se amplía cuando su capacidad esté lista; un probe de validación utiliza ejemplos
o ejecutables de prueba del crate y no pretende completar `search` ni `models`.

Uso representativo del primer corte:

```rust,ignore
let assets = ModelAssets::from_json(registration)?;
let snapshot = assets.verify(local_snapshot)?;
let encoder = Model2VecEncoder::load(&snapshot)?;
let tokens = encoder.token_ids("¿Dónde se guarda config.value?", None)?;
let vectors = encoder.embed_passages(&["function save_config", ""])?;
```

La carga sólo acepta los pesos y tokenizer correspondientes al registro.
Los errores identifican artefacto o política; nunca devuelven vectores vacíos
como sustituto de un modelo que no pudo cargarse. Un lote de entrada vacío sí
produce un lote vacío sin cargar pesos. La carga es perezosa para consumidores
que no necesitan inferencia, incluido `status`.

## Inventario de inferencia observado

| Familia actual | Contrato que se conserva | Evidencia fuente |
| --- | --- | --- |
| Model2Vec Potion | `minishlab/potion-code-16M-v2`, revisión `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b`, pesos F16/F32, media nativa y L2; sin padding ni truncado oculto; límite 512 en encode, no en conteo | `embedder/model2vec_backend.py`, registro JSON |
| Tabla Ken | NPZ `ken__static-qwen3-r512-v2.npz`, LUT, A int8 y escala por fila, B F32, tokenizer incluido; suma, proyección y L2; sin prompt | `embedder/static_head.py` |
| Contextual CPU | CodeRankEmbed int8, revisión `e74f446dc6e67e29fcee77213472c142f73a6bbb`; raw CLS 768 F32, sin normalización en encoder, prefijo de pregunta, truncado 512, batch 1, ORT CPU 2/1 hilos | `embedder/contextual_onnx.py` |
| Reranker CPU | Ettin 68m revisión `d166fa88ddde3c42bc3ee92f7df476d941c8204a`; cabeza CLS/Dense/GELU exacta/LayerNorm eps1e-5/Dense, logits crudos; sólo segundo miembro truncado, límite 1024, padding derecho, top10 | `retrieval/neural_assets.py`, `neural_reranker.py` |
| Expansión español | CT2 int8 CPU, revisión `ad91ad1697ea1761111ff4c179400796d085b347`; SentencePiece, beam 1, decoding 256, hilos 2/1, protección de identificadores y restauración | `retrieval/query_expansion.py`, `translation_preparation.py` |
| FastEmbed | Catálogo real del paquete de referencia, prompts por familia, proveedores CUDA/ROCM/CPU y degradación CPU declarada; legacy MiniLM conserva su espacio | `embedder/onnx_fastembed.py`, `embedder/__init__.py` |
| Sentence Transformers | Modelo/revisión del proyecto, tokenizer, módulos/pooling y prompts; límites, normalización F32, dispositivos y degradación CPU | `embedder/st_backend.py`, `retrieval/profile.py` |
| Qwen3 MLX | Sólo Qwen3, pesos safetensors fijados, padding derecho, último token real, dtype del perfil, L2; límite de caché 512 MiB sin elevar límites previos inferiores | `embedder/mlx_backend.py` |
| Juez Qwen3 | Plantilla/instrucción y tokens exactos, pregunta 128 tokens, documento según presupuesto, proyección yes−no sobre último token real; Torch/MLX según perfil | `retrieval/joint_model.py` |

La tabla es un mapa de familias, no un catálogo cerrado de modelos arbitrarios.
Se captura el catálogo FastEmbed y los perfiles declarados por los tests y APIs.
Una arquitectura sin implementación Rust sigue pendiente: no se elimina del
inventario ni se convierte en un alias de otro encoder. La ejecución arbitraria
de código Python remoto no puede acreditarse como runtime nativo; cualquier
consumidor que la necesite debe identificarse y resolverse antes del cierre M8.

Los modelos numéricos comprimidos de ranking son recursos M4. M2 conserva sus
bytes y registra que no son redes adicionales. El ensamblado del grafo Ettin y
la normalización de los JSON CT2 forman parte de preparación reproducible;
reutilizar un archivo generado por Python no demuestra que la instalación
nativa pueda prepararlo desde los artefactos registrados.

## Elección técnica y alternativas

Se conserva la implementación matemática actual y se reutilizan bibliotecas
nativas compatibles: tokenizers Rust 0.22.2 para el mismo formato; safetensors
para pesos; operaciones estáticas F16/F32 explícitas; ONNX Runtime para grafos
ONNX; CTranslate2/SentencePiece para traducción. MLX y los modelos de Torch
requieren pruebas específicas de sus bindings o un port de arquitectura con
salidas equivalentes. No se toma la coincidencia del nombre de una crate como
prueba de compatibilidad de su biblioteca enlazada.

Alternativa descartada: envolver Python, porque mantiene el runtime que el
usuario pidió retirar. Usar sólo un catálogo Rust de embeddings reduce trabajo,
pero no conserva automáticamente pooling, modelos ni preparación actuales.
Los componentes estáticos se implementan directamente porque su contrato es
pequeño y se puede contrastar con pesos reales; no se añade una red neuronal
genérica para realizar una media de filas.

Las versiones concretas de nuevos bindings se fijan en el plan de cada corte,
tras inspeccionar sus fuentes y compatibilidad de toolchain. No se instalan
dependencias de producto ni se acredita un runtime durante esta exploración.

### Fronteras observadas en Model2Vec 0.9.0

La implementación bloqueada de `StaticModel.tokenize` recorta primero el texto
a `max_length * median_token_length` caracteres Unicode, elimina IDs UNK y luego
recorta IDs a `max_length`. Desactivar el truncado del tokenizer no elimina ese
preprocesamiento. El conteo sin límite conserva el texto completo.

`_encode_batch` calcula la media en el dtype de los pesos. Con F16, NumPy acumula
la media y redondea su resultado a F16 antes de normalizar. Una fila sin tokens
introduce un vector cero F64, que promueve todo ese lote antes de la norma; el
adaptador Ken convierte finalmente cada salida a F32. El primer plan fija tests
de estos casos, del límite 1024 por lote y de la caché de términos cortos: una
media universal en F32 no se presume equivalente por usar los mismos pesos.

Un [probe NumPy independiente](../../validation/rust-migration-2026-10-18/m2-static/exploration/precision-probe.json)
observó una diferencia máxima de 0.000241816 entre el mismo texto en lote solo
y en lote con vacío. El [inventario instalado](../../validation/rust-migration-2026-10-18/m2-static/exploration/runtime-inventory.json)
también distingue paquetes presentes y ausentes: CTranslate2 4.8.3 y Torch 2.14.0
locales difieren de 4.8.2 y 2.9.0 fijados por el proyecto. No se altera ese entorno
para aparentar una referencia idéntica al lock; los ensayos de backends fijan y
registran ambos alcances antes de compararlos. Transformers/MLX no están instalados
en el entorno original observado, y siguen contando como capacidades pendientes.

La [exploración del Potion real con el oráculo congelado](../../validation/rust-migration-2026-10-18/m2-static/exploration/potion-contract.json)
verificó los pesos F16 de 63.457×256, mediana de token 7 y UNK=1. `[PAD]` se
conserva como ID 0; `[UNK]` se elimina. La norma F32 observada de la salida PAD
fue 1.0067662 por la aritmética F16 del oráculo. Normalizar otra vez en F32
cambiaría ese contrato. Estas observaciones preparan pruebas; no acreditan
todavía ninguna inferencia Rust.

## Identidad y compatibilidad persistente

Los perfiles actuales incluyen versiones de paquetes Python en sus hashes
(`EncoderSpec.key`, `tokenizer_revision`, `RetrievalProfile.fingerprint` y los
registros proporcionados). No se sustituyen esos campos por versiones Rust
silenciosamente: cambiaría la identidad aunque los pesos fueran iguales.

Se distingue la identidad compatible del espacio de la evidencia del runtime
que lo ejecuta. Para leer un espacio anterior se conservan sus campos y se
verifican sus artefactos y política. Un recibo separado declara las bibliotecas
Rust/nativas efectivas y las pruebas de equivalencia. No se declara que Python
está instalado para fabricar el hash compatible. Si la equivalencia no puede
demostrarse, se rechaza el uso del espacio y queda pendiente una migración
explícita con copia y reindexación, nunca una mezcla de vectores.

La serialización usada por hashes existentes debe reproducir JSON Python
ordenado, espacios y escape ASCII cuando el algoritmo original los incluya.
Los tests fijan bytes y digest, incluidos Unicode y números; ordenar claves
solamente no basta.

## Artefactos, preparación y límites

Se aceptan únicamente IDs de modelo y revisiones fijadas del registro actual.
Se rechazan rutas absolutas, `.`/`..`, componentes vacíos, tamaños inválidos,
hashes inválidos y duplicados. Los symlinks internos del cache Hugging Face
pueden apuntar a sus blobs: no se confunden con paths de proyecto confinados.
Cada archivo debe tener el tamaño y SHA-256 declarados antes de inferencia.

La preparación descarga únicamente datos públicos fijados, sin credenciales ni
código remoto, con publicación atómica y verificación antes de reutilizar.
Un modo offline falla explícitamente cuando faltan datos; nunca abre red.
Los fixtures corruptos y sintéticos viven bajo directorios temporales; no se
modifican caches del usuario ni se copian datos privados a recibos públicos.

## Pruebas y criterios de aceptación

1. Capturar tokens y salidas de procesos del oráculo congelado para texto vacío,
   espacios, ASCII, español, Unicode combinado, emojis, identificadores de código,
   entradas repetidas, tamaños 511/512/513 y lotes de distinta longitud.
2. Exigir igualdad exacta de IDs, máscaras, truncado, orden, dimensiones y política
   de prompts. Conteo de tokens no hereda truncado oculto del encoder.
3. Fijar tolerancias **antes** de la inferencia Rust para cada modelo/dtype y
   dispositivo. Justificarlas con precisión/aritmética y variación del oráculo;
   rechazar NaN/Inf. La tolerancia vectorial no acredita calidad de ranking M4.
4. Probar artefactos reales además de pesos sintéticos con valores distinguibles.
   Un fixture mínimo valida la regla, pero no certifica el tokenizer/pesos reales.
5. Probar carga incompleta/corrupta, revisión equivocada, forma/dtype inválidos,
   fallo de proveedor y degradación CPU. No usar skips para falta de modelos:
   preparación o capacidad pendiente debe hacer fallar el gate correspondiente.
6. Ejecutar los probes Rust fuera del checkout con PATH sin Python y, en Linux,
   traza exec. Inspeccionar dependencias nativas, versiones y proveedores reales.
   Una muestra GPU requiere hardware observado; CPU es obligatoria.
7. Verificar hashes originales antes/después, suite Rust/fmt/clippy y regresiones
   M1. Los tests Python se conservan; sus resultados previos siguen en recibos.

Cada recibo identifica fuentes, modelo/revisión, artefactos, tokenizer, runtime,
dispositivo, entradas, tolerancias, salidas y comandos. Se informa arranque,
preparación, inferencia y RSS por separado. Ningún perfil pasa por heredar el
estado de otro; el cierre global de modelos exige todas las familias aplicables.

## Fuentes técnicas comprobadas

- [Tokenizers 0.22.2, núcleo Rust y etapas de tokenización](https://docs.rs/tokenizers/0.22.2/tokenizers/).
- [Safetensors, formato y validación de tensores](https://docs.rs/safetensors/0.8.0/safetensors/).
- [ndarray-npy, lectura NPY/NPZ y tipos soportados](https://docs.rs/ndarray-npy/0.10.0/ndarray_npy/).
- [ort, interfaz nativa a ONNX Runtime](https://github.com/pykeio/ort).
- [FastEmbed Rust, catálogo y backends](https://github.com/anush008/fastembed-rs).
- [Bindings CTranslate2](https://github.com/jkawamoto/ctranslate2-rs).
- [Bindings MLX y fuentes de sus dependencias](https://github.com/oxiglade/mlx-rs).

Autorrevisión documental: responsabilidades separadas, inventario de familias
explícito, fuentes conservadas, ausencia de certificaciones inferidas y cierre
M2 condicionado a modelos y datos completos. Los planes siguientes concretan
firmas, pruebas y versiones de cada corte antes de escribir código.

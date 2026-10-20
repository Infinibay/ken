# M2: FastEmbed nativo y propiedad de artefactos grandes

Fecha: 2026-10-20. Rama `codex/rust-migration`.

Continúa el [contrato general aprobado](2026-10-18-rust-migration-design.md) y
el [contrato M2](2026-10-18-rust-model-runtime-design.md). El usuario exige
continuar de forma nativa, sin nuevas confirmaciones, conservando los originales
y verificando cada entrega. Almacenamiento terminó en `20db131d`, con prueba
conjunta `a5a5211`: 31 controles aprobados en macOS arm64 y Linux aarch64.
Este documento concreta el siguiente subsistema; no declara M2 terminado.

## Propósito y alcance

Ejecutar en Rust los modelos del catálogo FastEmbed real de la referencia,
conservando los vectores y su identidad: artefactos, revisión, tokenizer,
prompts, truncado, padding, batching, pooling y normalización. Una salida de
la misma dimensión no demuestra compatibilidad. Python sólo es oráculo y
controlador de pruebas; el proceso nativo ejecuta el modelo sin Python.

El alcance incluye los 30 registros del catálogo FastEmbed 0.8.0, cinco
implementaciones con registros no vacíos, tokenización y ejecución CPU en ambas
plataformas, selección de proveedores y degradación CPU. La prueba numérica de
GPU sólo se acredita en hardware/proveedor realmente disponible; las rutas de
disponibilidad y fallo se prueban explícitamente. La adquisición nativa general,
Sentence Transformers, MLX, juez Qwen3 y ensamblado final de modelos siguen en
M2. No se reemplaza todavía el ejecutable instalado ni los adaptadores públicos.

## Base y viabilidad observadas

Se verificaron 116 JSON de tokenizer/configuración, 94.452.712 bytes, de 29
repositorios públicos que corresponden a los 30 registros. Cada repositorio
quedó fijado por revisión de 40 dígitos hexadecimales; se comprobaron los bytes
contra SHA-256 LFS o identidad de blob Git, y se conservaron SHA-256 propios.
El `load_tokenizer` original se ejecutó en las 29 revisiones con entradas
vacías, Unicode, tokens especiales, longitudes 511/512/513 y sus límites de
contexto. Estas observaciones preparatorias no sustituyen el corpus final.

Un experimento Rust desechable cargó e infirió cinco grafos reales, uno por
implementación original, con las mismas versiones de dependencias que el
workspace aceptado. Se usó ONNX Runtime 1.25.1/API25 acreditado, CPU 2/1 hilos,
archivos e inputs explícitos, PATH sin herramientas y límites externos sobre
el proceso recién creado. Los cinco pasaron en ambas plataformas, con salida
F32 finita. Esto prueba viabilidad del runtime, no paridad de tokenización o
pooling del encoder todavía pendiente.

| Representante | Implementación original | Forma observada |
| --- | --- | --- |
| BAAI/bge-small-en-v1.5 | OnnxTextEmbedding | `[1,10,384]` |
| sentence-transformers/all-MiniLM-L6-v2 | PooledNormalizedEmbedding | `[1,10,384]` |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | PooledEmbedding | `[1,10,384]` |
| Qdrant/clip-ViT-B-32-text | CLIPOnnxEmbedding | `[1,512]` |
| jinaai/jina-embeddings-v3 | JinaEmbeddingV3 | `[1,10,1024]` |

Los seis archivos de grafo/pesos suman 2.938.860.244 bytes verificados. Jina v3
usa un archivo externo de 2.291.339.168 bytes; su pico RSS nativo medido fue
4.476.141.568 bytes en macOS y 3.124.969.472 en Linux. El contenedor exclusivo
pasó de 3 a 6 GiB, manteniendo dos CPU y ningún montaje, después de cerrar las
pruebas anteriores. Es capacidad de este ensayo, no un SLA del producto.

Los manifiestos, observaciones, fuentes del experimento y mediciones se conservan
en `.ken/rust-migration/m2/runtime-research/fastembed-*-2026-10-20*`. El código
del experimento no se incorpora al encoder del producto. La primera compilación
aislada resolvió ndarray 0.17.2; se corrigió a las versiones exactas del workspace
y se repitió la prueba en ambas plataformas, conservando el intento inicial.

## Conceptos y responsabilidades

| Concepto | Responsabilidad |
| --- | --- |
| Catálogo FastEmbed | Asociar el nombre público a una receta y artefactos inmutables registrados |
| Modelo FastEmbed | Declarar dimensión, grafo, política de salida e inputs adicionales de un modelo |
| Fuente de archivos | Localizar el snapshot y el directorio privado de trabajo sin prepararlos todavía |
| Archivos verificados propios | Conservar una copia privada exacta de los bytes acreditados durante su uso nativo |
| Dependencias ONNX | Acreditar que todas las referencias externas del grafo permanecen entre esos archivos |
| Tokenización FastEmbed | Reproducir configuración, especiales, prompts, truncado y padding del original |
| Proveedores ONNX | Traducir la decisión de dispositivo existente a sesiones reales y degradación CPU |
| Pooling | Convertir la primera salida real del grafo al vector según su receta y aritmética |
| Encoder FastEmbed | Coordinar preparación perezosa y llamadas serializadas, devolviendo resultados propios |

Se amplía `ken-models`. No se añade una biblioteca neuronal distinta ni se
reescriben los encoders ya aceptados. La selección de modelos y prompts sigue
en `model_policy`; almacenamiento mantiene su propia responsabilidad.

Uso representativo previsto, con declaración y rutas explícitas:

```rust,ignore
let model = FastEmbedModel::from_json(registration)?;
let source = ModelFileSource::new(snapshot_dir, private_work_dir)?;
let encoder = FastEmbedEncoder::new(model, source, runtime, device_request)?;
assert!(!encoder.is_prepared()?);
assert!(encoder.embed_passages(&[])?.is_empty());
let vectors = encoder.embed_queries(&["Read a stored setting by key"])?;
```

Las firmas y archivos exactos se fijan en el plan antes de implementación.

## Artefactos y límite de propiedad

Se reutiliza `ModelAssets` como autoridad de nombres relativos, revisiones,
tamaños, hashes y huella. El nombre público FastEmbed puede diferir del repositorio
HF físico: no se confunden ambos identificadores. El registro contiene el grafo,
archivos adicionales y los cuatro JSON requeridos, con dimensión y receta.

Se añade una verificación mediante copia por bloques a un directorio privado
propio. Se valida el archivo regular abierto, tamaño exacto y SHA-256 durante la
copia; un cambio de bytes, truncado, FIFO o error de lectura falla sin publicar
un objeto acreditado. Los archivos fuente pueden ser symlinks de un cache HF,
como permite el propietario actual. Los destinos se crean nuevos, sin symlinks
ni hardlinks a los datos originales. Los directorios privados son 0700 y los
archivos finales de datos son de sólo lectura. Un fallo limpia sólo su staging.

El propietario mantiene esos archivos hasta después de destruir la sesión que
los usa. Cambiar, reemplazar o borrar las rutas de origen después de preparar no
altera inferencias ya acreditadas. No se expone una referencia Rust prestada a
un mapping mutable ni se extiende artificialmente una vida a `static`.

Antes de crear una sesión se recorren las dependencias externas ONNX, incluidos
tensores en atributos, subgrafos, funciones y sparse tensors. Toda ubicación
debe ser relativa al grafo y resolver a un artefacto declarado dentro de la copia;
offset y longitud deben ser enteros no negativos y caber en el archivo. Se
rechazan escapes, duplicados ambiguos y protobuf truncado/desbordado. El lector
es acotado y puede saltar payloads grandes sin cargarlos completos en RAM.

Se elige esta propiedad de archivos frente a clonar `VerifiedSnapshot` hacia
buffers externos de varios GiB. La [API nativa](https://raw.githubusercontent.com/microsoft/onnxruntime/v1.25.1/include/onnxruntime/core/session/onnxruntime_c_api.h)
copia los inicializadores suministrados en memoria durante la creación; acumular
snapshot, buffer y grafo puede multiplicar el pico. La elección cuesta espacio
y lectura/copia adicionales, medidos por separado; conserva la acreditación
sin relajar la propiedad existente de snapshots en memoria.

## Tokenización e inferencia

Se fija el catálogo y enrutamiento originales, sin inferir la receta por una
coincidencia aproximada del nombre. `prompts_for` conserva prefijos de pregunta
y pasaje. Ambos caminos llaman la semántica original de `embed`; Jina v3 recibe
`task_id=1` escalar I64 en ambos, no la variante `query_embed` del paquete.

Se cargan `tokenizer.json`, `config.json`, `tokenizer_config.json` y
`special_tokens_map.json` acreditados. Se conserva el orden de inserción de
especiales string/AddedToken y sus flags. Se habilita truncado con el único
límite declarado o el mínimo de `max_length` y `model_max_length` si están ambos.
La llamada original fija dirección derecha, longest-first y stride cero; no
hereda una política de truncado distinta serializada. Los valores del mapa de
especiales que no sean string ni objeto se omiten, como en el original.
El padding serializado se conserva; sólo si falta se configura con pad ID y
pad token originales. No existe un límite universal de 512.

Los límites observados son 77, 128, 256, 512, 8192 y 8194. MiniLM usa 256,
multilingual MiniLM 128, Snowflake m-long 512 aunque también declare 8192, y
Jina v3 8194. Tokenización y sus límites se prueban sin requerir ejecutar una
red completa en cada longitud extrema; la inferencia real incluye además los
casos 511/512/513 y lotes mixtos fijados antes del código.

El batch original predeterminado es 256, con el resto en orden. Los inputs son
I64: IDs, máscara sólo si el grafo la pide, type IDs cero si los pide y el task
escalar registrado. Se consume la primera salida del runtime. Los resultados
deben conservar batch, secuencia y dimensión esperados, dtype y finitud.
Se conservan optimizaciones ORT_ENABLE_ALL y los defaults efectivos de hilos
del original (`threads=None`, ORT intra/inter cero). Los 2/1 hilos del
experimento fueron sólo un límite de la prueba de viabilidad.

| Receta | Cálculo que se conserva |
| --- | --- |
| CLS o salida de frase + L2 | Primera posición de una salida 3D, o salida 2D; norma F32 y denominador mínimo 1e-12 |
| Media enmascarada | Producto F32 por máscara I64 promovido a F64, suma y división F64, máscara con mínimo 1e-9; sin L2 |
| Media enmascarada + L2 | Media anterior y norma F64 antes del cast final F32 |
| Salida cruda CLIP | Salida 2D, sin introducir normalización |

La salida pública siempre es F32, como el cast de Ken. Ningún fallo de modelo,
artefacto o forma se convierte en vectores vacíos o ceros sustitutivos.
Un intermedio no finito de normalización también falla explícitamente, evitando
un falso cero por overflow; esos inputs sintéticos de integridad se separan de
la paridad con salidas válidas de los modelos reales.

## Estado, dispositivos y compatibilidad

La construcción y un batch vacío no cargan pesos ni runtime. La preparación
explícita o la primera llamada no vacía prepara datos y sesión; un fallo deja
el estado reintentable. Una exclusión serializa tokenización e inferencia de
todo el batch, incluido su consumo completo. Los resultados no prestan buffers
mutables de otra llamada. El informe de preparación/dispositivo refleja sólo
estado alcanzado, con `unknown` antes de preparar.

Se conserva preferencia CPU explícita y orden CUDA, ROCm, CPU para auto/GPU,
sin introducir CoreML/TensorRT. Una disponibilidad declarada no acredita que
pueda construirse la sesión: un fallo GPU reintenta CPU y un fallo CPU se
propaga. Se conserva y prueba el comportamiento efectivo de device IDs del
original; no se promete haberlos aplicado cuando su ruta de proveedores
explícitos los ignora. La evidencia distingue selección de proveedor y ejecución
numérica en hardware real. Se reutiliza el propietario del runtime API25.

Hay una corrección declarada de integridad: `_dim` original permanece en 384
incluso cuando el modelo devuelve 512/768/1024. El encoder nativo informa la
dimensión registrada real y verifica que la salida coincida. El corpus captura
primero esa discrepancia del original y la separa de la paridad vectorial.
No autoriza relabelar ni reembeddear datos existentes. `StoredModelState` y la
política aceptada siguen decidiendo compatibilidad y errores de datos previos.

## Pruebas y aceptación

Antes del código de producto se congela un corpus de procesos originales en
ambas plataformas, con los 30 registros, fuentes/versiones y artefactos reales
acreditados. Incluye query/passage, vacíos, Unicode/especiales, repeticiones,
511/512/513, lotes desiguales y frontera 256/257; tokenización cubre los límites
de contexto. Se registran llamadas efectivas al runtime, formas/dtypes,
vectores, estado perezoso y dimensión, sin sustituir inferencia por mocks.

Se fija antes de las comparaciones del encoder: igualdad exacta de IDs, máscaras,
orden, formas, tipos, prompts y metadatos válidos; para vectores CPU F32 finitos,
`abs(error) <= 1e-6 + 1e-6 * abs(reference)`. Esta tolerancia no acredita calidad
de ranking ni puede ampliarse para hacer pasar una implementación. Los casos de
dimensión falsa se identifican como corrección; las entradas de prueba no llevan
resultados esperados al proceso Rust.

Pruebas pequeñas con salidas distinguibles verifican cada receta y el cast
tardío, además de las redes reales. Hay pruebas de fuente cambiada, copia
interrumpida/error, protobuf y dependencias externas inválidos, filas ocultas,
NaN/Inf, concurrencia, primer uso, fallo/reintento y liberación de archivos.

La validación acumulada conserva los 31 controles, baselines, deadlines y
originales anteriores, y añade binding de release, paridad FastEmbed y prueba
de propiedad/perezosidad fuera del checkout. Se acreditan los dos sistemas con
los mismos inputs actuales y árbol completo de evidencia autenticada. No se
eliminan fallos, skips ni aserciones para alcanzar aceptación. Una revisión
fresca de todo el plan, una pasada TDD para Critical/Important y decisiones
con costo cierran este corte. M2 y la migración completa continúan pendientes.

Los vectores pueden registrarse como bytes F32 little-endian y los fragmentos
de evidencia comprimirse sin pérdida para limitar duplicación. Se conservan
hash/tamaño del contenido original y de los bytes transportados, se autentica
antes de descomprimir y se compara el contenido completo. La compresión no
autoriza recortar logs, campos, filas ni precisión.

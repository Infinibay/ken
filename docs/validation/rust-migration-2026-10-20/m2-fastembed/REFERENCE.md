# Referencia original FastEmbed (T1)

Este corte congela el comportamiento del Python original para implementar y
comprobar el encoder Rust. No acredita todavía el encoder nativo ni M2:
`native_acceptance=false`, `M2_accepted=false`.

`reference-index.json` identifica las dos capturas, sus índices e inventarios.
Cada una ejecuta 30 registros y 300 casos, y caracteriza los 29 tokenizadores.
Los resultados completos por modelo se guardan como JSON gzip, con vectores
F32 little-endian en hexadecimal, feeds reales, formas/dtypes, estados,
proveedores, opciones de sesión, avisos y fuentes. Cada fragmento conserva
hash/tamaño comprimido y descomprimido. `files.json` autentica todos los bytes
publicados; los stdout/stderr se comprimen sin pérdidas y conservan además el
nombre, tamaño y hash del log original. Los originales sin comprimir permanecen
en el área privada de ejecución.

La captura comprueba el árbol Python congelado y los 58 archivos Python de
FastEmbed instalado antes/después, Python3.12.9, FastEmbed0.8.0, NumPy2.4.4,
tokenizers0.22.2 y ONNX Runtime1.25.1. Un proceso original nuevo por modelo
observa el vacío frío antes de importar FastEmbed/ORT para instrumentación.
La adaptación del constructor sólo fija ubicación local y modo offline; no
cambia clase, batching, hilos, proveedores, optimización ni pooling. Las sesiones
CPU mantienen intra/inter0/0 y ORT_ENABLE_ALL. Los 148 archivos de modelos y
configuración suman18.952.301.850bytes y se verificaron por SHA-256 en ambos
sistemas. Las seis reutilizaciones por symlink son fuentes de cache; no acreditan
la propiedad independiente que debe implementar Rust.

Los casos cubren vacíos, queries/pasajes mixtos, Unicode/especiales, repetición,
511/512/513 palabras y lotes256/257. El último lote tiene256pasajes cortos y
uno largo para descubrir padding aplicado antes de dividir. Las fronteras de
cada tokenizer se construyen con longitudes reales context-1/context/context+1,
incluidos sus especiales, sin ejecutar una red completa en cada límite8k.

El original mantiene `dim=384` incluso ante vectores de ancho512/768/1024. Sólo
los resultados no vacíos exitosos pueden declarar esa corrección de metadatos;
los bytes vectoriales permanecen intactos. Las futuras peticiones al proceso
Rust llevan sólo id/operación/lado/textos, sin vectores o errores esperados.

Hay un fallo CPU previo y delimitado del grafo FP16 de
`jinaai/jina-embeddings-v2-base-de`: los ocho casos no vacíos fallan al crear
la sesión. Los dos vacíos no cargan nada; el estado sigue desconocido y cada
llamada no vacía reintenta. Los recibos conservan error y traceback, sin campos
de vectores o formas inventados. La firma está ligada al modelo, revisión,
grafo, SHA-256 y error reales; no permite aceptar otros fallos. La evidencia
`baseline-fp16/` reproduce dos intentos por plataforma sin hooks de sesión o
inferencia. No se desactivan optimizaciones ni se sustituye el grafo. Consulte
la sección de fallo previo del contrato FastEmbed.

Las salidas CPU válidas deberán satisfacer igualdad exacta de política/tokens
y `abs(error)<=1e-6+1e-6*abs(reference)` en Rust. La comparación de errores
requiere que el runtime nativo falle por sí mismo y preserve reintento; no se
introduce un interruptor de fallo esperado en las peticiones. La aceptación
acumulada de34controles llegará en T7, después de implementación y pruebas.

Los tiempos por caso rodean la llamada original. El campo histórico
`process_wall_ns` rodea el controlador completo: sandbox, proceso, validación
de salida y hashing posterior de archivos. No representa exclusivamente el
proceso hijo. Los picos RSS provienen de getrusage del hijo. No se afirma mejora
de velocidad a partir de estos datos; los sistemas tienen recursos distintos.

`auxiliary/case-alias-original-preflight.json` registra además una observación
sólo de prompts/tokenizer: el original enruta E5 con nombres en mayúsculas, pero
conserva esa escritura para buscar prefijos sensibles a mayúsculas. El corpus
principal usa nombres canónicos y no acredita por sí solo ese caso de alias;
la integración nativa debe cubrirlo sin normalizar silenciosamente los prompts.

Los snapshots históricos completos difieren fuera de la aplicación: Mac4920
archivos y Linux4682. `reference-snapshot-audit.json` conserva las dos huellas,
las328diferencias y los475registros de fuente `src/ken`, idénticos byte a byte.
También coinciden los58fuentes instalados de FastEmbed, las tres herramientas
de captura, versiones, registro, casos y bytes de modelos/configuración.
No se declara que los snapshots globales sean iguales.

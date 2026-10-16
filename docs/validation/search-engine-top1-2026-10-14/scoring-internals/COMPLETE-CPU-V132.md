# Resultado completo v132: calidad, coste y límites

Las **mismas 200 consultas de desarrollo** terminan con180 piezas correctas
en top1 (90%) y197 en top10 (98,5%). Se preservó exactamente la pertenencia
nativa del top10; los tres faltantes siguen contando como fallos. No es una
certificación privada ni una promoción del default público.

| Etapa | Clase /50 | Módulo /50 | Símbolo /50 | Archivo /50 | Total /200 |
|---|---:|---:|---:|---:|---:|
| Nativo | 44 | 44 | 43 | 37 | 168 |
| Piezas v126 | 47 | 45 | 43 | 40 | 175 |
| Piezas +68M +RRF60 | 47 | 45 | 45 | 43 | 180 |

Frente a nativo gana14 y pierde2; frente al bosque de piezas gana7 y pierde2.
El intervalo bootstrap agrupado por los ocho repositorios del incremento frente
a nativo es[0.012346,0.126984]; frente a piezas es[-0.004808,0.063584]. Son
comparaciones descriptivas de desarrollo expuesto, sin garantía de90% en otras
consultas. Los modelos de piezas excluyen del entrenamiento todo el repositorio
evaluado. El ensayo reutiliza el68M ya existente; no se entrenó ni buscó otro.

## Qué se ejecutó y qué se comprobó

Recuperación nativa nueva → tarjetas compactas v102 regeneradas de las fuentes
→ bosque de piezas v126 sobre esos mismos diez candidatos → inferencia nueva
ONNX68M FP32 → RRF60 con pesos0.5/0.5 → prioridad de ruta explícita → respuesta.
La entrada neuronal sigue la proyección compacta ya medida; no se afirma que
las tarjetas más extensas de v114 produzcan estos mismos logits o calidad.
La fidelidad al código y los presupuestos de salida se validan; la suficiencia
semántica del contexto no se certifica con este resultado de identidad.

Cada worker valida todas las fuentes antes de consultas, reconstruye los pools,
los compara por digest con v102 y compara el orden real del bosque con v126.
Estas referencias sólo detectan diferencias: no sustituyen candidatos ni scores.
La ejecución no carga Gold ni el archivo de logits históricos. Gold se abre en
un proceso distinto después del estado `ALL200 complete CPU outputs closed
without Gold`. Los outputs de los ocho workers y los modelos están fijados por
SHA256. CPUExecutionProvider fue el único provider; sin Torch/Transformers.

La auditoría posterior encontró **cero órdenes distintos** frente a la simulación
v130 en las200 consultas. Hay1988 pares efectivos; algunos pools tienen menos
de diez candidatos. La mayor diferencia de logit nuevo frente al histórico fue
3.814697265625e-06, compatible con cambiar la composición de los batches. No se
forzaron los logits para obtener esa coincidencia.

## Coste completo en CPU

Mediana4162.126ms; p955334.297ms; máximo6569.056ms. Pico de proceso1975648256
bytes (1,98GB decimales,1,84GiB).182/200 consultas tardaron como máximo5s.
Incluye recuperación, generación de tarjetas, exportación/proyección de traza,
features/bosque de piezas, tokenización/inferencia nuevas, comprobaciones por
consulta y serialización. Carga de assets y warmup se registran aparte. Los
workers se ejecutaron en serie, sin otro benchmark de modelos concurrente.

| Repositorio | Archivos indexados | p50 ms | p95 ms | p95 ms/100 archivos | Pico GB |
|---|---:|---:|---:|---:|---:|
| ajv | 486 | 3765.926 | 4817.072 | 991.167 | 1.261 |
| attrs | 141 | 4021.369 | 4849.302 | 3439.221 | 1.252 |
| boltons | 113 | 4183.337 | 4664.335 | 4127.730 | 1.273 |
| commons-csv | 122 | 3662.104 | 4569.311 | 3745.337 | 1.169 |
| junit5 | 2446 | 4315.360 | 6032.631 | 246.633 | 1.976 |
| marked | 582 | 3726.896 | 4687.858 | 805.474 | 1.208 |
| packaging | 139 | 4255.761 | 4736.266 | 3407.385 | 1.256 |
| pytest | 726 | 4756.609 | 5878.899 | 809.766 | 1.528 |

**La referencia aproximada de1s/100 archivos todavía se supera en los cuatro
repositorios pequeños** (attrs,boltons,commons-csv,packaging). No declarar
resuelto ese objetivo de rendimiento. La inferencia68M cuesta por sí sola
mediana3082.515ms/p953455.389ms; el ranking de piezas,97.777/279.044ms; la etapa
nativa,1035.114/1979.781ms. No sumar percentiles para calcular el p95 completo.
La siguiente optimización debe preservar estos mismos órdenes y comprobar de
nuevo ALL200, sin sustituir el modelo ni rebajar la métrica para aparentar rapidez.

## Decisiones incorrectas conservadas

[Índice de los20 fallos finales](fusion-v132/INDEX.md):17 tienen la pieza correcta
en top10 y3 no fueron puntuadas por esta etapa por quedar fuera de la ventana.
Cada caso guarda todos los candidatos con posición nativa/de pieza/neuronal/final,
score del bosque, logit y ambos componentes de RRF. El CSV conserva las1988
filas de las200 consultas, incluidas las correctas, con manifiesto verificable.

Las dos regresiones son explícitas: en vp-mf-031 el68M prefiere el módulo de tests
al módulo de listas; en vp-cs-078 prefiere clases de tests a VersionRange. La
fusión pierde la magnitud del margen del bosque y conserva sólo posiciones: un
prior de pieza3.059920 frente a-3.231066 no constituye un veto al cambio. El
módulo correcto cae de pieza1 a neural4 y el test pasa de pieza3 a neural1;
RRF elige el test por0.000124008. Es la causa ordinal exacta de esa regresión,
no una prueba de por qué internamente el modelo neuronal prefirió ese texto.

## Recibos y reproducción

- Fuente limpia congelada: `output/frozen/piece-complete-cpu-v132`, recibo
  3121eef43c19283275f06f0a7703446e31a02630e5179f14f313bcaee1503a18.
- Outputs reales: `output/development/piece-complete-cpu-v132`; registro
  961648fb55182c4411412ac98c772f45275fae18ce46e770639bf133df0d1495.
- Informe: `output/development/piece-complete-cpu-report-v132/summary.json` y
  `parity-audit.json`; incluye hashes, ganancias/pérdidas, tiempos por repo,
  carga/warmup, CPU y RAM. Preservados también en el checkpoint de esta etapa.
- Productores: `experiments/search-engine/{piece_complete_run,
  piece_complete_report,document_fused_scoring}.py` y
  `output/analysis/audit-piece-complete-v132.py`.
- Verificación posterior:294 tests de retrieval y mypy339 fuentes correctos.
  Una mutación que eliminaba el rechazo de logits no finitos hizo fallar las
  tres pruebas correspondientes; se restauró la fuente exacta antes de la suite.
- Respaldo `output/checkpoints/piece-controls-v132`:135 archivos en127 gzip,
  2627881 bytes; MANIFEST SHA
  1e94c7d5737ce7e543e93fe1cb461921592e7b153c204bc297a000193e0dde76.
  Incluye controles rechazados, sombras, overlays propios y resultados reales;
  todos los payloads descomprimidos y hashverificados. Complementa v120/v126.

El replay requiere los assets y fuentes registrados. No volver a correrlo sobre
un output existente: usar un directorio nuevo y la fuente congelada. No abrir las
reservas privadas para ajustar recursos o ranking.

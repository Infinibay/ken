# Retomar sin reconstruir la investigación

## Objetivo y autorización

Continuar hasta>=90% top1 de pieza correcta en las mismas200 consultas, conservando
top10 nativo197/200 y recursos CPU/RAM razonables. El usuario retiró la suficiencia
de evidencia como gate primario. No release, tags ni promoción de default todavía.
Dos agentes existentes sólo tienen autorización de curación/revisión independiente;
no delegarles implementación. No abrir la reserva privada v104 ni la antigua.

## Dónde está el trabajo

Directorio propio: `output/search-engine-2026-10-14/workspace` bajo el proyecto
original `/Users/andres/Projects/ken`. Rama `codex/search-engine-top1`.
El checkout original y el clon propio contienen cambios ajenos copiados: no
reset/stash/add-all ni commits de esos cambios. Las fuentes congeladas nuevas
parten de v120 limpio y sólo overlays propios; no copiar el árbol sucio entero.

**Trampa de Git:** origin del clon propio es el checkout LOCAL, no GitHub.
Publicar sólo con URL explícita `https://github.com/Infinibay/ken.git` y verificar
`git ls-remote ... refs/heads/main`. Último checkpoint publicado y verificado:
147ae3c6169a73b21e9c165ea55b226af8ef8292. Incluye documentación y valores
completos del scoring nativo y del modelo de piezas v126. No tags/release.

## Cambios nuevos propios en curso

- `src/ken/retrieval/model.py`: nuevo piece_kind opcional, cuatro valores válidos.
- `intent.py`: requested_piece_kind independiente de exact lookup y
  requested_piece_path para petición explícita de una ruta.
- `owner_ranking.py`, `ranking_trace.py`: transportan tipo sin cambiar los251
  valores viejos; restore de trazas antiguas sigue admitido.
- Nuevo `piece_ranking.py`: PieceCandidate valida fuente/identidad/miembros;
 262 señales separan declaración, pieza completa, prior nativo y metadatos;
  PieceReranker aplica sólo a class/module/file, preserva símbolos y prioridad
  exacta/ruta. Consume los mismos modelos estáticos; el bosque corre con NumPy.
- `experiments/search-engine/verifiable_cpu_run.py`: pasa piece_kind del caso.
- Nuevos helpers: piece_candidates.py, piece_feature_capture.py,
  piece_rank_control.py, document_scoring.py. Fuente y datos nunca incluyen
  respuestas esperadas durante extracción.
- Nuevas pruebas: test_requested_piece_kind.py, test_piece_ranking.py.
- CONSTRAINTS.md tiene aclaración explícita vigente; los protocolos sellados
  históricos conservan sus definiciones.

## Estado y recibos cerrados

- v122 falló antes de leer consultas por faltar tree_sha256 en el manifiesto;
  conservado, no usarlo. v122b lo corrige sin cambios de motor.
- Tipo v122b: snapshot `output/frozen/requested-piece-kind-v122b`, recibo
  9fc61ec50d71271beb3651901c7019e6875d225b9691d78bf9f7f4d630d1d394.
  ALL200 cerrado en `output/development/requested-piece-kind-v122b`;
  registration SHA21eebbfe8213f1134a8138d9b940bed04ee2e357021564dfe34e4ca1df5b0ce3.
  Informe:requested-piece-kind-report-v122b,168/200 y197/200, scores/pools iguales.
- Señales completas v123: snapshot `output/frozen/whole-piece-ranking-v123`,
  recibo902cbe6bccf9acf1a8ba2d78d0c58ddb0eb15a884693ab434abf3f5f84ab807a;
  datos `output/development/whole-piece-features-v123` (8npz, candidatos y tiempos).
- v124:whole-piece-ranking-control-v124,172/200; v125:whole-piece-scope-control-v125,
 174/200; v126:piece-path-identity-control-v126,175/200. Todos bajo
  `output/development`; cada uno contiene modelos por repo, scores, respuestas,
  registro, summary y graded-rows. 197/200 top10 en todos, membresía idéntica.
- v126 snapshot:`output/frozen/piece-path-identity-v126`;
  registration SHA4a963e133555963f1999eedaa907b6e9cfd9372e23f37d51055b2e123a2fa3a6.
  Por tipo:class47/50,module45/50,symbol43/50,file40/50. Faltan5 aciertos netos.

## Pruebas y entorno

TDD rojo/verde visto para tipo explícito, inferencia sin identidad exacta,
trazas, separación declaración/miembros, modelo de piezas, símbolos intactos y
ruta explícita. La suite retrieval completa (282casos) pasa contra la fuente
limpia congelada v126; mypy pasa338archivos de fuente. Los11962pares de valores
documentados y todos sus payloads se verificaron por hash y reproducción exacta.
Repetir validaciones pertinentes después de cualquier cambio nuevo.
Todavía falta medir el nuevo pipeline completo; sólo hay coste de extracción
separado. No declarar SLA final con esos tiempos.

LightGBM de entrenamiento necesita la biblioteca OpenMP existente:
`DYLD_LIBRARY_PATH=$PWD/.venv/lib/python3.12/site-packages/sklearn/.dylibs`.
No instalar ni usar Torch para servir o entrenar este bosque. Comando del control:

```sh
DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.12/site-packages/sklearn/.dylibs" \
PYTHONPATH=output/frozen/piece-path-identity-v126/src:output/frozen/piece-path-identity-v126/experiments/search-engine \
.venv-model-runtime/bin/python \
output/frozen/piece-path-identity-v126/experiments/search-engine/piece_rank_control.py \
--features output/development/whole-piece-features-v123 \
--public-cases output/development/verifiable-pieces-v98-public/cases.jsonl \
--output NUEVO_DIRECTORIO
```

El primer intento v124 falló al importar LightGBM por libomp ausente en rpath,
antes de leer consultas/Gold. Usar DYLD anterior; inferencia NumericRanker no
requiere LightGBM/OpenMP. Parámetros fijos:160árboles,15hojas,min_child40,
lambda2,learning_rate.08,truncation5,un hilo,seed42. No hubo HPO.

## Controles posteriores y trabajo en curso

- v127 (hechos de declaración/contrato):175/200, sin mejora frente a v126.
  Prototipo conservado en snapshot; fuente viva retirada. No añadir su coste.
- v128 (truncation1):174/200; rechazado. Se mantiene truncation5.
- v131 (aprendizaje residual):173/200; rechazado. Sus modelos exportan sólo
  el residuo: requieren sumar el prior y NO se pueden servir como los de v126.
  El controlador vivo fue restaurado a la política v126 antes del nuevo replay.
- v129/v130 combinan orden v126 con scores68M históricos de las mismas piezas.
  Prefijo3 da177/200; prefijo10 da180/200. Son simulaciones de orden, no nueva
  inferencia. Ambos conservan197/200 top10. Fórmula exacta y límites en README.
- v132 repite el pipeline completo en CPU: recuperación nueva, tarjetas compactas
  v102 regeneradas, bosque v126, inferencia68M FP32 nueva y RRF60 peso0.5.
  Productor `experiments/search-engine/piece_complete_run.py`; snapshot
  `output/frozen/piece-complete-cpu-v132`, recibo
  3121eef43c19283275f06f0a7703446e31a02630e5179f14f313bcaee1503a18.
  Salida `output/development/piece-complete-cpu-v132`. Gold sólo después de que
  el estado sea `ALL200 complete CPU outputs closed without Gold`.

El modelo68M es el ya medido; no se buscó otro. No afirmar90% real ni sus costes
hasta cerrar y verificar ese replay. Modelo150M sigue sin ejecutarse.

## Hipótesis investigada, sin mejora observada

Los siguientes pasos deben usar un solo cambio por ensayo. Los fallos restantes
incluyen declaración de anotación/interfaz frente a consumidor, benchmark frente
a implementación y contratos que el tokenizer no expresa (p.ej.return'' pierde
la noción de cadena vacía; transient pierde la equivalencia con no serializado).
v127 investigó hechos sintácticos y condiciones de comportamiento explícitas,
sin listas de rutas, nombres del benchmark o reglas por ID; las pruebas con
ejemplos ajenos al corpus pasaron, pero ALL200 no mejoró. Eso no prueba que esos
hechos sean inútiles en general: sólo que esta extracción y este bosque no
añadieron aciertos sobre175/200.

No hay un modelo mayor nuevo en prueba:150M descargado/preparado pero no ejecutado;
ensayos neuronales pausados por el usuario. La prioridad sigue siendo Ken.

## Archivos que leer después

1. README.md y FEATURES-251.md en esta carpeta; caso concreto en CASES.md.
2. docs/design/requested-piece-ranking.md para responsabilidades y compatibilidad.
3. Resumen cerrado v126 y fuente piece_ranking.py para continuar desde87,5%.
4. Versionar sólo cambios propios, respaldar modelos/feature receipts/controles,
   verificar tests y subir explícitamente a GitHub main. No incorporar archivos
   ajenos ni snapshots viejos v118/v119 con payload extranjero.

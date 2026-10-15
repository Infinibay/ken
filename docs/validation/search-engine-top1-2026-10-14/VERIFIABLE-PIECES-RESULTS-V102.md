# Piezas verificables: comparación CPU v102

La cobertura inicial ya alcanza el objetivo:197/200 consultas (98,5%) tienen la
pieza correcta entre los diez primeros resultados. El objetivo final de90% aún
no se cumple. Ken coloca la pieza correcta primera en168/200 (84%), pero sólo
76/200 (38%) de sus respuestas permiten verificar todos los requisitos visibles.

Todas las consultas cuentan, incluidos fallos y ausencia de evidencia. Cada tipo
tiene50consultas;120EN/80ES,160de comportamiento/40de identificación cualificada,
ocho repositorios. Es un conjunto descriptivo nuevo; no equivale al400anterior,
a la reserva privada histórica ni al NDCG@10 de Semble.

| Configuración | Pieza correcta top1 | Pieza correcta + evidencia verificable |
|---|---:|---:|
| Ken actual |168/200 (84%)|76/200 (38%)|
| Ken + Ettin17M INT8 |132/200 (66%)|64/200 (32%)|
| Ken + Ettin32M INT8 |140/200 (70%)|67/200 (33,5%)|
| Ken + Ettin68M INT8 |164/200 (82%)|78/200 (39%)|

La mejora conjunta de68M es sólo2consultas; pierde4identidades correctas netas.
No justifica reemplazar el orden de Ken. No hay alternativas válidas no listadas
señaladas por el criterio predefinido de evidencia positiva/identidad negativa.
Los intervalos Wilson descriptivos de utilidad son31,6–44,9% en Ken y32,5–45,9%
en68M. Las ocho agrupaciones por repositorio limitan la precisión del contraste.

| Tipo (50 cada uno) | Recall10 | Ken: identidad / conjunta |17M: identidad / conjunta |32M: identidad / conjunta |68M: identidad / conjunta |
|---|---:|---:|---:|---:|---:|
| Clase |50|44 /22|39 /20|38 /17|45 /20|
| Módulo |49|44 /11|31 /8|32 /10|38 /10|
| Símbolo |50|43 /27|34 /21|36 /22|42 /27|
| Archivo |48|37 /16|28 /15|34 /18|39 /21|

De las92respuestas de Ken con identidad correcta pero utilidad insuficiente,
84reciben relevancia2/suficiencia1;5reciben1/1 y3reciben1/0. Esto localiza gran
parte del problema en la evidencia presentada. La inspección inicial detecta
ventanas limitadas por fragmentos del índice, presupuestos sin aprovechar,
condiciones finales omitidas y llamadas a helpers cuyo comportamiento no se ve.
No se cambian los criterios para convertir esos fallos en aciertos.

## Descartar y ordenar

Se probaron dos políticas congeladas antes de leer consultas: el mismo filtro
con orden neural o preservando el orden de Ken. Los umbrales son el mínimo de
40tarjetas correctas de calibración, incluyendo20con evidencia incompleta. Nunca
se considera irrelevante una tarjeta sólo por ser incompleta o no figurar enGold.

Preservar el orden de Ken después del filtro mantiene168identidades/76conjuntas
en los tres modelos: no mejora top1. El filtro de17M pierde una cobertura correcta
(Recall10 posterior98%);32/68mantienen98,5%. Cada modelo descarta3de5negativos
claramente irrelevantes de calibración; ese denominador pequeño no permite una
garantía general. Los scores no separan por sí solos irrelevancia y verificabilidad.

## CPU, memoria y estabilidad

| Modelo añadido | Mediana pipeline |p95 observado | Mediana reranker | Pico proceso completo |
|---|---:|---:|---:|---:|
|17M INT8 |1,392s|19,773s|205ms|1547MiB|
|32M INT8 |1,580s|2,725s|462ms|1554MiB|
|68M INT8 |2,348s|12,313s|1297ms|1645MiB|

CPU obligatoria,2hilos intra/1inter,batch4,512tokens, sinTorch/Transformers/GPU.
Los p95 de17/68incluyen fuerte variación temporal del equipo y recuperación común,
con carga externa deCPU observada. No constituyen una comparación causal de
velocidad entre tamaños. Se conservan todos los tiempos. El baseline original
reutilizado midió2,501s/11,820s de mediana/p95; su repetición de rendimiento,
registrada antes de ver calidad y con200respuestas idénticas, dio1,152s/2,217s.
No se suman ni restan percentiles para estimar latencias. Los picos incluyen índice,
traducción, embeddings, carga y calentamiento: no son RAM de los pesos del reranker.

470de1988pares por modelo se truncan a512tokens; el juez ve la tarjeta completa,
por lo que el contexto disponible al modelo y al consumidor puede diferir.

El adaptador original usaba padding0; los tres modelos publican50283. La corrida
v102 corrigió ese error antes de abrir Gold. V98y sus perfiles quedan diagnósticos.
En un probe posterior, sintético y sin consultas del corpus, INT8 cambia ranking
al permutar/agrupar los mismos pares (delta máximo observado1,115). El mismo17M
enFP32 mantiene orden con diferencias≤0,000002. FP32 pesa~67,6MB frente a17,4MB
del grafoINT8; el probe de10pares mide19–416ms enCPU, no pipeline completo.
No demuestra una mejora de calidad ni adopta un proveedor GPU. Indica que la
precisión/tamaño de lote deben validarse antes de promoción o calibración portable.

## Integridad y continuación

800salidas cerradas antes de Gold. Los345juicios originales se conservaron;
317opiniones de entradas visibles idénticas se reutilizaron y21pares nuevos se
juzgaron a ciegas:338entradas distintas. Los1200selecciones de filtros no añaden
pares nuevos. Cierre FINAL a36f4b4c0c1f70645d9ba90b8be24cb751f7dfd6ae22f2cdb44c032596857032
anterior al primer acceso de root a Gold principal. Calibración ciega60/60acuerdo,
0/40falsas aceptaciones. Los contextos persistentes y familiaridad de curadores
están declarados; ninguna opinión se corrigió por feedback de Gold.

Una incompatibilidad de vocabulario de variantes de calibración se normalizó en
una copia: sparse→identity_only_insufficient y distractor→faithful_plausible_distractor.
Los60IDs, etiquetasR/S, expected_pass, hashes y evidencia permanecen idénticos;
20suficientes+20incompletas protegidas+20distractoras. Los originales y la política
fija no cambiaron. Dos pruebas y revisión técnica independiente lo verifican.

El conjunto200ya es desarrollo tras abrir sus referencias. La nueva reserva v104
se cura independientemente con las mismas cuotas, tipos, presupuestos y criterios;
excluye todos los173archivos target/support de desarrollo y calibración. Root no
recibe consultas ni identidades antes de congelar el nuevo motor. La reserva
histórica ken-search-acceptance-20261014 permanece cerrada.

Fuentes locales: output/development/verifiable-pieces-report-v102/report.json,
verifiable-shadows-report-v102/report.json y verifiable-stability-correct-padding-v103/report.json.
No hay cambio de default de producción ni afirmación de90%.

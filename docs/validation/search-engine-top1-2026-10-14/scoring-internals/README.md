# Cómo puntúa Ken y por qué falla el primer resultado

Este documento conserva el análisis de scoring, sus números y sus límites. Se
lee primero al retomar la investigación; no hace falta reconstruir el debug.
Fecha de trabajo del usuario: 15 de octubre de 2026.

Estado al16 de octubre: motor público CPU y salida compacta por defecto.
Cache estático ef211af y corrección aislada de identidad v172 verificados en MCP:
200originales expuestas191/197(95,5%/98,5%); nueva batería expuesta200sólo símbolos
159/195(79,5%/97,5%), antes150/195. Los40locators explícitos ya aciertan; consultas
de comportamiento nuevas119/160. Última aceptación independiente, frozen145:
177/198(88,5%/99%), NO cumple90. Reserva nueva cerrada. No mezclar cohortes.
Controles H/J/K/L/N/P/Q/R/MLP/S rechazados y costes/causas en
[registro público](PUBLIC-DEFAULT-V140-V145.md) y
[captura completa v172](../../qualified-source-locator-2026-10-16/README.md).
Los controles181–184 tampoco alcanzaron90: mejor170/195en desarrollo nuevo,
191/197actualoriginal sin cambios. [Diagnóstico completo y controles](../../search-ranking-diagnostics-2026-10-16-v181-v184/README.md).
La combinación predeterminada conserva PotionCode16Mv2, contexto CodeRank INT8,
Ettin68M CPU y fusión fija; los controles rechazados no se activan. El comando
global uv-tool usa un wheel local noeditable; no se hizo release.

Adaptación externa A186 del mismo modelo de 68M cerrada: 2768→2799/3000 en validación
externa de 4 candidatos; no es la métrica de Ken. Tail final y ONNX CPU equivalente
guardados. A189 público de 400 consultas sigue en curso: el default y sus porcentajes de arriba
siguen vigentes. [Receta, artefactos, incidentes y validación pendiente](../../external-code-adaptation-2026-10-16-v185-v188/README.md).
Revisión independiente de 26 fallos raw recuperables: 13 núcleos visibles,
9 necesitan contexto externo y 4 pierden lógica al armar el card; ningún card
correcto se trunca a 512 tokens. Referencias intactas; no prueba causalidad.

## Objetivo y snapshots que no se deben mezclar

El usuario exige al menos 90% de **pieza correcta en top1**: clase, módulo,
símbolo o archivo. Retiró explícitamente la suficiencia del contexto retornado
como condición del acierto. Esa suficiencia se informa aparte. Se conservan las
200 consultas y los diez candidatos nativos: Recall10=197/200, 98,5%.

| Snapshot | Qué cambió | Top1 correcto | Recall10 | Naturaleza |
|---|---|---:|---:|---|
| v120 | Debug del ranking nativo de owners | 168/200, 84% | 197/200 | Replay nativo completo y scores reproducidos |
| v121 | Igualar solamente rrf_rank a la mediana de cada consulta | 157/200, 78,5% | 196/200 | Control diagnóstico rechazado: gana4, pierde15 |
| v122b | Transmitir piece_kind por separado | 168/200, 84% | 197/200 | ALL200; conserva todos los scores y pools |
| v124 | Bosque de piezas completas, también aplicado a símbolos | 172/200, 86% | 197/200 | CV excluyendo cada repositorio; gana7, pierde3 |
| v125 | Aplicar la nueva etapa sólo a clase/módulo/archivo | 174/200, 87% | 197/200 | Mismos modelos; gana7, pierde1 frente a nativo |
| v126 | Respetar una ruta solicitada explícitamente | 175/200, 87,5% | 197/200 | Misma CV; gana7, pierde0 frente a nativo |
| v127 | Agregar hechos léxicos de declaraciones y contratos | 175/200, 87,5% | 197/200 | Sin mejora; se retiraron las señales y su coste |
| v128 | Cambiar sólo truncation5 por truncation1 en LambdaRank | 174/200, 87% | 197/200 | Rechazado; se mantiene truncation5 |
| v131 | Aprender un residuo sobre native_to_best | 173/200, 86,5% | 197/200 | Rechazado; no usar sus JSON como modelos v126 |
| v129 | Combinar v126 con los scores históricos68M, primeros3 | 177/200, 88,5% | 197/200 | Simulación de órdenes; no inferencia nueva |
| v130 | Misma combinación, primeros10 | 180/200, 90% | 197/200 | Simulación; requiere replay completo para confirmar |
| v132 | Repetir la búsqueda y la inferencia completas en CPU | 180/200, 90% | 197/200 | Confirmado en ALL200; p95 total5,334s, pico1,976GB |

v126 por sí solo llega a175/200; v132 confirma180/200 combinándolo con el68M
existente y la fusión fija. Ambos son candidatos experimentales, **no el default
publicado ni una certificación privada**. El tiempo por100 archivos todavía
supera la referencia del usuario en cuatro repositorios pequeños. Ver el
[resultado completo, costes y límites](COMPLETE-CPU-V132.md). No equiparar la
inferencia sola con la latencia total ni el desarrollo expuesto con aceptación.

## Fusión con el reranker: fórmula y límites

Son dos órdenes sobre las **mismas diez piezas**: primero el ranking de Ken
v126; luego el orden descendente de logits del 68M. Se calcula
`F(i) = (1-w)/(60+r_Ken(i)) + w/(60+r_neural(i))`, con posiciones desde1 y
`w=0.5`. Los empates conservan el orden de Ken. Una ruta pedida explícitamente
mantiene prioridad. No es una media de logits ni una probabilidad de relevancia.

En los archivos históricos, `fp32_rrf50` significa **peso neuronal0.5**; el50
no es la constante de rango, que sigue siendo60. `fp32_rrf25` usa peso0.25.
La fuente original de esta decisión es `verifiable_precision.precision_orders`
del snapshot v110; la implementación equivalente nueva es
`src/ken/retrieval/reranker_fusion.py`. No confundir esta fusión final con el RRF
de canales de recuperación ni con la señal `rrf_rank` del bosque de owners.

v130 reutiliza scores ya cerrados de v110 para las tarjetas compactas v102 y
los reordena sobre el nuevo orden de piezas. Frente a v126 gana7 consultas y
pierde2, saldo+5. Son class47, module45, symbol45 y file43, de50 cada tipo.
Eso sugiere complementariedad; no demuestra que el modelo entienda las causas
de los fallos ni que usar las tarjetas actuales dé los mismos resultados.
El texto de política de su productor conserva una frase «remaining7» del
ensayo prefijo3; el código efectivo usa `[:10]`, comprobado en las200 órdenes.
Se conserva ese registro original y se deja aquí la aclaración.

El replay v132 vuelve a recuperar los candidatos y a construir las tarjetas
compactas desde las fuentes reales, valida su digest contra v102, aplica el
bosque v126 real y valida su orden contra el control cerrado, y vuelve a
ejecutar ONNX68M con CPUExecutionProvider. Incluye esas comprobaciones, la
proyección de la traza, el modelo y la serialización en el tiempo por consulta.
No sustituye resultados por las referencias: sólo compara después de producirlos.
Gold no se abrió hasta cerrar ALL200. Confirmó180/200 y los mismos órdenes que
la simulación, con inferencia nueva. Sigue siendo desarrollo expuesto; no
aceptación privada ni default de la herramienta.

## Recorrido del ranking nativo

1. Se mantiene una identidad canónica por owner: ruta, kind, qualname, owner y
   definition_ordinal. Los pasajes y regiones pertenecen a esa identidad y versión
   de fuente; varias regiones pueden formar un solo owner.
2. Se recuperan propuestas por identidad exacta, BM25F, embeddings estáticos de
   identidad/comportamiento, consulta original/expandida y vectores contextuales
   de código. La traducción/expansión es local. El perfil v120 usa
   potion-code-16M-v2 y CodeRankEmbed ONNX INT8; los vectores de repositorio ya
   están preparados. No confundir «sin cross-encoder reranker» con «sin modelos».
3. RRF combina posiciones de canales: `sum(1/(60+posición))`. Hay más de una
   fusión en el recorrido. Las familias y variantes pueden estar correlacionadas;
   RRF no afirma independencia estadística.
4. Los owners propuestos se enriquecen con mediciones de código original y
   expandido y dos vistas separadas: **contract** (cabecera+documentación, fuente
   vacía) e **implementation** (cabecera+implementación, documentación vacía).
   Se miden incluso candidatos propuestos por otro canal. Son dos vistas, no
   siete copias materializadas. Los vectores se comparten/mappean en sólo lectura.
5. Se calcula el vector de251 señales. Los primeros227 valores describen
   recuperación, cobertura de términos y forma del owner;8 son contexto de
   código y16 las dos vistas × dos consultas × cuatro normalizaciones.
6. Un **bosque aprendido de árboles aditivos**, exportado a JSON, calcula
   `score(x)=sum(hoja_arbol_t(x))`. Las hojas ya incorporan learning_rate. En
   inferencia bastan NumPy y comparaciones; no se carga LightGBM para puntuar.
7. Orden: prioridad exacta, luego score descendente, luego orden estable de
   propuestas en empates. Una identidad exacta única puede saltar la codificación.
8. La proyección nativa de owners a piezas conserva la primera aparición de cada
   pieza: clases por pertenencia léxica, módulos por importabilidad, archivos por
   ruta, símbolos por tipos admitidos. Por eso el método de mayor score puede
   decidir el puesto de una clase o archivo entero.

Código propietario de cada decisión: `src/ken/retrieval/{candidates,proposals,
evidence_features,alignment,contextual_features,source_views,numeric_ranker,
owner_ranking,ranking_trace}.py`; proyección usada en el benchmark:
`experiments/search-engine/{verifiable_pieces,ranking_diagnostics}.py`.

## Qué significa cada número

[FEATURES-251.md](FEATURES-251.md) enumera las251 columnas en su orden exacto,
con el cálculo de cada una. No hay un coeficiente fijo por columna: un valor
puede favorecer a candidatos distintos según las ramas e interacciones.

La cobertura de términos usa `s_i=max_j(q_i·d_j)`: cada término de consulta toma
su mejor término del campo. Se calculan media, mínimo, p25, fracciones >=0.5/0.7
y media ponderada por rareza dentro del pool. Repetir un término de documento no
añade votos. Esto aproxima cobertura semántica; no prueba relaciones, conjunción,
orden de operaciones ni que todos los términos describan la misma condición.
Consulta: hasta128 términos; campos: hasta4096 términos distintos, en el orden
registrado. El tokenizer conserva identificadores completos y componentes,
normaliza NFKC y elimina stopwords. Los límites pueden descartar información.

`mean_cosine` compara el vector de consulta con la media normalizada de términos
del campo. `min` mide el término menos cubierto. Un `above70` de1 significa que
todos superaron el umbral de similitud; no significa probabilidad de relevancia1.
Los campos calls/returns y la separación executable/comments son proyecciones
léxicas: no son un análisis de llamadas resueltas ni de flujo de valores.

No confundir los cuatro puestos:

- `proposal_<canal>`: recíproco de la posición en ese canal.
- `rrf_rank`: recíproco de la posición del valor RRF dentro del pool propuesto.
- `owners[].rank`: puesto posterior al bosque de owners.
- `pieces[].rank`: puesto posterior a proyectar y deduplicar piezas.

Ejemplo: el serializador puede tener `rrf_rank=1/49` y terminar como pieza2
después del bosque. Un owner en131 puede representar el archivo73 si muchos
owners anteriores pertenecen a los mismos archivos. `*_to_max` es **x-máximo**,
no x/máximo. `*_relative` usa rango min–max; `*_rank` usa posición estable.
Estas normalizaciones dependen del pool. Los scores y márgenes se interpretan
dentro de una consulta/modelo; no se comparan entre folds como probabilidades.

## Qué reproduce el debug y qué no demuestra

RankingTrace conserva la matriz **real usada**, las señales crudas, fuente,
identidad, fingerprints, orden inicial y final. No recalcula una aproximación
para explicar una respuesta. v120 reprodujo exactamente101764 scores y su orden
en las200 consultas; los32 fallos los decide `numeric_model_score`, sin empates
ni bypass exacto. No se encontró un error de ordenación que explique esos casos.

Para un par elegido/aceptable, NumericRanker.explain_pair recorre ambos caminos
en cada árbol. Si sus hojas son `L_t` y `R_t`, el margen es
`sum(L_t-R_t)+residuo_de_acumulación`. Cada diferencia se agrupa bajo la primera
rama donde los caminos divergen. Es una contabilidad exacta del bosque, **no un
efecto causal aislado, un peso lineal ni SHAP**. Las ramas completas se guardan.
Una señal con el mismo valor en ambos candidatos puede decidir una rama común
y condicionar cómo se usan las demás. Que su margen agrupado sea cero no significa
que el bosque no la use. Esto importa especialmente para el tipo de pieza pedido.

Ejemplo vp-mf-047: elegido -0.586761 frente a aceptable -1.093991; margen
0.507230. `rrf_rank`=0.5 frente a0.020408 contribuye+1.670859 en esa contabilidad;
calls_mean_cosine=0.084833 frente a0.388648 contribuye-0.606647 y la fracción
documental0 frente a0.034483 contribuye-0.603348. Otros árboles completan el
margen. No se puede inferir que quitar RRF arregle todo: el control v121 hizo
exactamente una intervención y perdió más aciertos de los que ganó.

## Casos y valores conservados

- [CASES.md](CASES.md): índice de los32 fallos;29 tienen el aceptable en top10.
- `cases/<id>.md`: consulta, pieza y owner elegidos/aceptables, ambos puestos,
  score y margen exactos, las251 entradas de ambos candidatos y señales crudas.
- `pair-feature-values.csv`:8032 pares de valores, con nombres e índices,
  diferencias y margen agrupado por señal. Incluye valores iguales y ceros.
- `forest-pairs.jsonl.gz`: las32 comparaciones originales con **todos** los
  caminos, umbrales, valores, hojas y primeras divergencias de los árboles.
- `VALUES-MANIFEST.json`: hashes, snapshot y conteos verificados. La generación
  compara cada explicación con el modelo registrado antes de publicarla.
- [PIECE-FEATURES-262.md](PIECE-FEATURES-262.md) y
  [PIECE-CASES-V126.md](PIECE-CASES-V126.md): señales y fallos restantes del
  candidato nuevo. Sus15 pares numéricos contienen3930 pares de valores en
  piece-pair-feature-values.csv y todos los árboles en piece-forest-pairs.jsonl.gz.
  Los7 fallos de símbolo remiten al bosque nativo que realmente decidió su orden;
  no se explican usando un bosque de piezas que no se les aplicó. Otros3 fallos
  tienen el aceptable fuera del top10 y no se inventa una puntuación de pieza
  que ese candidato nunca recibió en esta etapa.

Leer un par completo sin descomprimir otros archivos:

```python
import gzip, json
with gzip.open('forest-pairs.jsonl.gz', 'rt') as stream:
    case = next(json.loads(line) for line in stream if json.loads(line)['id']=='vp-mf-047')
print(case['comparison']['numeric']['trees'][0])
```

## Findings comprobados e hipótesis

**Comprobado:** todos los200 aceptables están en el pool completo. Entre32
fallos,18 los tienen segundos;4 terceros;4 cuartos; uno en5,6,7,18,21 y73.
Hay6 fallos de clase,6 de módulo,7 de símbolo y13 de archivo. El problema
dominante está en elegir entre candidatos cercanos, con tres consultas además
fuera del top10 fijo. No se eliminan esas tres del denominador.

**Comprobado:** query_kind_class fue0 en las50 consultas de clase. La intención
antigua asigna kind a ciertas búsquedas de identidad nombrada; no representa el
tipo de pieza pedido por toda consulta descriptiva. v122b conserva esa semántica
del modelo viejo y transporta `SearchRequest.piece_kind` por separado.

**Comprobado:** la clase hereda al mejor owner. En vp-cs-005 gana CodeGen gracias
a CodeGen.try frente a la clase Try. Lo mismo puede promover un consumidor,
wrapper o clase externa sobre la pieza especializada que se pide.

**Hipótesis respaldada por pares, no efecto aislado:** las señales disponibles
no discriminan suficientemente definición/consumidor, declaración/ejecución,
datos/implementación y operaciones cercanas. Ejemplos: typing test frente a
define; MethodOrderingVisitor frente a MethodOrderer; evaluator frente a
annotation; unquote frente a unquote_to_bytes; __init__ frente a read.

**Prueba rechazada:** neutralizar sólo rrf_rank a la mediana por consulta baja
168 a157;4 ganancias y15 pérdidas. Otros priors correlacionados permanecen; no
equivale a reentrenar un modelo sin RRF ni demuestra importancia causal global.

**Mejora experimental observada:** v126 evalúa la declaración y el contenido de
la pieza por separado, con un bosque de262 señales. Mantiene símbolos sin
cambios y respeta una ruta pedida explícitamente. Llega a175/200 excluyendo de
cada entrenamiento el repositorio evaluado, con siete ganancias y ninguna
pérdida frente a168. [Estado y pasos para retomar](RESUME.md).

## Recursos y límites de las cifras

v116 nativo completo preparado: mediana1218.642ms, p952362.571ms,
máximo3603.967ms, pico1531346944bytes. La nueva extracción de señales de piezas,
medida separadamente: mediana80.280ms, p95266.594ms y pico394657792bytes en ese
proceso de extracción; **no sumar p95 ni picos** para afirmar el coste completo.
Esos tiempos de extracción no eran el coste completo. El replay con fuente
validada quedó cubierto para la composición v132:mediana4162.126ms,
p955334.297ms,pico1975648256bytes. La referencia de1s/100 archivos no se cumple
en los cuatro repositorios pequeños; la tabla y las mediciones completas están
en COMPLETE-CPU-V132.md. No declarar resueltos los recursos por alcanzar90%.

Todo esto es desarrollo expuesto. Se conservan las reservas privadas cerradas,
los criterios vigentes, los recibos y las pérdidas de cada control. Ninguna cifra
de este documento acredita90% privado ni sustituye la comparación de aceptación.

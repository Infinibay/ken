# Contexto fuente y presupuesto del reranker, v189–v193

El motor instalado conserva **191/200 top‑1 y 197/200 top‑10** en la batería
original; **159/200 y 195/200** en las 200 consultas nuevas, todas de símbolos.
Los experimentos descritos aquí son desarrollo expuesto. La reserva nueva,
incluidas sus consultas, sigue cerrada. No hay release ni cambio de default.

## Qué ve el modelo y dónde se pierde información

Ettin‑68M recibe por separado cada pareja de consulta expandida y tarjeta fuente.
La tarjeta identifica tipo/ruta/símbolo, y contiene declaración, ventanas de
implementación y documentación. La salida compacta para CLI/MCP tiene otro
presupuesto: cambiar la entrada neuronal no debe cambiar qué referencia recibe
el usuario ni confundir un auxiliar con la pieza principal.

La proyección actual admite 64 líneas físicas, cuatro extractos y 12.000 caracteres
de JSON canónico. `_window` elige una ventana por coincidencias léxicas con la
consulta; los empates prefieren la primera. Eso puede excluir código anterior o
posterior, incluso cuando toda la función habría cabido. El tokenizer añade una
segunda restricción: 512 tokens entre pregunta/documento/separadores, recortando
sólo el documento. Ese último recorte no entiende el programa.

**512 es una configuración de Ken, no el máximo del modelo.** La
[ficha oficial de Ettin‑68M](https://huggingface.co/cross-encoder/ettin-reranker-68m-v1#model-description)
y los archivos config/tokenizer fijados en d166fa88… declaran **7.999 tokens**.
El ONNX original 8e22c1a0… se probó realmente en CPU a 512/1024/2048; la pregunta
corta de control tuvo el mismo score exacto. No se infiere rendimiento a7.999.

La revisión independiente V190 reconstruyó los 260 candidatos de 26 fallos
recuperables del reranker original: todos sus hashes coincidieron. Ningún
candidato correcto sufrió el recorte a512: sus parejas tenían123–471 tokens.
Trece tenían las operaciones centrales visibles, nueve necesitaban contexto
externo y cuatro perdían lógica durante selección/ownership anterior al modelo.
Esto limita la explicación: el recorte final no causó esos 26 fallos, pero la
representación fuente sí omitía información en algunos. Disponibilidad no
prueba por sí sola la causa del score. Referencias sin cambios.

## A189: la adaptación externa no transfirió su mejora

La adaptación fija A186 subió2768 → 2799/3000 en validación externa disjunta por
repositorio, con 4 candidatos por consulta. Al aplicar el mismo checkpoint fijo al
recorrido público completo de 400 consultas, ninguna política pasó el objetivo:

| Política adaptada | Top‑1 original /200 | Top‑1 nuevo /200 |
|---|---:|---:|
| Logit crudo para todas las piezas |165|167|
| RRF fija para todas las piezas |193|159|
| Crudo símbolos, RRF agregados |189|167|

Todas mantienen197/195 top‑10. El original crudo sólo para símbolos ya obtenía
189/169. No se activó el adaptado. La política por tipo se registró antes del
tail final; no se eligió un checkpoint ni hiperparámetros con estas400etiquetas.
El primer grader no importó LightGBM por libomp; se relanzó el MISMO productor
con DYLD_LIBRARY_PATH, sin alterar scores/criterio. Los dos logs se retienen.

En JUnit5 hubo cinco observaciones de 17–102 segundos; p95 total 28,702 s y pico
2.128.560.128bytes en esa captura. Se conservaron todas. El origen no está probado;
un snapshot posterior no mostró swapping activo y no justifica atribuirlas a
presión de memoria. La equivalencia del grafo no certifica coste del candidato.

## B191/B192: aportar más fuente no alcanza por sí solo

B191 conserva todas las líneas originales y añade el cuerpo propio completo
cuando cabe en los mismos límites. No incorpora código anidado ni auxiliares.
B192 reutiliza componentes V114/V116: contenedores léxicos íntegros con dueños
atribuidos, y definiciones de llamadas visibles resueltas de forma unívoca en el
mismo archivo. No afirma ejecución de código anidado ni adivina dispatch.
Python/JS/TS admiten esos enlaces; Java, constantes/fixtures/imports no están
cubiertos por ese extractor de auxiliares.

B192 mantiene una ampliación sólo si la pareja completa cabe en 512 tokens; si no,
vuelve al documento original. Nunca corta a ciegas una ampliación nueva. Cada
cambio se midió solo y combinado, sobre los mismos candidatos y modelo original.

| Entrada neuronal | Top‑1 original, RRF / crudo símbolos | Top‑1 nuevo, RRF / crudo símbolos |
|---|---:|---:|
| Original |191 /189|159 /169|
| B191 cuerpo propio |191 /189|158 /169|
| B192 contenedor léxico |192 /189|159 /169|
| B192 auxiliares |191 /189|159 /168|
| B192 contenedor +auxiliares |192 /189|159 /169|

Todos conservan197/195 top‑10. B192 propone 163/515/618 ampliaciones, respectivamente,
en las 210 consultas simbólicas no exactas; acepta 134/298/380. Las 29/217/238 restantes
exceden 512 tokens y conservan la entrada original. Se cuentan tarjetas, no queries.

Con ranking crudo, el contenedor gana 168 y pierde 068 en la nueva cohorte; los
auxiliares ganan 015/018 y pierden 049/060/137. Combinados ganan 015/018/168 y pierden
049/068/137. Los ID tienen prefijo symdev‑20261016‑. Ni siquiera el oráculo que
elige el primer resultado correcto entre estos cuatro órdenes supera 172/200:
es sólo diagnóstico y está prohibido en ejecución. No basta con elegir uno de
esos ganadores; quedan diferencias semánticas por aprender/discriminar.

23 pruebas de composición/propiedad/dependencias pasan. Se conserva el fallo
inicial por módulo todavía inexistente y su ejecución verde. No cambió código
de producción ni el wheel instalado.

## Cómo se compara sin mezclar criterios

Las 250 consultas simbólicas reutilizan exactamente los pools actuales 172;
40 locators cualificados conservan su bypass. Las 150 consultas originales de
clase/módulo/archivo quedan sin cambios. Las puntuaciones crudas originales se
reutilizan sólo para entradas idénticas; se infiere de nuevo lo cambiado y se
comprueba un control original por consulta. D193 extiende esa identidad al par
de IDs/máscaras efectivos, sin reutilizar scores entre prefijos distintos.

El orden nativo usa únicamente piece_rank de A189, calculado ANTES del neuronal
con los bosques sin cambios: nunca sus logits adaptados. Antes de abrir Gold
expuesto, cada grader reproduce todos los órdenes 172 y cierra todas las órdenes
de sus variantes. Se exige ≥180/200 en cada cohorte y197/195 top‑10, sin promedio
para ocultar el fallo nuevo ni cambios de etiquetas/denominador.

Los 400 son desarrollo: se usan para diagnosticar y escoger futuras mejoras. No
son test independiente. La última aceptación independiente de 177/198 pertenece al
snapshot 145 histórico y no acredita el código actual. Reserva nueva cerrada.

## D193: 512, 1.024 y 2.048 tokens en CPU

Se cambiaron por separado el máximo del tokenizer y el texto ampliado B192. No
se quitaron los límites 64/4/12.000 de fuente; esto aísla el presupuesto neuronal.
Con 1.024 ya caben TODOS los documentos de ambas vistas: 74 tarjetas originales
antes recortadas y 238 ampliaciones antes rechazadas quedan completas. Con 2.048,
los IDs/máscaras efectivos son idénticos a 1.024 y no hay más código que leer.

| Texto, tokens | Top‑1 original, RRF / crudo símbolos | Top‑1 nuevo, RRF / crudo símbolos |
|---|---:|---:|
| Original,512 |191 /189|159 /169|
| Original,1024 |191 /189|159 /169|
| Original,2048 |191 /189|159 /169|
| Contenedor +auxiliares,512 |192 /189|159 /169|
| Contenedor +auxiliares,1024 |192 /189|158 /169|
| Contenedor +auxiliares,2048 |192 /189|158 /169|

Recall10 permanece en 197/195 en las 12 variantes. Ninguna llega a 180 aciertos nuevos. No se cambia
el default por esta comparación. Las observaciones de 1.024/2.048 idénticas reutilizan
sólo secuencias de tokens/máscaras exactamente iguales, nunca prefijos distintos.

La prueba CPU repitió realmente 192 llamadas de 10 candidatos: 32 consultas elegidas
por hash de ID, cuatro noexactas por repositorio, ambas vistas y 3 presupuestos.
Todos los scores nuevos coinciden con los cerrados dentro de1e-4. No se borraron
outliers. El grafo se calentó con un ejemplo corto; no se incluyen recuperación,
catálogo fuente, construcción de tarjetas ni transporte MCP en estos tiempos.

| Presupuesto | p95 neuronal original | p95 neuronal con contexto | Pico RSS del proceso, ambas vistas |
|---|---:|---:|---:|
|512|1,213s|1,273s|761.921.536bytes|
|1024|1,206s|1,834s|759.808.000bytes|
|2048|1,306s|1,944s|747.814.912bytes|

Una pasada pareada y 32 consultas no eliminan el ruido del host. En particular,
1.024 y 2.048 reciben exactamente las mismas secuencias: sus diferencias de tiempo
observadas no prueban un efecto del límite configurado. No presentar este RSS
como la RAM del motor completo. La sonda sintética a 2.048 sí llenó 2.048 tokens y
llegó a 1.018.167.296 bytes y 1,168 s por pareja, no por consulta de 10 candidatos.

El resultado dirige la próxima hipótesis: un límite mayor evita recortes, pero
no recupera lo excluido ANTES de tokenizar. Para aprovecharlo de verdad hay que
seleccionar fuente por unidades completas y presupuesto real de tokens, y
comprobar qué distinciones semánticas aún no captura el scoring. No se afirma
que ésa sea la única causa ni se promete 90% sin medirla.

## Archivo reproducible

232 payloads gzip, 6.516.586 bytes, con protocolos previos, productores, predicciones,
órdenes, resultados, fuentes/tests, fallos y replayCPU. No contiene reserva.
`output/checkpoints/source-context-and-token-budgets-v189-v193`

Manifiesto SHA-256: `9c1bb04d4debc0c8038a4a9b0a8f0544e12ac671912e2f1d18cfb2524248c922`.
El archivo de entrenamiento anterior permanece inmutable; no se duplican pesos
ni parquets. [A189](results-a189.json),[B191](results-b191.json),
[B192](results-b192.json),[D193](results-d193.json),[CPU](cpu-d193.json).

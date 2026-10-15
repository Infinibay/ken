# Contexto verificable y controles de precisión — desarrollo v105–v112

El objetivo de90% top1 conjunto aún no está alcanzado. Se exige simultáneamente
la pieza correcta y evidencia visible suficiente para todas las facetas; Recall10
se conserva en197/200 (98,5%). Las200consultas expuestas son desarrollo, no reserva
ni el NDCG público de Semble. Ninguna variante nueva es el default de producción.

## Evidencia y responsabilidad de la respuesta

| Variante | Identidad top1 | Pieza + evidencia suficiente | Recall10 |
|---|---:|---:|---:|
| v102 original de este criterio |168/200 (84%)|76/200 (38%)|197/200 (98,5%)|
| v105 definiciones propias completas |168/200 (84%)|80/200 (40%)|197/200 (98,5%)|
| v109 capacidad compartida para definiciones |168/200 (84%)|89/200 (44,5%)|197/200 (98,5%)|
| v111 relaciones locales de llamada visibles |168/200 (84%)|93/200 (46,5%)|197/200 (98,5%)|

Mismos64líneas físicas,4extractos,12000caracteres JSON canónicos y denominador200.
Cierres y citas independientes antes del reporte; sin cambiar referencias,
aceptación o consultas. v109 contra v105:17ganancias/8pérdidas; intervalo de
bootstrap por8repos del cambio [0,00957;0,08228]. v111 contra v109:4ganancias y
0pérdidas; intervalo [0,00518;0,03774]. Son diferencias de desarrollo y suponen
aplicación estable de la rúbrica, no validación en repos/consultas nuevos.

La auditoría de v105 documentó dos inconsistencias de juicio frente a v102 sobre
código exactamente igual, relativas a contratos de helpers. No se promovió ningún
fallo ni se modificó opinión/reporte. Nota y parejas acotadas se conservan. Esto
limita la comparación histórica; no es motivo para bajar el criterio.

v109 mantiene los200órdenes y autentica3928tarjetas. v111 añade helpers en40
respuestas sin retirar evidencia previa; sólo4transiciones terminan satisfaciendo
todas las facetas. LocalCallEvidence reutiliza TARGET inequívoco del analizador,
exige llamada visible y fuente actual, y conserva sólo aristas compactas de un
archivo. No hay suposición por nombre, inferencia transitoria de ejecución,
resolución importada, presupuesto oculto, ni cambio de pieza/ranking. Java aún
no recibe esta ampliación. El reparto primero-al-primer-owner puede omitir prueba
complementaria; faltan además constantes/regex y ámbitos anidados coherentes.

CPU completa preparada v111,200consultas seriales: mediana1108,79ms,
p952211,32ms, máximo3349,94ms; pico1542504448bytes (~1471MiB). Enriquecimiento:
mediana0,459ms/p95207,53ms. Son observaciones de este equipo, no promesas para
cualquier repositorio ni una mejora de velocidad atribuible frente a otras horas.

## Precisión del reranker y coste de CPU

Mismos pesos publicados, tokenizador, padding50283 y tarjetas congeladas v102.
Resultados de IDENTIDAD solamente; no están medidos como top1 conjunto.

| Control | Raw | RRF50 | RRF25 | Recall10 |
|---|---:|---:|---:|---:|
|17M FP32,10pares (v108)|146/200 (73%)|165/200 (82,5%)|171/200 (85,5%)|197/200|
|68M FP32,10pares (v110)|171/200 (85,5%)|175/200 (87,5%)|171/200 (85,5%)|197/200|
|68M FP32,3pares (v112)|175/200 (87,5%)|174/200 (87%)|168/200 (84%)|197/200|

v112 conserva los10candidatos y el orden de los7no puntuados. El control RRF50
obtiene6ganancias/0pérdidas sobre Ken en estos200casos. Cada brazo fijó pesos
y prefijo antes de ejecutarse. v112 es posterior y fue motivado por el coste de
v110; no es una prueba independiente ni un ajuste a la reserva. Todos los brazos,
incluidos los peores, quedan.

Coste del REPLAY DEL RERANKER SOLAMENTE, sin toda la búsqueda ni sus índices:
17M10pares mediana381ms/p95428ms/RSS315441152bytes;68M10pares2981ms/p953308ms/
RSS720453632bytes;68M3pares962ms/p95991ms/RSS723976192bytes. CPUExecutionProvider,
2hilos intra/1inter, sinTorch/Transformers. No sumar estas medidas para declarar
latencia/RAM completa: cualquier variante adoptada necesita medición integrada.
La prueba de cabeza verifica su ensamblaje NumPy, no paridad del backbone completo.

## Respaldo y verificaciones

Código de controles:11ca6e3. Ensamblaje/validación de contexto:5874192.
44tests enfocados pasan; la eliminación deliberada de la exigencia de llamada
visible causa fallo y fue restaurada. La revisión de código cubrió corrección,
atribución de fuente, límites, caché obsoleta, shadowing y dependencia extranjera.
Las14800pruebas/10xfail preexistentes, mypy336y lockcheck corresponden al checkpoint
anterior e864b57, sin cambios posteriores en src/tests/pyproject/uv.lock.
No se presenta ese suite completo como nueva validación de los prototipos.

El MANIFEST de output/checkpoints/search-engine-2026-10-15-followup guarda
artefactos cerrados y snapshots de productores en gzip, con SHA256 descomprimido.
Modelo binario, secretos y reservas privadas están excluidos. Los paths absolutos
son procedencia de ejecución; esto todavía no es un instalador portable.
Las nuevas200consultas privadas v104 permanecen cerradas. Ningún porcentaje de
esta página es una medición de esa reserva. Sin tags, versión nueva ni release.

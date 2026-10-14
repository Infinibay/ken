# Estado de desarrollo del motor de búsqueda

Implementación experimental en `output/search-engine-2026-10-14/workspace`, rama
`codex/search-engine-top1`. El checkout principal conserva los cambios previos del usuario.
El objetivo aprobado sigue siendo al menos 90% de top‑1 estricto en aceptación.
**Ese objetivo todavía no está demostrado.**

Condición posterior del usuario, con su última aclaración: modelo liviano,
ejecución en CPU y RAM contenida, referencia aproximada de 1 segundo por cada
100 archivos del repositorio para devolver la respuesta completa con índice
preparado. Los 500 ms y el límite fijo de 3–5 s anteriores quedaron reemplazados. Las filas históricas de Qwen con GPU que siguen
son diagnósticos; no son perfiles elegibles bajo esta condición. Se detuvo la
medición pesada en curso, preservando sus respuestas y sus fallos.

## Último control completo y límites

Tras corregir el padding/truncado del tokenizer y respetar primero la escritura
literal de los símbolos, el control completo v15 obtiene **157/400 (39,25%)**
con preferencia de rol; el servicio público con RRF y el perfil Potion explícito
obtiene 138/400 (34,50%). La preferencia de rol continúa en la capa de evaluación,
sin promoverse como default. EN: 107/240; ES: 50/160; implementación: 104/320.
La regresión separada de nombres cualificados únicos vuelve a 48/48 sin encoder.
No se ejecutó la reserva de aceptación ni se alcanzó el 90%.

Se probaron seis embeddings estáticos alternativos sobre las mismas 400 consultas:
ninguno superó al Potion de código en el control común v14. Véase
`STATIC-EMBEDDINGS.md` para calidad, idiomas, cobertura, CPU, RAM y límites del
ensayo. Los pesos mayores no aportaron una mejora que justifique adoptarlos.

El NDCG por archivo sobre nuestras 400 consultas es 0,73923 para el control Ken
v15 y 0,68871 para Semble. Esto no es el benchmark de 1251 consultas de Semble,
ni el criterio de función/evidencia de aceptación; véase `BENCHMARK-METRICS.md`.
El archivo correcto aparece primero en 247/400 consultas de Ken frente a 204/400
de Semble. Las métricas de localización y de evidencia se conservan separadas.

## Comparación controlada en CPU

Las 400 consultas públicas originales, mismos pasajes de 256 tokens léxicos,
propietarios, parsers, roles y evaluación estricta:

| Modelo | Top‑1 estricto | Identidad top‑1 |
|---|---:|---:|
| Estático de Ken | 114/400 (28.50%) | 121/400 |
| Potion code 16M | 137/400 (34.25%) | 145/400 |

Potion aporta 23 aciertos adicionales en esta comparación. No corresponde
atribuirle mejoras de extracción presentes en ambos controles. Sus 100
candidatos contienen el propietario o fragmento correcto en 363/400 consultas;
todas las anclas están presentes en 360/400. Falta el checkpoint de cobertura
del 98% y la precisión sigue muy lejos del 90%. Salidas y recibos en
`output/development/{static,potion}-cpu-256-v5/`.

Controles adicionales sobre las primeras 50 consultas originales:

- E5 small ONNX int8: 19/50 estrictos; cobertura 44/50. Sólo se prepararon esos
  dos repositorios; los 350 casos restantes no cuentan como observados.
- MiniLM multilingüe ONNX int8, 40 entidades y ventanas: 21/50 estrictos.
  p95 4059 ms y pico RSS observado 983 MiB, excluyendo recuperación inicial.
- ColBERT 33M: 13/50 estrictos, frente a 12/50 de Potion en esos mismos pools.
- Expansión por fragmentos literales de la consulta: mantiene 44/50 de cobertura
  E5. Se descartó como cambio de producción.

Ninguno se promovió. La optimización aritmética de CPU sí conservó exactamente
las 400 respuestas y redujo tiempo y memoria: véase `PERFORMANCE.md`.

Una auditoría independiente de referencias propuso 208 alternativas; su segunda
revisión exigió evidencia decisiva dentro de las propias anclas. Sólo 29 cumplen
esa condición, 178 son navegación hacia otra función y una sigue ambigua.
**Ninguna se aplicó**: las consultas, referencias, denominadores y resultados
originales permanecen intactos; la reserva no se abrió.

## Mediciones históricas con GPU

Las mismas primeras 50 consultas públicas de desarrollo, con archivo, propietario
y todas las anclas decisivas visibles, máximo 40 líneas por resultado y 12000
caracteres JSON. Son consultas de Packaging y Day.js; no representan las 400 ni
la reserva independiente.

| Variante experimental | Top‑1 estricto | Identidad top‑1 |
|---|---:|---:|
| Control estático inicial | 9/50 (18%) | 11/50 |
| Recuperación densa Qwen 0.6B inicial | 15/50 (30%) | 20/50 |
| Relevancia conjunta por documento de entidad, 40 candidatos | 28/50 (56%) | 32/50 |
| Relevancia por pasaje, máximo por propietario, 100 candidatos | 38/50 (76%) | 40/50 |
| Mismo orden anterior, selección de ventanas reales | 39/50 (78%) | 40/50 |

Las filas combinan cambios de representación, presupuesto y ordenamiento; no son
una ablación aislada del tamaño del modelo ni del backend. La última fila sí
conserva todos los propietarios y scores anteriores y cambia sólo la exposición
de evidencia y sus límites de propiedad. Resultados crudos en
`output/development/qwen-50/`, recibos y versiones congeladas en `output/frozen/`.

La última variante obtiene EN 23/30, ES 16/20, comportamiento 32/40. Todos siguen
por debajo de los gates aprobados. Errores y respuestas vacías cuentan como fallos.

Auditoría de recuperación parcial: 200/200 propietarios o fragmentos correctos
entre 100 candidatos; todas las anclas están en los pasajes seleccionados en
199/200. Falta completar el checkpoint de 400 consultas.

Regresión independiente de nombres únicos: 48/48, 24 EN y 24 ES, tres casos por
cada uno de 16 repositorios. La primera ejecución falló en expresiones naturales
de definición; la corrección se registra con sus pruebas y se conserva el intento
fallido. Esto no sustituye el gate semántico de aceptación.

El primer ranker lineal fue rechazado por sesgo del muestreo de negativos. Una
segunda revisión independiente produjo 1184 pares incorrectos utilizables; los
equivalentes o inciertos se excluyen del entrenamiento. Su mejor control daba
114/400 frente a 112/400 de RRF con metadatos comparables: no se adoptó por defecto.

## Cambios funcionales

- Pasajes con identidad propietaria, cuerpo ejecutable, rangos y hash de fuente.
- Recuperación léxica por campos y vistas densas separadas de identidad/comportamiento.
- Lookup exacto independiente de embeddings, también para peticiones naturales.
- Perfil serializable con revisión de modelos, backend, precisión y presupuestos.
- Ordenamiento local opcional por evidencia conjunta y ventanas fieles de hasta 40 líneas.
- Un servicio compartido por API, CLI y MCP, con formato de evidencia explícito y
  respuestas legadas conservadas durante la migración.

Preparación explícita: `ken retrieval index --path PROJECT --profile PROFILE.json`.
Consulta CLI: `ken search-symbols QUERY --path PROJECT --response-format evidence --json`.
MCP: `ken_find(query=QUERY, scope="symbols", response_format="evidence")`.
Los modelos del perfil deben estar disponibles localmente; las consultas no descargan pesos.
No se promueve todavía un perfil semántico predeterminado ni una etiqueta de 90%.

## Validación y límites pendientes

La última suite enfocada de recuperación y evaluación pasó 196 pruebas; mypy de
354 módulos pasó sin nuevas supresiones. El ajuste de mayúsculas tiene prueba
RED/GREEN y una mutación que la prueba detecta. Una integración anterior pasó 191
pruebas de recuperación, evaluación, CLI y MCP. También se verificaron dos
llamadas stdio persistentes; falta repetirlo con el futuro perfil final de CPU.
La primera suite completa tuvo 12 fallos de extracción de gramáticas en el
caché de usuario bajo sandbox; el rerun aislado con acceso a ese caché pasó
13/13 sin cambiar código. La suite completa debe repetirse al integrar.

El indexado completo y los ensayos de GPU coexistieron inicialmente: esos tiempos
no son latencia sin competencia. Se registra una pausa temporal del indexador
experimental en `output/development/qwen-float16/resource-events.jsonl` para
serializar los ensayos. Hace falta medir de nuevo frío/caliente, memoria y coste
incremental del perfil final, con dependencias resueltas en un entorno limpio.

La reserva independiente de 300 positivos y 60 negativos permanece sin abrir ni
ejecutar. La certificación requiere congelar fuente, scorer, perfil y modelos;
usar la misma configuración pública en las interfaces reales; pasar todos los
gates sin bajar umbrales; completar revisión y migración antes de promover.

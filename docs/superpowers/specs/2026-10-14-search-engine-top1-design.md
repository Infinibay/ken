# Búsqueda de implementaciones: diseño para un top‑1 mínimo del 90%

Fecha: 2026-10-14. Estado: diseño aprobado por el usuario; implementación y evaluación de desarrollo en curso. Aceptación pendiente, sin promoción de un perfil de 90%.

## Propósito y definición de éxito

Ken debe llevar desde una pregunta sobre código hasta la implementación que la responde en el primer resultado. El usuario confirmó que **deben ser correctos el archivo y la función o el fragmento**. Encontrar solamente el archivo no satisface el objetivo.

El objetivo obligatorio es `strict_top1 >= 0.90` sobre consultas positivas nuevas, con repositorios y etiquetas reservados para aceptación. `strict_top1` exige una alternativa válida de referencia: ruta correcta, identidad propietaria correcta cuando existe, y evidencia visible que incluya el ancla de código que demuestra la coincidencia. No cuentan firmas/docstrings aislados para preguntas que requieren comportamiento ejecutable, proximidad de líneas, un archivo entero devuelto indiscriminadamente, errores ni abstenciones. Una consulta sobre constantes, configuración o código a nivel de módulo puede tener un fragmento sin función; no se inventa un propietario.

La métrica de identidad del primer resultado se informa también por separado de la de evidencia visible. Así se distingue recuperar la función correcta de mostrar el fragmento equivocado dentro de ella. En preguntas que necesitan varios lugares, la referencia declara qué conjunto de anclas constituye una respuesta suficiente; el primer resultado puede incluir varios pasajes de la misma entidad.

El 90% es un criterio de aceptación, **no una mejora ya demostrada ni una garantía para todas las preguntas posibles**. Con 300 positivos implica al menos 270 aciertos. Se publican intervalos Wilson y bootstrap por repositorio; un 90% observado no implica un límite inferior de confianza del 90%. El objetivo no se reduce si la implementación no lo alcanza.

## Qué sabemos y qué falta demostrar

Fuentes de diagnóstico: [benchmark](../../../output/ken-vs-semble-2026-10-14/INFORME.md), [estudio y ablaciones](../../../output/ken-vs-semble-2026-10-14/study/ESTUDIO.md). Ambos conjuntos ya fueron inspeccionados y son exclusivamente desarrollo/regresión.

| Observación | Implicación de diseño | Límite de la evidencia |
|---|---|---|
| `ken_find` de archivos usa stem y primeros ocho nombres; símbolos usa nombre y primera línea de docstring. | Hay que indexar evidencia del comportamiento, conservando la identidad. | No prueba qué segmentación o modelo será mejor. |
| Semble híbrido sin reglas: archivo @5 42/60; completo 53/60. | Recuperación y ordenamiento son problemas diferentes. | No trasladar sus pesos como constantes universales. |
| Mismo pipeline de Semble con nuestro modelo: archivo @5 50/60 frente a 53/60. | Primero corregir representación y recuperación; evaluar el modelo con el resto fijo. | En función/rango @5 la caída fue mayor: 33 a 26. |
| Añadir hasta 4000 caracteres de fuente al embedding actual empeoró archivo @5 de 37 a 26/60. | Separar vistas de identidad y comportamiento. | No equivale a probar pasajes bien delimitados. |
| Retirar diversidad por archivo mejoró función/rango @5 de 33 a 42/60. | Ordenar entidades y agrupar sus pasajes antes de diversificar. | No demuestra que toda diversidad sea perjudicial. |
| FTS falló con `?` en 50/50 preguntas de comportamiento del benchmark. | Reparar la frontera de consulta antes de atribuir fallos al ranking. | Es un defecto reproducido de esa superficie, no de todos los canales. |

Las cifras anteriores usan métricas antiguas, algunas permisivas con rangos; **no son el baseline del nuevo `strict_top1`**. Hay que recalcularlo con las nuevas etiquetas y el mismo presupuesto de evidencia.

## Alternativas consideradas

1. **Retocar el motor actual:** reparar FTS y ajustar boosts. Sirve como baseline y corrección inmediata, pero deja sin representar cuerpos, literales y propietarios; no hay fundamento para esperar 90%.
2. **Recuperación por entidades y evidencia, con ranking evaluable:** incorporar pasajes estructurales, varias vistas de recuperación y un único ordenamiento explicable. Es la opción elegida: aprovecha la identidad, relaciones e incrementalidad de Ken y permite diagnosticar dónde se pierde cada respuesta.
3. **Un agente o LLM que investigue cada consulta:** puede resolver tareas complejas, pero cambia la naturaleza y el coste de la herramienta. No es la ruta predeterminada. Un reranker local acotado es un experimento dentro de la segunda opción, no una autorización para introducir llamadas remotas o una investigación ilimitada por consulta.

No se copia el chunker de 750 caracteres, las penalizaciones de rutas ni la pérdida de identidad de Semble. Se toma su lección útil: buscar también en el contenido y combinar evidencias complementarias.

## Diseño desde el uso

Contrato interno propuesto, todavía no implementado:

```python
response = search(
    conn, root,
    SearchRequest(
        query="¿Dónde se retira Authorization al redirigir a otro host?",
        target="symbol", purpose="implementation", limit=5,
        max_chars=12000, explain=False,
    ),
)
```

El primer `CodeMatch` identifica la función propietaria e incluye la evidencia de la retirada del header. La posición se decide antes de formatear; el presentador no puede promover otra coincidencia porque su snippet resulta más corto. `target="file"` agrupa entidades coincidentes de cada archivo, sin sustituirlas por sus primeros ocho símbolos. El filtro literal sigue siendo una operación literal y no se convierte silenciosamente en búsqueda semántica.

### Conceptos y responsabilidades

| Concepto | Responsabilidad y dueño |
|---|---|
| Instantánea de fuente | El indexador existente determina bytes, hash, versión y vigencia de cada archivo. |
| Entidad de código | `ci_symbols` y los parsers conservan identidad, propietario y rango; un fragmento de módulo puede no tener símbolo. |
| Pasaje | Una región de evidencia vinculada a una entidad y una instantánea; no es una definición alternativa del programa. |
| Recuperación | Produce candidatos por identidad, léxico y semántica, con la procedencia de cada señal. |
| Ordenamiento | Compara entidades candidatas según la pregunta; agrupa evidencia repetida y expone una traza reproducible. |
| Presentación | Selecciona evidencia fiel dentro del presupuesto y declara rangos visibles, truncamiento y vigencia. |
| Ranking de contexto | Añade memoria, actividad y relaciones cuando se busca contexto; consume la recuperación común. |

`src/ken/retrieval/` alojará el núcleo compartido. `src/ken/search.py`, MCP y CLI serán adaptadores de contratos existentes. No habrá un motor paralelo para cada superficie. La recuperación heurística de `responsibility/retrieval.py` se integrará mediante un adaptador que conserve su evaluación de responsabilidades y su incertidumbre.

## Información que hay que recolectar mejor

La unidad de indexación sigue siendo el archivo; la unidad de respuesta es la entidad con sus pasajes.

- **Identidad:** ruta, lenguaje, tipo, nombre completo/corto, propietario, firma y rango. No depender de que un nombre entre primero en los 512 vecinos semánticos.
- **Comportamiento:** docstring completo, comentarios vinculados, sentencias del cuerpo, literales, errores, variables de entorno y rutas. Conservar original y campos separados; no repetir artificialmente la ruta dentro de cada campo.
- **Relaciones:** referencias, imports y llamadas cuando el análisis existente puede justificarlas. Separar hechos observados de resolución incierta. Los vecinos del grafo son contexto potencial, no respuestas correctas por definición.
- **Papel del código:** definición, uso, test, fixture, ejemplo, generado, compatibilidad o reexportación. Conservar procedencia y señales de incertidumbre; no excluir tests cuando la pregunta pide tests.
- **Vigencia:** hash de bytes, versión de extracción/tokenización, revisión del modelo y formato de los vectores. Un cambio de cualquiera invalida sólo los artefactos afectados.

Los pasajes se delimitan por sentencias/nodos dentro del propietario más estrecho. Firma y contexto del propietario son campos auxiliares: no se hacen pasar por líneas contiguas del snippet. Se ensayan presupuestos de 128/256/384 tokens del modelo, manteniendo el mismo extractor; se registran divisiones forzadas y cobertura de anclas. Las funciones largas tienen varios pasajes; una función corta conserva su cuerpo completo. El fallback por líneas declara propiedad desconocida si no puede probarla. Closures, decoradores, overloads, métodos homónimos y código fuera de funciones reciben pruebas explícitas.

Se reutilizan el ciclo transaccional por archivo, hash, watcher, cola y almacenamiento vectorial existentes. Los cambios de esquema añaden tablas de pasajes/postings y su versión; no alteran silenciosamente la interpretación de `ci_symbols.docstring`. No se reconstruye un FTS de todo el repositorio durante cada consulta. Reemplazo, borrado y cambio de configuración deben publicar fuente, postings y vectores de manera consistente.

Hay una limitación que no se puede dar por resuelta: `src/ken/vectors.py` documenta que sus lectores actuales pueden observar un slot liberado y reutilizado entre el barrido y la resolución SQL. Para los nuevos espacios de recuperación se exige una instantánea de filas/slots activos y escritura en slots nuevos, sin reciclar los retirados mientras su generación tenga lectores. La compactación rota una generación y conserva la anterior hasta que terminen sus lectores. Se reutiliza el mecanismo de escribir/flush antes del commit, pero no se hereda silenciosamente esa anomalía de lectura. La tarea 4c mide el coste y prueba la carrera con barreras deterministas; no promete resolver a la vez todos los lectores legados.

## Recuperación y matemática

### Candidatos antes de preferencias

La unión inicial contiene lookup exacto independiente de SQL, léxico por campos, vectores de identidad y vectores de comportamiento. Los identificadores completos se conservan además de sus componentes `snake_case`/`camelCase`. El análisis de consulta preserva puntuación significativa, negación y cadenas exactas; inglés y español usan el mismo contrato. No se traducen nombres de APIs.

Baseline reproducible: hasta 100 candidatos por canal léxico/denso, unión por entidad, preselección de 100 mediante RRF y reserva para coincidencias exactas. Los presupuestos son configuración versionada y se barren en desarrollo; no dependen del repositorio. Nombres ambiguos mantienen todas sus definiciones hasta el presupuesto declarado y reportan truncamiento; un nombre calificado único sí puede recibir precedencia determinista. `purpose` explícito prevalece sobre una inferencia; si es `auto`, una inferencia dudosa aporta una característica, no un filtro irreversible.

El techo de cualquier ordenador es la cobertura de sus candidatos:

`P(top1 correcto) <= P(respuesta presente en candidatos)`.

El checkpoint de recuperación es `candidate_recall@100 >= 0.98` en desarrollo. Si no se cumple, se trabaja sobre corpus, extracción, vistas y unión; añadir boosts o un cross-encoder no puede recuperar una respuesta ausente. La traza mide pérdidas antes y después de agrupar/preseleccionar.

### Léxico por campos

Comparar BM25 sobre pasajes con BM25F sobre identidad, firma, documentación, cuerpo y ruta. Para el segundo:

```text
tf*(t,d) = Σ_f w_f · tf(t,d,f) / (1-b_f+b_f·len(d,f)/avglen(f))
idf(t) = log(1 + (N-df(t)+0.5)/(df(t)+0.5))
L(q,d) = Σ_t idf(t) · (k1+1)·tf*(t,d)/(k1+tf*(t,d))
```

`N` y `df` corresponden a documentos de pasaje de la misma generación. La frecuencia documental y las longitudes se actualizan también al borrar. El baseline usa `k1=1.2`, pesos de campos `1`, `b=0.75` para cuerpo/docs y `b=0` para identidad/firma/ruta. Son valores de partida, no óptimos proclamados: el conjunto de desarrollo decide si otra parametrización generaliza. Campos vacíos no dividen por cero; duplicar un pasaje o una ruta no constituye evidencia independiente.

### Ordenar por evidencia, no por suma de escalas incompatibles

RRF es un baseline de unión; no conserva toda la magnitud de evidencia. Compararlo con un ranker lineal regularizado entrenado por pares dentro de cada consulta. Características: coincidencia de identidad y su especificidad, cobertura de términos/raros, scores léxicos por campos, cosenos de cada vista, correspondencia entre acción y código, propósito/papel, soporte de relaciones y cantidad de evidencia distinta. Scores ausentes tienen indicador propio.

```text
score(q,e) = w · x(q,e)
loss = Σ_q mean_(positivo,negativo)[softplus(-w·(x_pos-x_neg))] + λ||w||²
```

Los negativos difíciles son otras funciones del mismo archivo, usos en lugar de definiciones, tests cuando se pidió implementación, reexports y respuestas semánticamente cercanas. No usar sólo negativos aleatorios fáciles. Normalización y pesos se ajustan únicamente con repositorios de entrenamiento; validación deja repositorios y familias de consulta fuera. Entrenamiento balanceado por consulta evita que una pregunta con muchos negativos domine.

El esquema inicial de features se limita a hechos calculables: exactitud de nombre completo/corto; cobertura de identificadores enteros; cobertura de términos de consulta sin stopwords; cobertura ponderada por IDF; scores BM25 de identidad, firma, documentación, cuerpo y ruta; cosenos de identidad y máximo de comportamiento; número saturado de pasajes de sentencias distintas con evidencia léxica; propósito/papel como categorías e interacciones; y soporte estructural resuelto. Cada score opcional tiene máscara de ausencia. No se añade una feature vaga de “correspondencia con la acción” sin un extractor y una prueba propios. Nuevas features requieren su ficha y ablación. La vista densa de identidad usa nombres, propietario, firma y ruta; la de comportamiento usa contexto del propietario, documentación y pasaje, respetando el límite real del tokenizer.

No sumar coseno, BM25 y actividad como si tuvieran unidades comparables, ni tratarlos como probabilidades independientes. El máximo entre pasajes y una cobertura saturada de evidencia distinta se comparan con suma/media; repetir diez pasajes de una función no debe premiar diez veces el mismo hecho. La diversidad se aplica después de ordenar entidades, según finalidad y sin cambiar la primera respuesta para exhibir archivos distintos.

La relevancia semántica y las preferencias históricas se inspeccionan por separado. La recencia de una lectura no demuestra que esa función responda la consulta. Calibrar una probabilidad de acierto requeriría datos reservados adicionales; hasta entonces `score` tiene semántica de ordenamiento y `confidence` se omite.

### Modelos y segunda etapa

Comparar con extractor y candidatos controlados: modelo estático actual; Potion como control del estudio; y `intfloat/multilingual-e5-small` como hipótesis multilingüe, usando sus prefijos de query/passage y revisión fijada. El último no está validado para nuestro código. Ninguno se adopta por reputación o por un resultado de archivo @5. Medir top‑1 estricto, recuperación, EN/ES, indexación, RAM, disco y arranque.

Si la respuesta está presente pero el ordenamiento sigue fallando, evaluar un cross-encoder local sobre 20/40 candidatos. Antes de medir se registra un único modelo multilingüe compatible con ejecución local, su revisión, licencia, longitud y backend; no se ensayan modelos contra aceptación. Debe mejorar top‑1 en validación por repositorio y ser parte del mismo perfil predeterminado que se certifica. Si el ranker simple alcanza el objetivo, no se añade esa dependencia. El diseño de dos etapas tiene [soporte en la documentación de Sentence Transformers](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html); no es evidencia de que alcance nuestro 90%.

## Retorno y compatibilidad

`CodeMatch` contiene ruta, lenguaje, identidad opcional (`kind`, `qualname`, `owner`, rango completo), score con versión de ranker y uno o varios fragmentos **realmente visibles** con sus rangos, contenido y hash de fuente. `truncated`, `stale` y `omitted_count` son explícitos. `explain=True` añade señales ejecutadas y procedencia, sin una explicación inventada por un LLM.

Presupuesto por defecto de aceptación: 10 resultados, máximo total de 12000 caracteres, hasta 40 líneas visibles por resultado, sin enviar archivos completos como sustituto de localizar evidencia. En el resultado primero se preserva una ventana alrededor de la evidencia seleccionada y se incluye la identidad como metadata. Si no cabe evidencia suficiente, se declara el recorte y la métrica visible falla; no se excluye la consulta del denominador. El usuario puede pedir más mediante lectura normal.

La evidencia se hidrata desde fuente vigente comprobando hash. Una edición concurrente provoca un reintento acotado y luego un estado de fuente modificada, nunca líneas antiguas citadas como actuales. Sin parser todavía se puede devolver un pasaje correcto con identidad desconocida.

Los contratos actuales de `search_files`, `search_symbols`, CLI y MCP se conservan mediante adaptadores/versionado. Un nuevo formato explícito de evidencia convive con la forma anterior durante la migración. No reutilizar el campo legado `score`, documentado como coseno, para un score aprendido. El cambio de recuperación predeterminado requiere el gate final; antes puede activarse para evaluación con configuración explícita y trazable.

## Evaluación que evita fabricar el 90%

1. Mantener las 60 preguntas conocidas y sus etiquetas originales como regresión. Añadir anclas de evidencia en una versión nueva sin sobrescribir los datos históricos.
2. Crear al menos 400 positivos de desarrollo en repositorios adicionales; agrupar paráfrasis, traducciones y implementaciones relacionadas para no repartirlas entre entrenamiento y validación. Validar dejando repositorios fuera.
3. Reservar **300 positivos, 12 repositorios nuevos, 25 consultas por repositorio**, con Python, JS/TS, Go, Rust y Java representados por al menos dos repositorios cada uno. Registrar commits, tamaños, cobertura real del parser y exclusiones antes de ejecutar. No descartar un proyecto porque el buscador falla.
4. Distribución reservada: 210 preguntas de comportamiento/implementación, 45 de identidad y 45 de usos/tests/documentación; 180 en inglés y 120 en español. Cruces estratificados y selección de comportamientos declarados antes de ver resultados. No obtener las preguntas copiando docstrings o nombres objetivo al prompt de búsqueda.
5. Referencias con alternativas legítimas, propietario y anclas, revisión independiente del autor del ranking y comprobación de bytes/rangos antes de congelar. El ejecutor que ajusta el motor no recibe las consultas/etiquetas reservadas. Si la curación no puede ser independiente, se informa y no se llama ciega a la evaluación.
6. Congelar dataset, scorer, perfil, fuente y modelos por hash. Evaluar baseline y candidato final una vez para la decisión. Una falla inspeccionada convierte ese conjunto en diagnóstico; el siguiente intento requiere una nueva reserva. El registro conserva todos los intentos y costes.

En aceptación, el motor recibe sólo lo disponible en uso normal: consulta, proyecto y configuración pública congelada. Se usa `purpose="auto"`; las etiquetas de propósito/idioma/propietario y `answerable` son para estratificar/puntuar, no pistas para el motor. Un experimento con propósito explícito se informa aparte y no sustituye el gate predeterminado. Anclas, archivo objetivo y alternativas nunca entran en el request, el entrenamiento reservado ni la selección del snippet.

Gates: `strict_top1 >= 0.90` global, macro por repositorio, en comportamiento, en inglés y en español. Con 25 consultas por repositorio, global y macro coinciden; se conservan ambas para detectar cambios de ponderación posteriores, no se presentan como dos validaciones independientes. No confundir este requisito con 90% en cada repositorio individual; cada uno informa también su resultado y fallos. La regresión de identificadores únicos calificados exige 100% en sus casos deterministas. Un conjunto separado de al menos 60 consultas no respondibles mide falsas afirmaciones y abstención; no se mezcla con positivos para subir el porcentaje. Una abstención positiva vale cero.

Informar además identidad @1, evidencia @1, recall de candidatos, MRR, @5/@10, clasificación de fallos y diferencias pareadas; nada reemplaza el gate top‑1. Performance: p50/p95 frío y caliente por API y MCP real, trabajo de indexación/reindexación, RAM, disco, tamaño de salida y lecturas adicionales en tareas auditadas. Inicialmente no se inventa un límite de latencia del usuario: se presenta la frontera calidad/coste y se descartan complejidades dominadas.

## Auditoría y limpieza con evidencia

Cada señal o canal recibe una ficha: qué hecho observa, qué hipótesis representa, coste, correlación con otros, consumidores, ablación con candidatos fijos y efecto fuera del repositorio usado para ajustar. Una mejora en recall puede explicar una mejora de ranking: no atribuirla a la fusión si cambió el conjunto de candidatos.

| Área actual | Decisión inicial, sujeta a pruebas |
|---|---|
| Hash, watcher, cola, nombres calificados, relaciones y KQL2 | Conservar; tienen contratos y valor fuera de búsqueda. |
| Metadatos breves de identidad | Conservar como vista especializada; dejar de usarlos como único contenido de comportamiento. |
| Lookup de nombre limitado al pool semántico | Reemplazar por recuperación exacta independiente. |
| FTS sincronizado recorriendo archivos en consulta | Pasar la actualización al ciclo de indexación, sin perder frescura declarada. |
| Outlines de primeros ocho miembros | Mantener en lectura de outline; sustituir en respuestas de búsqueda por miembros coincidentes. |
| Fusiones y umbrales históricos | Mantener como controles al principio; retirar del camino activo los redundantes o dominados, con pruebas de consumidores. |
| Penalizaciones de tests/docs e historia de uso | Condicionar a finalidad; medir aportación, no aplicarlas como verdad de relevancia. |
| Recuperación repetida en búsqueda/ranker/responsibility | Unificar la producción de candidatos; preservar los contratos y decisiones propios de cada consumidor. |

No se elimina un subsistema por no ayudar a una métrica de repositorios sin historia. Las lecturas/exposiciones futuras no se convierten automáticamente en etiquetas positivas: registrar posición, alternativas expuestas, selección explícita y resultado permite estudiar ese sesgo después.

## Entrega y riesgos

Entregas verificables: evaluador estricto; recuperación con pasajes; ranking/retorno integrado; limpieza y aceptación final. Cada una mantiene el sistema utilizable y tiene rollback por perfil/esquema. El plan adjunto concreta tareas y comandos.

Riesgos principales: datos insuficientes para aprender; multilingüismo; referencias incompletas; cambios de propietario; crecimiento del índice; rangos y fuente concurrente; compatibilidad de consumidores. Si falla un gate, se conserva el objetivo y se publica dónde falta información o capacidad. No se activa por defecto un motor con una etiqueta de “90%” sin el recibo de aceptación.

El repositorio tiene modificaciones anteriores del usuario, incluso en ranker, CLI, MCP y watcher. Antes de implementar hay que fijar una instantánea reproducible de ese estado y aislar el trabajo sin resetear, guardar en stash ni mezclar esos cambios en commits propios. Partir sólo del HEAD actual perdería parte del baseline investigado.

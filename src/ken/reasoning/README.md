# Razonamiento persistente: primera integración con Ken

Implementado el 17-09-2026. Núcleo sin LLM, Stanza, red ni ejecución de comandos.
El agente interpreta una vez; Ken conserva premisas, pruebas y trabajo pendiente.
La interfaz MCP y `ken tools` comparten estas tres herramientas:

- `ken_reason_record`: inserta/reemplaza/retira un conjunto de premisas con fuente.
- `ken_reason`: consulta el conocimiento formalizado del contexto y devuelve
  apoyos, oposición, pruebas, fuentes y condiciones pendientes.
- `ken_calculate`: aritmética racional exacta y acotada, sin `eval`.

Un proceso MCP que ya estaba abierto debe reiniciarse para publicar herramientas
nuevas. No hace falta reiniciar el daemon de índices ni modificar su base.
Se usa `.ken/reasoning.sqlite`, independiente de `ken.db` y del grafo estructural.

## Contrato del agente

```python
ken_reason_record(
    source="documento:revision:pasaje",
    facts=[
        {"predicate":"type", "subject":"robot:atlas", "object":"robot"},
        {"predicate":"subclass", "subject":"robot", "object":"machine"},
        {"predicate":"all/use", "subject":"machine", "object":"battery"},
    ],
    evidence="Premisas explícitas de una demo; no afirmaciones sobre robots reales.",
    context="demo:robots",
)
ken_reason(
    question="¿Qué utiliza Atlas?",
    goal={"predicate":"use", "subject":"robot:atlas", "object":"?answer"},
    context="demo:robots",
)
```

El ejemplo devuelve `battery` con una prueba. No hay un detector general de
sinónimos en este núcleo: el agente debe suministrar IDs de sentido/referente.
`question` conserva la formulación original, `goal` explicita su interpretación.
Sin `goal`, Ken recupera notas candidatas mediante `ken_recall` y pide formalizar:
no transforma sus textos en premisas ni deduce a partir de similitud semántica.

Las relaciones del AST, referencias de código y notas existentes de Ken no se
mezclan automáticamente con hechos del mundo. El agente puede consultarlas con
las herramientas existentes y registrar interpretaciones con su evidencia.
La microgramática de `experiments/text-graph-engine` es un adaptador experimental
opcional; no se distribuye como una dependencia obligatoria de Ken.

Una regla tiene `body: [atom, ...]` y `head: atom`; uno a tres antecedentes.
Las variables sólo pueden ocupar sujeto/objeto y la cabeza debe estar ligada por
el cuerpo. Los predicados son explícitos. Hay reglas incorporadas para pertenencia,
clasificación y universales `all/<predicado>`, como en el prototipo anterior.
No hay contrapositiva, negación por fallo ni transitividad de verbos arbitrarios.

## Qué se conserva y cuándo se revisa

- Inserciones con el mismo conjunto de reglas propagan nuevos hechos sobre el
  cierre anterior. Duplicar exactamente una fuente es idempotente.
- Cambiar/retirar una fuente invalida conservadoramente **ese contexto entero**.
  Todavía no hay invalidación mínima por componente. Así se eliminan ciclos sin
  raíces y se reconstruyen apoyos alternativos correctamente.
- Cambiar el conjunto de reglas, incluidas las incorporadas que requiere un nuevo
  predicado/ámbito, reconstruye el checkpoint.
- Las fuentes y versiones anteriores permanecen en el registro de eventos.
  La vigencia externa depende de que el agente notifique cambios: no hay watcher
  automático de archivos ni caducidad temporal de observaciones.
- Presente/pasado/futuro o un ID de intervalo son ámbitos opacos distintos; no se
  implementa todavía cálculo de intervalos ni unificación temporal.
- La respuesta se calcula sobre los hechos actuales, incluidas nuevas oposiciones
  y nuevas coincidencias WH. No hay caché de respuestas vacías que oculte inserciones.

## Estocasticidad y reanudación

Se guarda la frontera, estado del generador y cursores de joins. Cada candidato
de join consume trabajo, por lo que un join se puede interrumpir y continuar.
El muestreo favorece predicados alcanzables hacia atrás desde ambas polaridades
de la meta. Cada décimo trabajo sigue FIFO; la selección usa una ventana acotada.
No hay aprendizaje de pesos aún. Semilla y ranking no son probabilidades de verdad.

El checkpoint es transaccional y versionado. Una consulta cerrada reutiliza el
cierre con cero nuevas operaciones de inferencia, incluso después de reiniciar.
Todavía se cargan, validan y serializan estructuras: cero inferencia no significa
cero latencia ni acceso constante a una base de tamaño arbitrario.

Límites: 10.000 hechos, 50.000 trabajos en cola, 50.000 soportes, 2.000 reglas del
usuario; presupuesto por llamada hasta 10.000 unidades. El corte por presupuesto
es reanudable; alcanzar una capacidad no se declara completo. Explicaciones hasta
50 niveles y 300 visitas por prueba; un soporte puede existir aunque no quepa en
la explicación. No se probó todavía una sesión de ocho horas ni millones de hechos.

## Hipótesis y herramientas

`assumptions=[atom, ...]` acepta hasta ocho supuestos y usa una copia del estado
base cuando es compatible. El escenario es aditivo: suponer P no retira NO P.
Los supuestos figuran como tales en la prueba y no se insertan en la base. Hay
hasta 16 checkpoints de escenarios por contexto.

Si la consulta concreta queda desconocida, devuelve condiciones faltantes de
reglas que podrían apoyarla. Son candidatos de un paso, **no** una explicación
causal, una probabilidad ni hipótesis exhaustivas. El agente puede obtener datos
o ensayarlos como supuestos para verificar sus consecuencias. Inducción/analogía
y abducción profunda siguen disponibles en el prototipo, pero aún no se han
migrado a este núcleo persistente.

`ken_calculate("0.1 + 0.2")` devuelve exactamente `3/10`. Admite números,
paréntesis, `+ - * / **`; no admite nombres, funciones, unidades, álgebra simbólica
ni I/O. No incorpora automáticamente el resultado al grafo. Para un cálculo con
datos del grafo, el agente conserva las fuentes de los operandos al registrarlo.

No hay invocación autónoma de herramientas. Las observaciones faltantes se
devuelven al agente, que elige cómo obtenerlas y vuelve a registrar el resultado.
Un timeout es una observación sobre ese intento, no evidencia de imposibilidad.

## Validación y Wikipedia

`tests/test_reasoning_memory.py` cubre reinicio, deltas, retiro, ciclos, cambios de
reglas, múltiples apoyos, contextos, escenarios, consultas vacías/WH, atomicidad,
concurrencia, cálculo acotado y equivalencia contra cierre ingenuo en seis semillas.
Las ejecuciones interrumpidas en joins deben producir los mismos resultados y
trabajo total que la ejecución continua.

Experimento reproducible desde `experiments/text-graph-engine/prototype`:

```sh
.venv/bin/python evaluate_persistent_wikipedia.py
```

`--persist-demo` publica además el caso formalizado en el contexto
`demo:wikipedia:earth` de este proyecto. El script verifica los hashes originales
y los spans de evidencia. Mantiene separadas la extracción automática y las
anotaciones del agente. Resultados en `reports/persistent-wikipedia.json`.

En seis fragmentos / 25 oraciones, el compilador estricto aceptó **0** oraciones.
De doce preguntas, la demo respondió cuatro definiciones mediante extracción,
cinco consultas fueron no interpretadas y tres quedaron sin evidencia. El núcleo
persistente no convierte esas definiciones opacas en premisas lógicas.

Una formalización revisada de cuatro pasajes de Earth/Tierra sí permitió una
pregunta que requiere cuatro deducciones: vincular el núcleo externo con una
magnetosfera capaz de desviar la mayoría de los vientos solares destructivos, y
unir ese planeta con la estrella que orbita. Resultado: Sun/Sol. El agente aportó
la identidad Tierra/Earth, Sol/Sun y la descomposición relacional de la pregunta.
Esto valida inferencia sobre premisas, **no** comprensión automática de Wikipedia.

La repetición hizo cero trabajo nuevo; retirar la premisa de capacidad dejó la
respuesta desconocida. «La mayoría» nunca se convirtió en «todos». Un supuesto
adicional de órbita alrededor de Sirius produjo dos respuestas condicionales,
sin borrar la órbita original ni modificar el mundo base.

Otra medición con 600 premisas: 3.000 unidades de trabajo inicial, cero en cada
una de 19 repeticiones y 10 para añadir dos premisas de otra clase. Los contadores
de este núcleo incluyen trabajos de join y no son directamente comparables con
las expansiones del motor anterior. No se midió aún ahorro de tokens de un LLM.

La siguiente prioridad es un adaptador de interpretación evaluado con anotaciones
de referencia, seguido de invalidación más selectiva y recuperación de subgrafos.
Mejorar el planificador no recuperará hechos que el parser nunca representó.

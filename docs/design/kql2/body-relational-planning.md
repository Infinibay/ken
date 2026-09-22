# Planificación relacional de BODY

Estado: propuesta de generalización, 15 de septiembre de 2026. No describe una
optimización general ya implementada.

## Ejemplo y significado

```kql2
method $algorithm {
  body {
    call $slot { receiver: $strategy; dispatch: possible; };
  }
}
```

La anidación expresa pertenencia y comportamiento, no obliga al ejecutor a
enumerar primero todos los métodos. Si el receptor o el destino están ligados,
sus índices pueden ser más selectivos que el conjunto de métodos.

Un plan lógico puede seleccionar llamadas por receptor y destino, unir cada
ocurrencia con su método propietario y verificar ejecución. Otro plan equivalente
empieza por métodos filtrados y busca sus llamadas. Pueden materializarse como
joins, semijoins, subconsultas correlacionadas o lotes de IDs. No es necesario
generar código Python ni elegir SQL como única representación física.

## Implementación actual del catálogo

Los selectores fuente se compilan a operadores relacionales sobre FactIndex.
Executor reordena joins dentro de fronteras válidas y adelanta restricciones
independientes. Al llegar a `source_body`, invoca SourceExecutor.match por fila
candidata; BodyEngine recorre el CFG y comprueba la subsecuencia. Hay memoización
de BODY por patrón y bindings de entrada, y de consultas nombradas por bindings.

Existe una poda específica de candidatos para asignaciones de parámetros a
bindings. Es sólo una condición necesaria: BODY sigue comprobando ejecución y
efectos. Se desactiva ante cobertura desconocida o hechos de valor incompletos.
No equivale a bajar cualquier BODY a joins.

## Generalización pendiente

1. Extraer restricciones necesarias de cada cláusula positiva: propietario,
   ocurrencia de llamada, receptor, destino acreditado, argumentos y operandos.
2. Conservar roles de ocurrencia internos, incluso si el usuario sólo captura el
   destino. Dos llamadas al mismo método no son una misma ejecución.
3. Estimar cardinalidades con índices; elegir dirección del join y evitar listas
   gigantes de IDs o consultas independientes por cada ID.
4. Pasar las ocurrencias candidatas al verificador residual. Para una llamada
   aislada, omitir el recorrido sólo cuando los hechos acrediten exactamente la
   misma semántica de ejecución que BODY.
5. Para secuencias, preservar orden, compatibilidad de ramas, procedencia por
   ocurrencia y ausencia de escrituras durante los intervalos restringidos.
6. Mantener fronteras de alternativas, negación, cuantificación y dependencias.
   No adelantar un filtro que dependa de un valor que todavía debe capturarse.

La ausencia de receptor, resolución o CFG puede producir unknown en el
verificador actual. Un inner join que descarte esos casos cambiaría los resultados:
la poda debe conservarlos como candidatos inciertos. `dispatch: possible` tampoco
es equivalente a una coincidencia de nombre ni garantiza invocación en runtime.

## Validación necesaria

Comparar plan optimizado y de referencia en bindings, multiplicidad, evidencia y
unknown. Incluir llamadas tras return, ramas incompatibles, destinos ambiguos,
receptores ausentes, sobrescrituras, llamadas repetidas, closures y grafos
parciales. Medir tiempo, filas, memoria y estados con ruido creciente; mantener
los presupuestos existentes. Un descenso de estados por sí solo no demuestra
mejora del tiempo de ejecución.

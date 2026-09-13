# Cobra: Composite nominal y un testigo incorrecto de Command

Se analizaron 19 archivos Go de https://github.com/spf13/cobra, commit
`adbc8813901bba65827259daa8e22ff94ec1f30e`, sin ejecutar el código.
El [reporte](cobra-recursive-composite.json) registra hashes y resultados de las
23 consultas GoF. Todas completaron; no hubo diagnósticos de parsing.

**Composite: omisión corregida.** `Command` declara `commands []*Command`
(command.go:221), sin exigir una interfaz separada. El frontend ahora vincula el
elemento nominal del slice e identifica las llamadas sobre el segundo binding
de range. La consulta exige que la operación del padre y la del hijo tengan el
mismo nombre; no acepta cualquier llamada de un bucle ni una colección de otro tipo.

Los [testigos ampliados](cobra-composite-witnesses.json) permiten revisar:

| Método | Llamada al hijo | Evaluación |
|---|---|---|
| SetGlobalNormalizationFunc, línea 382 | command.SetGlobalNormalizationFunc, 388 | Propaga configuración recursivamente a los hijos |
| checkCommandGroups, 1205 | sub.checkCommandGroups, 1212 | Comprueba grupos a lo largo del árbol |
| IsAdditionalHelpTopicCommand, 1628 | sub.IsAdditionalHelpTopicCommand, 1636 | Agrega una propiedad booleana de los subárboles |

Se devuelve un Composite (`Command`), no tres tipos diferentes. La firma prueba
la estructura nominal y las llamadas, no ausencia de ciclos, terminación ni
elección de sobrecarga en todos los lenguajes.

**Historial de Command; corregido en IR 1.25.0.** La [auditoría actual](command-actions.md) elimina el testigo de getter y conserva la variante stored-closure. La observación siguiente corresponde al estado anterior: La consulta también
devuelve `Command`, pero al inspeccionar su evidencia selecciona
`getUsageTemplateFunc` (464), que delega al padre (470) para encontrar una función
de plantilla. El invocador es una closure de UsageFunc (451–453). Esto no prueba
una operación Command: describe búsqueda y devolución de una plantilla. El hecho
de que el tipo se llame Command y tenga otros mecanismos de ejecución no valida
ese testigo. La firma de delegación sin argumentos necesita mejor discriminación
de rol y ciclo de invocación; filtrar simplemente nombres no resolvería la causa.
La variante para Run/RunE almacenados como callbacks sigue pendiente.

# Valores retornados en la vista KenQL

Estado: implementado en IR 1.27.0. La [guía operativa](../../structural-ir.md)
incluye un ejemplo ejecutable y los límites de disponibilidad.

La vista anterior convierte `return local` en una lectura del binding aun cuando
el pase de retornos conoce la construcción exacta que lo alcanza. Esto impide
unir `RETURNS_VALUE` con `RESULT` sin seguir flujos históricos imprecisos y afecta
Prototype, Builder y consultas propias.

La proyección usa los hechos `RETURN_ORIGIN` de callables con
`RETURN_FLOW_STATUS=supported`. Una construcción se normaliza al mismo nodo VALUE
que su `RESULT`; parámetros y otros bindings conservan una lectura LOADED_FROM.
El hecho RETURNS_VALUE retiene modalidad, análisis, evidencia y el ID de la
operación de retorno. Las alternativas may no se convierten en must.

Los retornos explícitos inalcanzables en un cuerpo soportado no aportan
RETURNS_VALUE; tampoco los valores reemplazados antes del retorno. Se conserva
RETURNS en la vista fuente, y las asignaciones/argumentos mantienen su semántica.

Los callables sin ese análisis, incluidos lenguajes y controles no soportados,
conservan la proyección sintáctica previa con `basis=syntax`. No se promete
corregir sus resúmenes ni inferir ausencia de retornos. Los consumidores que
necesiten el pase de flujo pueden exigir `basis=flow` o RETURN_FLOW_STATUS.

Los tests contrastan retornos directos/locales, aliases antes de sobrescribir,
alternativas de ramas, retornos inalcanzables, parámetros, opacidad y round-trip
de la vista serializada. Los tests de Prototype y Builder deben demostrar que
las queries existentes se benefician sin codificar esas categorías en el motor.
Una copia y un sucesor del mismo tipo siguen pudiendo compartir estructura:
el falso positivo FilePart.rollOver requiere criterios adicionales de patrón.

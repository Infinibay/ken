# Terminación normal de regiones y Retry por fallthrough

Estado: implementado en IR 1.46.0; diseño escrito antes del código.

Los ejemplos Java originales Retry y RetryExponentialBackoff de iluwatar retornan
el intento desde un try dentro de un do/while. El catch registra el fallo, puede
relanzarlo y espera antes de alcanzar su final; no usa continue. La consulta
anterior perdía ambos; la nueva variante los recupera. Tenacity es un caso diferente: almacena el resultado y
coordina acciones entre métodos; esta extensión no basta para reconocerlo.

Se incorporan hechos públicos generales, sin lógica especial de Retry en el
matcher:

El probe de iluwatar encontró además que do_statement permanece NATIVE aunque
el CFG ya reconoce su control posterior al cuerpo. Ahora se normaliza como LOOP en
el frontend para que ENCLOSING_LOOP y CONTINUE_TARGET conserven su contexto.
Esto exige regresión de otras consultas GoF que usan bucles, no sólo Retry.

- NORMAL_COMPLETION: operación de región → possible, abrupt o unsupported,
  con basis=statement-normal/1. Describe una ruta normal estructural que puede
  alcanzar el final, no alcanzabilidad, terminación runtime ni ausencia de throws
  ocultos en expresiones. Secuencias requieren continuación; if/else une brazos.
  return/throw/break/continue cortan la secuencia. Las condiciones no se evalúan.
- LOOP_BODY_TAIL: bucle → última sentencia directa del cuerpo, ignorando comentarios.
  La posición es anterior al update/test/exhaustion del bucle: no garantiza otra
  iteración ni salta esos controles.
- HANDLER_FALLTHROUGH: handler → try al que pertenece, sólo cuando hay una ruta
  normal soportada del cuerpo y el try no tiene finally, recursos ni else.
  Mantiene evidencia del handler y reutiliza NORMAL_COMPLETION; no afirma qué
  excepción captura ni que el intento lance esa excepción.

El pase admite bloques, sentencias simples, if/else/elif y try/catch anidado sin
finally/recursos/else en Python, JS, TS, Java, C# y C++. Construcciones sin modelo,
bucles internos, switch/match, etiquetas, goto, suspensión y errores producen
unsupported. Los cuerpos de funciones/clases anidadas no se recorren como código
del handler. Memoización por operación y límite de profundidad evitan repetir
árboles por cada consulta. El CFG de excepciones sigue siendo partial:
estos hechos no se deben presentar como un CFG completo.

La regla resilience.exception-retry tiene dos variantes con los mismos roles
públicos. explicit-continue conserva el contrato previo. handler-fallthrough
exige el mismo try del retorno de llamada y del handler, final directo del cuerpo
del bucle y HANDLER_FALLTHROUGH. El rol retry apunta al continue en la primera
variante y al handler en la segunda, como testigo de la continuación.

Se probaron seis lenguajes, handlers vacíos/con llamadas/con ramas y try anidado,
retornos y throws incondicionales, salidas en todos los brazos, sentencias después
del try, distintos loops/handlers, cuerpos anidados, recursos/finally y parsing
incompleto. Se escanearon los mismos bytes externos antes/después, conservando
commits, hashes, resultados, presupuestos y tiempos separados de parseo/consulta.
No se inferirán idempotencia, estabilidad de argumentos, backoff ni seguridad
de reintentos a partir de esta estructura.

Referencia de terminación normal frente a abrupta:
[JLS, bloques y sentencias](https://docs.oracle.com/javase/specs/jls/se22/html/jls-14.html#jls-14.1).
El pase de Ken es deliberadamente parcial; no implementa el algoritmo de
alcanzabilidad del compilador Java ni generaliza todas sus reglas a otros lenguajes.

# Command: acciones, consultas y objetos retenidos — IR 1.25.0

La firma anterior aceptaba cualquier delegación sin argumentos con un invocador
tipado. Eso clasificaba PreparedRequest.copy como Command y aportaba evidencia
incorrecta de búsqueda de plantillas en Cobra. Se conservaron los escaneos
[Requests antes](command-requests-before.json) y [Cobra antes](command-cobra-before.json).

`command#command-object` ahora exige una llamada al receptor cuyo resultado se
descarta como sentencia, o el retorno de una llamada resuelta que escribe estado
del receptor. Se usa `RETURN_ORIGIN`. La nueva variante `retained-object` admite
cálculos puros: una clase invocadora distinta almacena el objeto recibido y lo
ejecuta desde otro método. `stored-closure` conserva su consulta anterior.

## Evidencia revisada

- **Requests:** [verificación actual](command-requests-verified.json), cero Command.
  PreparedRequest.copy consume copias de campos para construir otro objeto;
  desaparece el falso positivo, sin filtrar nombres copy ni PreparedRequest.
  El falso negativo de Prototype por copia mediante asignaciones sigue pendiente.
- **Cobra:** [verificación por variante](command-cobra-verified.json), Command
  conserva su match por `stored-closure`. Las variantes de objeto devuelven cero.
  getUsageTemplateFunc devuelve una plantilla y ya no sirve como evidencia de
  ejecución. Eliminar ese testigo incorrecto no elimina otro match de clase:
  la clase Command sigue siendo un positivo válido.

Los reportes fijan commits, fuentes y hashes del motor. Se revisó código fuente;
no se ejecutaron los proyectos. Las consultas terminaron completas y sin unknowns.
Command nombrada tomó 2,140 ms en Requests y 2,499 ms en Cobra, con 1.347 y 1.423
estados respectivamente. Son mediciones individuales de consulta, no percentiles
ni tiempos de construcción del grafo.

## Regresiones y límites

69 tests nuevos cubren descarte en ocho lenguajes, llamadas anidadas, paréntesis,
retorno, asignación, await y tails Rust. Command se prueba en Python/Java/TS/C#:
acciones con resultados, getters puros, escrituras locales, copias y cálculos
puros retenidos, con nombres ajenos a execute/Command. La suite pasa 2.322 tests.
Los 276 casos GoF canónicos y los 24 de closures almacenadas siguen pasando.

La [regresión externa](ir125-corpus-regression.json) conserva las mismas fuentes,
53 presencias esperadas en 281 ejemplos, los mismos matches y ninguna consulta
incompleta. No se perdieron positivos etiquetados en ese corpus; eso no demuestra
recall universal. Los fixtures no se ejecutan ni se verifican con sus compiladores.

`DISCARDS_RESULT` representa uso sintáctico, no efectos ni ejecución. Getters con
efectos y llamadas puras descartadas pueden compartir la firma de acción; una
query almacenada puede compartir la firma de objeto retenido. El análisis no
prueba orden temporal ni estabilidad de campos. Efectos de I/O no modelados,
implementaciones externas, MRO compleja y comandos con otras firmas de argumentos
necesitan variantes/evidencia adicionales. No se exige que todo Command modifique
estado o devuelva void.

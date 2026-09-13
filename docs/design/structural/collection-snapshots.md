# Copias de colecciones y Observer

Implementado en IR 1.22.0: una copia superficial conserva la procedencia
de los elementos, pero no la identidad de la colección ni su estado posterior.
Vaciar el registro después de copiarlo no vacía la copia. Esto permite expresar
notificaciones sobre snapshots sin unir todas las asignaciones históricas.

- `COLLECTION_SNAPSHOT_OF`: llamada de copia → colección fuente, con el modelo
  utilizado. Modelos iniciales: Python `list(xs)`/`tuple(xs)` y JS/TS
  `Array.from(xs)` sin mapper. Se rechazan nombres declarados/importados en el
  archivo que puedan ocultar esos builtins. El modelo asume builtins estándar;
  monkey-patching externo y mutaciones concurrentes no están resueltos.
- `ITERATION_SNAPSHOT`: bucle → llamada de copia que suministra su iterable.
  Una llamada directa es suficiente. Un alias local requiere una única escritura
  simple, anterior al uso, en la misma secuencia de sentencias o una secuencia
  contenedora. No se siguen campos, asignaciones condicionales que no dominan el
  uso, ciclos ni aliases sobrescritos. También se excluyen aliases usados como
  receptores, pasados a llamadas, modificados por índices o usados como bindings
  de otros bucles; la exclusión de escape/mutación se propaga por los aliases.
  Esto es un subconjunto conservador de
  procedencia, no un nuevo análisis general de reaching definitions.
- `ITERATION_INVOKES_VALUE`: bucle → llamada sobre el elemento, o invocación del
  elemento como callback. Ambos deben pertenecer al mismo callable. Se excluyen
  bindings escritos explícitamente y bindings reutilizados por otros bucles.
  La presencia sintáctica no prueba que la llamada llegue a ejecutarse.

La variante `observer#snapshot-registry` exige registro y notificación sobre el
mismo campo. El listener registrado debe ser un parámetro de un método o de un
callback que ese método pasa explícitamente como argumento a una llamada. Un
callback meramente declarado no basta. Pasarlo como argumento tampoco prueba
que la API receptora lo ejecute: el resultado sigue siendo una firma estructural.

Validación: positivos y mutaciones negativas en Python, JavaScript y TypeScript;
[RxJS Subject](../../structural-validation/multilanguage/observer-snapshots.md)
como evidencia externa con fuente y revisión fijadas.
Los tests comprueban copias de otra colección, mapper que transforma elementos,
shadowing de builtins, alias sobrescrito o definido en otra rama, callback sin
consumidor, y rebinding del elemento. No se clasifican todos los misses como FN.

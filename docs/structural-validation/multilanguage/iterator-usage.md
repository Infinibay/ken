# Operación pública de Iterator

`iterator.iterate_over` está declarada en `[[operations]]` en el TOML de Iterator.
Se registra como query nombrada, con los mismos joins, budgets, exports y evidencia
que las demás consultas. No se agrega a la unión GoF, por lo que encontrar un for
no convierte su contenedor en una implementación detectada de Iterator.

Los 24 tests de `test_pattern_operations.py` cubren ocho lenguajes, dos bucles que
no deben cruzar sus roles, composición, serialización en el mismo TOML, validación
y colisiones de nombres antes de escribir. También distinguen los índices/keys
de los valores: Go de un solo slot y JS/TS for-in no satisfacen esta variante;
Python `_` sí es un binding y C++ auto& conserva su variable.

En el [Subject de RxJS](iterator-usage-rxjs.json), la operación encuentra tres
bucles: next, error y complete, en las líneas 42, 54 y 65 del commit fijado por
el reporte. La medición individual fue 17 estados, 9 filas examinadas y 0,138 ms
de consulta; excluye construcción del grafo. El reporte incluye hashes de fuente
y motor. En esa medición IR 1.21 la evidencia de uso todavía no corregía Observer:
faltaba unir el registro, snapshots y aliases. La extensión IR 1.22 corrige ese
caso; ver [Observer sobre snapshots](observer-snapshots.md).

Límites: fuentes y bindings son entidades sintácticas; no se prueba ejecución,
tipo de los elementos ni ausencia de rebinding. La resolución completa del
shadowing en bloques sigue pendiente. Destructuring, cursores explícitos y APIs
de callbacks requieren variantes adicionales. `%… do … %end`, map y filter siguen
como propuestas, descritas en la documentación de operaciones públicas.

La [regresión GoF](ir121-corpus-regression.json) compara las mismas fuentes del
corpus anterior. Tener una operación adicional no debe alterar por sí mismo los
matches de los detectores del catálogo.

# iluwatar caching: Optional y Read-Through

Actualización IR 1.33.0: el nuevo detector reconoce readThrough y
readThroughWithWriteBackPolicy, con testigos de hit/retorno y miss/carga/escritura/retorno.
Se preservan los matches Optional anteriores. Ver [auditoría actual](../multilanguage/read-through-cache.md).
El texto siguiente conserva los hallazgos y límites del informe original.

Actualización con IR 1.15.0: el [escaneo posterior](iluwatar-optional-after.json)
detecta `AppManager.findAside` (línea 142), con cacheStore, userId, lookup (143),
load (146) y write (147). La revisión de ese flujo confirma un positivo real.
La consulta termina completa; la nueva variante usa lambdas con ámbito propio y
el modelo de `java.util.Optional` con import explícito no sombreado. No se han
resuelto todos los flujos de caché descritos abajo. El reporte anterior se conserva
como evidencia del fallo original.

Se analizaron 14 archivos de `caching/src/main/java/` de
https://github.com/iluwatar/java-design-patterns en el commit
`41625d8d354cdf6b6f10a82e29c2392b3efd5d20`.
El [reporte](iluwatar-caching.json) conserva hashes y resultados. Cero diagnósticos
de parsing; la consulta de cache-aside completó la búsqueda sin matches.

La revisión de `AppManager.findAside`, líneas 142–151, confirma una omisión real:
`Optional.ofNullable(cacheStore.get(userId)).or(...)` ejecuta una lambda de carga
cuando falta el valor. Esa lambda llama a `dbManager.readFromDb(userId)`, escribe
el resultado mediante `ifPresent(account -> cacheStore.set(userId, account))`, y
la cadena finaliza con `orElse(null)`. `saveAside`, líneas 131–134, actualiza la
base e invalida la entrada; el detector actual no verifica ese camino de escritura.

Causas originales: la variante implementada exigía un if con comparación nula explícita,
asignaciones a la misma variable y retorno de ésta. Además, el frontend no
declaraba `lambda_expression` Java como callable con parámetros y ámbito propios.
Preservar la sintaxis como NATIVE no permite afirmar el flujo de Optional.
La solución requiere ownership de lambdas y un modelo de Optional con identidad
resuelta, que correlacione las claves y el valor pasado al consumidor `ifPresent`.
Añadir únicamente nombres or/ifPresent al query aceptaría métodos ajenos a Optional.

`CacheStore.readThrough`, líneas 74–84, usa otro flujo no cubierto: comprueba
contains, retorna en hit y carga/escribe después del if. Su clasificación como
read-through del proveedor o cache-aside de la aplicación requiere conservar la
frontera entre cliente y caché, aunque ambos compartan una carga bajo demanda.

No se ejecutó el código externo. La comparación antes/después valida el caso
findAside; readThrough y los otros flujos señalados siguen pendientes.

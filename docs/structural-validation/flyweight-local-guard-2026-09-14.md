# Flyweight: chequeo de miss mediante una variable local

Corrección del 14 de septiembre de 2026. Archivo:
`src/ken/structural/patterns/flyweight.toml`, variante `explicit-interning`.
El motor y el IR no requieren cambios para esta corrección.

## Causa y comportamiento corregido

El patrón exigía que el operando de NULL_TEST tuviera directamente CONTAINER e
INDEX. En `result = pool.get(key); if (result == null) ...`, el operando es el
binding result; el acceso al contenedor pertenece a la llamada get. Esto descartaba
el ejemplo Java canónico de `test_map_api_shape.py`.

La nueva alternativa conserva las asignaciones como eventos: lookup y construcción
escriben el mismo binding comprobado, y son sus únicas dos escrituras explícitas.
Exige STORAGE_WRITE_STATUS supported y STORAGE_WRITE_COUNT 2. Se usa este inventario
porque distingue escrituras a bindings de escrituras a elementos; el inventario
antiguo por callable marcaba las inserciones por subscript como unmodeled-target.

Los caminos CFG ordenan lookup → guard y miss → construcción → inserción. La
construcción y la inserción están dentro del guard. Se mantienen las correlaciones
anteriores de pool, clave, construcción retenida y retorno. Se aceptan chequeos
nulos, undefined y truthiness con ambas polaridades nativas. Los accesos directos,
membership y la variante entry-api mantienen sus caminos separados.

Una reasignación antes del guard, entre construcción/inserción o después de insertar
introduce otra escritura y se rechaza. Sólo perseguir ASSIGNED_FROM habría aceptado
esas formas, porque esa relación agrega asignaciones de toda la función.

## Pruebas

`tests/structural/test_flyweight_local_guard.py` añade **44 casos**:

* 12 positivos: Python/Java/TypeScript × con/sin ruido × guard normal/invertido.
* 24 negativos: ocho mutaciones por lenguaje — reset antes del guard, reset y
  restauración, construcción antes del guard, lookup posterior al guard,
  sobrescritura antes/después de insertar, otra clave y otro pool.
* 2 positivos con truthiness Python/TypeScript y 3 con nombres distintos.
* 3 positivos de rendimiento: 40 pares de instrucciones independientes antes del
  lookup y 10 llamadas intermedias; presupuesto de 100.000 estados y 3 segundos.

```sh
.venv/bin/pytest tests/structural -k 'flyweight or map_api_shape' -q -o addopts=''
```

**169 pasan, 3 xfail previos, 10.420 deseleccionados, 10,51 s.** Incluye el test
Java que antes fallaba y los casos de catálogo/matriz de Flyweight. Los tres xfail
son el contrato adicional de estabilidad del estado intrínseco al usar el objeto;
esta corrección no implementa ese análisis ni convierte esos xfail en aprobados.
No se volvió a ejecutar la suite completa de los demás patrones.

Además pasan **313 pruebas** de contratos del catálogo, queries documentadas y
reutilización de compilación (`test_catalog_ir_contracts.py`,
`test_documented_kenql_queries.py`, `test_query_compilation_reuse.py`), en 2,60 s.

## Coste de la consulta

La primera versión de la corrección enumeraba todas las operaciones candidatas a
guard antes de filtrarlas y agotaba 100.000 estados en dos casos noise-20. La
versión final filtra primero mediante las relaciones del chequeo y comprueba
pertenencia al callable después. No cambia el presupuesto del motor.

| Caso existente | Estados | Filas examinadas | Tiempo de muestra | Resultado |
|---|---:|---:|---:|---|
| Java / noise-20 | 1.316 | 614 | 2,85 ms | Completo, 1 match |
| TypeScript / noise-20 | 1.202 | 557 | 2,30 ms | Completo, 1 match |

Muestras individuales de ejecución sobre grafo preparado, sin contar parseo ni
linking; no son un benchmark general de KQL2 ni una garantía de latencia.

## Límites explícitos

La consulta conserva el máximo de **32 saltos CFG** por recorrido y los límites de
wrappers sintácticos (3) y ancestros del guard (8). Un intervalo más largo puede
seguir dando un falso negativo; no se amplió el límite del lenguaje para ocultarlo.
Los conteos son ocurrencias fuente: escrituras redundantes o muertas pueden excluir
implementaciones válidas. No se prueban factibilidad de todos los caminos, efectos
ocultos por llamadas/alias, identidad temporal del pool, inmutabilidad ni seguridad
concurrente. Las detecciones de APIs por nombre conservan sus límites anteriores.

# Cache-Aside: miss nulo con asignaciones y retornos correlacionados

Diseño previo, implementado y validado en IR 1.34.0. La variante null-miss anterior
reunía ASSIGNED_FROM de toda la callable. Eso aceptaba escribir el valor viejo
antes de cargar, cambiar la clave entre get y set, o sobrescribir el valor antes
del retorno. La consulta ahora conserva la identidad de las asignaciones y sus
recorridos por el CFG. Ver [auditoría reproducible](../../structural-validation/multilanguage/cache-aside-flow.md).

## Inventario del IR

BINDING_WRITE_COUNT relaciona callable → binding con atributo entero count,
basis=explicit-writes y analysis=binding-writes/1. Cuenta eventos explícitos de
asignación del cuerpo, no ejecuciones ni inicialización implícita de parámetros
o parámetros-propiedad. Incluye ramas mutuamente excluyentes y código posterior
a return. El alcance por callable evita sumar escrituras de otros métodos a
un campo compartido.

Se expone count=0 para bindings usados sin reasignación. BINDING_WRITE_STATUS
indica supported/unsupported. Un ámbito no soportado no emite un conteo exacto:
la ausencia de arista **no significa cero**. El inventario admite Python,
JavaScript, TypeScript, Java y C#, bajo las restricciones de CFG estructurado;
rechaza bucles, escrituras indirectas/no modeladas, callables interiores y
operaciones conocidas que manipulan el ámbito dinámico.

```kenql
query bindings_written_twice {
  require $owner BINDING_WRITE_COUNT $binding [count: 2];
  emit $owner, $binding;
}
```

Esta primitiva también sirve para consultas sobre configuración sobrescrita o
bindings inicializados una sola vez. Por sí sola no clasifica un bug: dos escrituras
pueden ser deliberadas y una escritura puede ejecutarse en muchos caminos.
No es SSA ni prueba de pureza, inmutabilidad o ausencia de mutaciones por aliases.
La versión IR forma parte de las claves de caché de unidades/proyectos, de modo
que un grafo 1.33 no se reutiliza como 1.34.

## Recorrido consultado

null-miss exige exactamente dos escrituras al binding comprobado: lookup y load.
ASSIGNMENT_TARGET/ASSIGNMENT_VALUE identifican ambas operaciones. NULL_TEST conecta
la condición con ese binding y BRANCH_TRUE identifica el brazo de miss. La clave
y el receptor de caché requieren UNREASSIGNED_BINDING dentro de la callable.

CFG_NEXT ordena lookup → condición → load → write → return; el camino hit debe
alcanzar un retorno con origen lookup y el miss uno con origen load. Los caminos
CFG tienen hasta 16 saltos; los wrappers sintácticos hasta tres, y la pertenencia
al brazo de miss hasta seis. Son límites explícitos de esta consulta, no del IR.
No se garantiza equivalencia con cuerpos arbitrariamente largos o anidados.

RETURN_ORIGIN puede tener modality=may cuando ambos caminos convergen en un mismo
return. La query admite explícitamente may o must sin convertir los orígenes
posibles en obligatorios en todos los caminos. Las ramas any separadas son
necesarias para esa admisión; una lista de valores en el filtro no tiene la misma
semántica de evidencia. La existencia de caminos compatibles no prueba ejecución
ni factibilidad de todas las condiciones.

```kenql
query inspect_cache_aside {
  match "architecture.cache-aside#null-miss"(
    unit:$function, cache:$cache, key:$key, lookup:$lookup, load:$load, write:$write
  );
  emit $function,$cache,$key,$lookup,$load,$write;
}
```

Los roles públicos y la composición con architecture.cache-aside se conservan.
La variante sigue declarada en un TOML; no introduce un detector privado en Python.

## Formas fuente comprobadas

Estos fragmentos se analizan estáticamente; las APIs Cache/Store son ilustrativas,
no dependencias importadas ni programas compilados. Los tests incluyen renombrado,
retorno mediante alias, retorno separado en miss y una tercera opción TTL.

```python
def fetch(cache, source, key):
    value = cache.get(key)
    if value is None:
        value = source.load(key)
        cache.set(key, value)
    return value
```

```javascript
function fetch(cache, source, key) {
  let value = cache.get(key);
  if (value === null) {
    value = source.load(key);
    cache.set(key, value);
  }
  return value;
}
```

```typescript
function fetch(cache: Cache, source: Store, key: string) {
  let value = cache.get(key);
  if (value === null) {
    value = source.load(key);
    cache.set(key, value);
  }
  return value;
}
```

```java
class A {
  Object fetch(Cache cache, Store source, String key) {
    Object value = cache.get(key);
    if (value == null) {
      value = source.load(key);
      cache.set(key, value);
    }
    return value;
  }
}
```

```csharp
class A {
  object Fetch(Cache cache, Store source, string key) {
    var value = cache.Get(key);
    if (value == null) {
      value = source.load(key);
      cache.Set(key, value);
    }
    return value;
  }
}
```

Mover set antes de load se rechaza por orden CFG. Reasignar key entre get y set
se rechaza por inventario. Sobrescribir value después de cargar añade una tercera
escritura y se rechaza. Retornar otro símbolo no aporta el origen requerido.
Un alias local del retorno sí conserva sus orígenes; no se requiere que el nombre
final escrito sea value.

## Límites y costes deliberados

Los argumentos de clave/valor deben ser posicionales no expandidos. Se permiten
opciones adicionales, como set(key,value,300); reconocer ese argumento no demuestra
que sea TTL ni que se aplique correctamente. get/Get y set/put/Set filtran por forma
de API, sin probar contratos externos o persistencia del loader.

El conteo exacto de dos escrituras favorece rechazar los contraejemplos anteriores,
pero puede excluir implementaciones válidas con escrituras redundantes o muertas.
Tampoco cubre sentinels, indexación, serialización, APIs awaited, expansión de
argumentos, aliasing general, efectos ocultos, invalidación ni seguridad concurrente.
La comparación con null puede depender de operadores sobrecargados.

Java Optional conserva su variante separada y su evidencia anterior de asignaciones
sin orden temporal general. Sus closures tienen inventarios por ámbitos diferentes;
las garantías nuevas de null-miss **no se aplican** a esa variante. Los escaneos
externos de Optional y Read-Through son pruebas de regresión, no nuevos TP de
null-miss. Las métricas de la matriz propia no estiman precisión/recall global.

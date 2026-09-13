# Read-Through Cache con retorno temprano en hit

Implementado en **IR 1.33.0**, después del diseño y las pruebas de las primitivas.
Ver la [guía IR](../../structural-ir.md) y la
[auditoría externa](../../structural-validation/multilanguage/read-through-cache.md).

## Caso de referencia

CacheStore.readThrough de iluwatar/java-design-patterns comprueba contains,
retorna get en hit y, por el camino falso, carga desde DbManager, escribe en
el mismo cache y retorna el valor cargado. CacheStore crea su propio LruCache
en initCapacity. Esto es distinto del Optional de AppManager.findAside, que
usa una caché externa y ya tiene su propia variante Cache-Aside.

La regla nueva es `architecture.read-through-cache`, definida en
[un TOML separado](../../../src/ken/structural/modern_patterns/read-through-cache.toml).
Su operación pública `read_fill` describe el recorrido sin afirmar ownership.
La query canónica añade un campo de la clase que recibe una construcción
contenida en un método de esa clase. Es evidencia local de construcción, no
prueba de inicialización obligatoria, exclusividad o identidad runtime.

## Fuente de ejemplo y uso

Ejemplo propio; las APIs se tratan como formas de llamadas, no se ejecutan:

```python
class Memo:
    pass

class Provider:
    def __init__(self):
        self.cache = Memo()

    def read(self, source, key):
        if self.cache.contains(key):
            return self.cache.get(key)
        value = source.load(key)
        self.cache.set(key, value)
        return value
```

Memo es un placeholder del almacenamiento en este fragmento de análisis. La
misma forma se prueba con clases, new y retornos explícitos en JavaScript,
TypeScript, Java y C#; los fixtures no son una implementación de una biblioteca.

```kenql
query providers {
  match "architecture.read-through-cache"(
    unit: $provider, read: $read, cache: $cache, key: $key
  );
  emit $provider, $read, $cache, $key;
}
```

La operación pública permite reutilizar el recorrido con una caché recibida,
sin etiquetarla como almacenamiento creado por el proveedor:

```kenql
query retrievals {
  match "architecture.read-through-cache.read_fill"(
    read: $read, cache: $cache, key: $key, presence: $presence,
    lookup: $lookup, source: $source, load: $load, write: $write,
    hit_return: $hit_return, miss_return: $miss_return
  );
  emit $read, $cache, $key, $source, $lookup, $load, $write;
}
```

Los roles se pueden ligar al resultado de otra consulta. No hay un motor especial
para esta clasificación: son joins, paths y operaciones nombradas públicas.

## Predicados simples

`TRUTH_TEST` relaciona un if con su operando fuente. `when=true` describe la
prueba directa; `when=false`, su negación por not/!. Se admiten paréntesis y
negaciones sucesivas. Llamadas, accesos a miembros e identificadores son operandos
admitidos; comparaciones, conjunciones y disyunciones no se aplanan a uno de sus
operandos. Se conserva `basis=condition-syntax`.

El frontend también expone los brazos mediante BRANCH_TRUE y BRANCH_FALSE.
TRUTH_TEST no ejecuta el predicado ni resuelve operadores sobrecargados, truthiness
especial o identidad de APIs. La variante read_fill usa presencia afirmativa y
retorno temprano en el brazo verdadero; un miss negado con cuerpo de carga
requiere otra variante aunque TRUTH_TEST preserve su polaridad.

## Inventario positivo de escrituras

La query evita interpretar negación de mundo abierto como estabilidad de bindings.
El pase `binding-writes/1` expone:

| Relación | Contrato |
|---|---|
| `UNREASSIGNED_BINDING` callable → binding | El binding usado no aparece como destino de asignación explícita en el inventario soportado del método. |
| `UNIQUE_BINDING_WRITE` operación → destino | Existe exactamente un evento sintáctico de escritura a ese binding dentro de la callable. No significa ejecución única o incondicional. |
| `BINDING_WRITE_STATUS` callable → estado | supported/unsupported, razón y versión del pase. No hay hechos derivados si el grafo tiene diagnósticos. |

Se admiten Python/JS/TS/Java/C#. El pase requiere CFG estructurado y rechaza
loops, funciones anidadas, operaciones de ámbito dinámico conocidas, updates,
asignaciones compuestas y destinos no modelados. Una asignación múltiple que
oculta un parámetro no acredita estabilidad. Los miembros identificados por
MEMBER_OF siguen admitidos aunque su entidad sea VALUE.

El conteo recorre todo el cuerpo, incluidas ramas y código después de un retorno;
por eso un binding puede quedar excluido por una escritura que no se ejecutaría.
La identidad de operación mantiene el alcance: dos métodos que escriben el mismo
campo no comparten un evento UNIQUE_BINDING_WRITE. Ninguno de estos hechos prueba
pureza, ausencia de alias, mutación del objeto recibido o efectos de llamadas.

## Recorrido y correlaciones exigidos

read_fill requiere CFG_STATUS=structured, RETURN_FLOW_STATUS=supported e inventario
de escrituras soportado. Correlaciona la misma clave y el mismo receptor de caché
entre presencia, lectura y escritura. Ambos bindings deben estar sin reasignación
explícita en el método. La carga usa un receptor diferente de la caché; la igualdad
o diferencia de identidades fuente no es un análisis completo de aliases.

El hit retorna el origen de la llamada lookup dentro de su brazo. El camino falso
alcanza una asignación única del loader, luego una escritura de esa variable y un
retorno cuyo RETURN_ORIGIN es la carga. Una llamada cargadora o escritura después
de un retorno no satisface el camino. El control de orígenes impide devolver una
variable que luego se haya reemplazado y llamarla resultado de la carga.

Contains/containsKey/has/Contains/ContainsKey y get/Get reciben exactamente un
argumento escrito posicional; put/set/Set, dos. El loader recibe la clave como
primer argumento posicional y puede tener otros argumentos. Spreads no son claves
escalares. La forma de los nombres no certifica el contrato de un cache real.

Los caminos CFG tienen límites explícitos de dieciséis saltos. Los enlaces al
statement desde la operación permiten hasta tres niveles; el brazo del hit,
ocho. Se buscan caminos estructurales existentes, no todos los caminos factibles.
Una rama intermedia puede admitir escritura sólo en ciertos casos; la query no
prueba que todo miss rellene la caché.

## Contraejemplos y límites

Las pruebas excluyen caché/clave diferentes, valor escrito equivocado, carga desde
el mismo receptor de caché, rebindings antes/después, sobrescrituras del valor,
hit sin return, escritura anterior a la carga, llamadas adicionales en APIs de
presencia/escritura y argumentos expandidos. La caché recibida desde fuera puede
satisfacer read_fill pero no la condición de construcción local de la regla.

CacheStore.readThroughWithWriteBackPolicy aporta otro recorrido read/fill. La
query no demuestra su protocolo de escritura diferida, evicción o vaciado.
Tampoco prueba TTL, invalidación, atomicidad, single-flight, exclusión mutua ni
que contains y get observen el mismo estado bajo concurrencia. Async, serialización,
indexadores y sentinels necesitan otros modelos. El catálogo conserva esas
limitaciones sin convertir un resultado estructural en una garantía runtime.

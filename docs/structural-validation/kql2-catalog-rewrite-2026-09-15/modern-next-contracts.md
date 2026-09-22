# Tres siguientes contratos modernos de BODY

Lectura y propuesta, 15 de septiembre de 2026. No modifica consultas, tests ni
motor durante la ejecución de la suite global. Los ejemplos siguientes son
**contratos objetivo completos**, no una afirmación de que todo su vocabulario ya
compile. La base es `docs/design/kql2/examples.md`: selectores fuente, valores,
expresiones, BODY y fragmentos. No se propone encapsular un detector en una función
opaca ni cambiar los nombres de relaciones internas.

Se revisaron Dispatch Table, Cache Aside, Read Through Cache, Batch Work Queue,
Unit of Work y Exception Retry. Las tres prioridades siguientes comparten
primitivas reutilizables y permiten retirar los bloques internos más voluminosos.
Retry se debe abordar después: necesita finally y reanudación de excepciones,
no únicamente reconocer un `while` con un `try`.

## 1. Dispatch Table: registrar, seleccionar y ejecutar el valor seleccionado

**Algoritmo en palabras:** una operación instala un callable bajo una clave de un
registro; otra selecciona mediante una solicitud un valor de ese registro y lo
invoca. La petición no necesita tener la misma identidad que el parámetro de
registro: pertenecen a invocaciones distintas. No se afirma que toda clave usada
haya sido registrada en runtime. La elección del callable debe depender de la
lectura efectiva, no de una asignación histórica ni de un objeto con nombre igual.

```kql2
language "kql/2";
module proposed.dispatch_table;
import ken.core;

pattern Registry(out TypeDecl $unit, out Field $table,
                 out Callable $register, out Callable $dispatch) {
  class $unit {
    field $table {}
    method $register {
      param $key { reassigned: false; }
      param $handler { reassigned: false; }
      body {
        read($table)[read($key)] = read($handler);
        gap until end {
          forbid write(element(read($table), read($key)));
        }
      }
    }
    method $dispatch {
      param $requested { reassigned: false; }
      body {
        let $selected = read($table)[read($requested)];
        call $selected {};
      }
    }
  }
  where $key != $handler and $register != $dispatch;
}
query results {
  use Registry(unit: $unit, table: $table,
               register: $register, dispatch: $dispatch);
  select $unit, $table, $register, $dispatch;
}
```

El intervalo de escritura en registro protege **esa entrada**, no prohíbe escribir
otras claves. Para un candidato estructural menos fuerte puede omitirse la garantía
de retención final y declararse explícitamente; no se debe heredar una afirmación
fuerte de la query anterior si la nueva no la demuestra.

**Primitivas mínimas:** `let` sobre expresión indexada; LHS indexado; invocación de
un Value producido; origen del valor en cada lectura; intervalo hasta salida sobre
un lugar indexado, con unknown ante alias/overload sin modelo. La clave debe ser
Value de la ocurrencia, no nombre de variable. El patrón de operación reutilizable
`IndexedLookup` ya está definido en los ejemplos del lenguaje.

**Variantes:** Python `dict`, JS objeto/Map, TS Map, Go map, Java Map, C# Dictionary,
Rust HashMap y C++ map usan el mismo contrato con modelos nominales para APIs y
operadores. No normalizar `get` de cualquier objeto a lookup. La variante adaptada
inserta explícitamente `let $adapted = call $adapter { argument $selected ...; }`
y `call $adapted {}`; además debe demostrar que el adaptador entrega un callable
que usa la entrada, no cualquier objeto nuevo pasado a una llamada.

**Positivo mínimo Python:**

```python
def register(self, key, handler):
    self.routes[key] = handler

def dispatch(self, key, request):
    selected = self.routes[key]
    log(request)
    return selected(request)
```

**Contrastes:** `selected = fallback` antes de invocar (negativo); invocar `other`
tras leer `selected` (negativo); registrar en `routes` pero leer `backup` (negativo);
alias `chosen = selected` (positivo); convertir clave de solicitud mediante función
acreditada (variante positiva independiente); dos métodos con parámetros ambos
llamados `key` no acreditan que sean la misma solicitud histórica.

## 2. Cache Aside y Read Through: bifurcación que devuelve el origen correcto

**Algoritmo en palabras:** consultar por clave; en hit entregar el resultado; sólo
en miss consultar proveedor con esa clave, poblar cache con el resultado y
entregarlo. Un `get` seguido de `put` no acredita este algoritmo. Los caminos hit
y miss se verifican separadamente sobre la misma condición y la misma consulta.

Ejemplo objetivo para la forma con retornos explícitos en ambas ramas:

```kql2
language "kql/2";
module proposed.cache_aside;
import ken.core;

pattern ReadOrFill(out TypeDecl $unit, out Callable $read) {
  class $unit {
    field $cache {}
    field $provider {}
    method $read {
      param $key { reassigned: false; }
      call $lookup { name: /^(get|Get)$/; }
      call $load {}
      call $write { name: /^(put|set|Set)$/; }
      body {
        let $cached = call $lookup { receiver: $cache; argument $key at 0; };
        if ($cached == null) {
          let $loaded = call $load { receiver: $provider; argument $key at 0; };
          call $write {
            receiver: $cache;
            argument $key at 0;
            argument $loaded at 1;
          };
          return $loaded;
        } else {
          return $cached;
        }
      }
    }
  }
  where $cache != $provider;
}
query results { use ReadOrFill(unit: $unit, read: $read); select $unit, $read; }
```

La selección por nombre de llamadas hace de este fragmento un **candidato de API**,
no un contrato de caché confirmado. Una biblioteca de modelos acreditados debe
restringir lookup/write y su semántica de miss; el BODY sigue mostrando algoritmo,
clave, valores, receptor y bifurcación. La carga puede ser callable inyectado en
vez de método de provider: alternativa visible, no requerimiento universal de dos
campos. Read Through añade propiedad/encapsulación del almacenamiento y proveedor
bajo la abstracción; crear una colección en cualquier método no prueba ownership.

**Primitivas mínimas:** permitir Value capturado en condición; correlacionar
lectura del local de cache con ese valor actual; exits de ambas ramas sin
confundir el retorno común con retorno dentro de una rama; preservación del lugar
cache/key durante la operación. La forma habitual que modifica `value` en miss y
hace un único `return value` después del if necesita join de valores por camino.
No imponer dos sentencias return como requisito del patrón.

**Prueba transversal esencial:** el mismo algoritmo expresado como dos retornos,
un retorno común, retorno temprano de hit, y `Optional.or` debe conservar
identidad de valor. Optional requiere callback condicional y origen de retorno de
la closure; no puede simularse mediante una llamada incondicional al proveedor.

**Positivo mínimo Python:**

```python
def fetch(self, key):
    value = self.cache.get(key)
    if value is None:
        value = self.provider.load(key)
        log(key)
        self.cache[key] = value
    return value
```

**Contrastes:** polaridad invertida; carga antes del test (si se promete carga sólo
en miss); escribir con otra clave; escribir una constante tras cargar; retornar
`fallback` aunque la carga fue correcta; sobrescribir `value` en una rama
intermedia. Todos son negativos del contrato fuerte. `cache.get(key) or load(key)`
no equivale a null-miss si cero, falso o vacío son valores válidos. Logs que no
modifican bindings ni heap relevante son positivos; efectos no resumidos deben
conservar unknown cuando se afirma ausencia de interferencia.

## 3. Batch Work Queue: registrar trabajo y consumir el lote que se vacía

**Algoritmo en palabras:** registrar unidades de trabajo; una operación posterior
recorre ese lote e invoca cada trabajo; sólo después de agotar el recorrido lo
retira/vacía según la política. La cola vacía de antemano seguida por un loop
sintácticamente presente no demuestra consumo. Un `break` tras el primer elemento
seguido de clear no cumple el contrato de drenaje completo.

```kql2
language "kql/2";
module proposed.batch_work;
import ken.core;

pattern Drain(out TypeDecl $unit, out Callable $consume) {
  class $unit {
    field $queue {}
    method $register {
      param $work { reassigned: false; }
      body { insert $work into $queue; }
    }
    method $consume {
      body {
        at entry { let $batch = read($queue); }
        gap until next {
          forbid remove_elements($batch);
          forbid write(binding($queue));
        }
        iterate $batch as $work {
          completion: exhausted;
          source_changes: forbidden;
          body { call $work {}; }
        }
        clear $batch;
      }
    }
  }
  where $register != $consume;
}
query results { use Drain(unit: $unit, consume: $consume); select $unit, $consume; }
```

`insert`, `clear`, `completion`, `source_changes` y `at entry` son propuestas de
sintaxis **pendientes de definición/implementación**. La primera debe mapearse a
mutaciones de colección acreditadas, y las propiedades del recorrido a semántica
normalizada de CFG/efectos, no a una función detectora de cola. El `let` de entrada
retiene identidad del lote, no una copia implícita de sus elementos.

Hay dos contratos distintos que no deben mezclarse:

1. **Candidato batch:** existe consumo de un elemento y clear posterior. No acredita
   todos los trabajos ni ejecución exactamente una vez.
2. **Drenaje completo:** todos los elementos del lote de entrada se activan antes
   de completar el vaciado; branches, break/continue/return, excepciones y mutación
   del contenedor deben respetar esa afirmación. Requiere cierre del análisis.

Si se permite insertar durante el procesamiento, se necesita una política
explícita sobre qué lote pertenece al drenaje. Capturar snapshot y dejar nuevas
entradas para otro turno es una variante distinta de consumir cola viva. No
inferir FIFO, atomicidad, single consumer ni exactly-once a partir de un `for`.

**Positivo mínimo Java:**

```java
void submit(Runnable job) { queue.add(job); }
void drain() {
    for (Runnable job : queue) {
        audit();
        job.run();
    }
    queue.clear();
}
```

El ejemplo acredita secuencia bajo terminación normal; no garantiza finalización
si `job.run` lanza. La variante de objetos usa `call $run {receiver:$work;}` y un
modelo de interfaz funcional; la variante closure invoca el Value directamente.

**Contrastes:** clear antes del loop; loop sobre otra cola; sustituir `job` antes
de invocarlo; llamar logging con `job` pero no ejecutarlo; break temprano seguido
de clear; retornar antes de clear; alias del mismo lote (positivo); snapshot con
mutación de cola viva (variante separada); limpiar antes de reenviar una excepción
(política de pérdida, no drenaje exitoso).

## Primitivas compartidas y orden de trabajo

| Prioridad | Primitiva genérica | Desbloquea |
| --- | --- | --- |
| 1 | Captura Value de expresión y llamadas a Value; igualdad de origen por ocurrencia | Dispatch, adaptadores funcionales, closures Command, Observer callbacks |
| 2 | Lectura/escritura de lugares indexados con claves Value y modelos de APIs | Dispatch, caches, registros Observer y change sets |
| 3 | Condición sobre Value y retornos/join por rama | Cache Aside, Read Through, State, Mediator tags |
| 4 | Fragmento insert/remove/clear y loop sobre Value con políticas de término | Batch, Unit of Work no transaccional, Observer y Command encolado |
| 5 | Restricciones de región/entrada/salida y efectos sobre lugares/colecciones | Retención, drenaje fuerte, snapshot, caches y varios GoF |

Priorizar Dispatch directo ofrece el corte de implementación más pequeño y prueba
que la expresión fuente indexada definida originalmente funciona de extremo a
extremo. Después Cache verifica joins y exclusión de ramas. Batch debe iniciar con
claim de candidato explícito y avanzar a drenaje fuerte sólo con semántica de
salidas y efectos suficiente.

Unit of Work reutiliza batches indexados y consumo por acción de persistencia;
no debe declararse transaccional antes de modelar begin/commit/rollback y su
recurso compartido. Exception Retry necesita siguiente iteración tras el catch y
los efectos de finally; un `continue` aparente que finally anula es el negativo
central. Subclass Factory necesita valores de tipos/clases y retorno de una
clase derivada; construir una instancia no es un sustituto.

No se modificó ningún fichero de producción ni de tests para estas propuestas.

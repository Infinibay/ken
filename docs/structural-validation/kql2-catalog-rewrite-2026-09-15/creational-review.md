# Revisión de autoría KQL 2: creacionales

15 de septiembre de 2026. Estado parcial: **no están migradas todas las variantes**.
La aceptación no consiste en cambiar nombres de relaciones internas por helpers.
Las consultas deben describir participantes, construcción, retención y consumo de
valores; las diferencias de algoritmo siguen siendo variantes visibles.

## Cambios comprobables

| Entrada | Algoritmo expresado en BODY | Límite pendiente |
| --- | --- | --- |
| Factory Method / virtual-slot | Operación sobrescrita construye producto y retorna ese valor, admitiendo trabajo intermedio. | Candidato de definición; consumo por cliente es refinamiento separado. |
| Factory Method / contract-slot | Cliente recibe contrato e invoca su slot sobre ese parámetro; implementación concreta crea y retorna producto. | No acredita que esa implementación concreta sea la recibida en runtime. |
| Factory Method / client_flow | Captura resultado del slot y exige que una llamada posterior lo consuma como argumento. | No prueba todos los caminos ni factibilidad del despacho. |
| Abstract Factory / nominal-families | Dos operaciones de creación retornan sus propias construcciones bajo dos categorías de producto. | Categoría distinta no demuestra compatibilidad de familia. |
| Abstract Factory / structural-families | Dos proveedores presentan slots de nombre/aridad compatibles y retornan construcciones distintas. | Proveedor estructural candidato; falta compatibilidad semántica y objetos literales. Comparaciones de propiedades necesitan benchmark. |
| Builder / mutable-product | Paso almacena entrada en estado; finalizador construye usando ese estado y retorna ese producto. | Retención final de entrada utiliza predicado genérico; ciclo de vida/efectos ocultos no probados. |
| Builder / accumulated-state | Finalizador ahora debe pasar la colección a la construcción y retornar ese valor. | Registro de colección aún es predicado; conversiones intermedias válidas requieren flujo modelado. |
| Builder / immutable-product | Paso crea sucesor con estado previo y entrada nueva, lo retorna; finalizador construye producto con estado. | Pasar argumento no demuestra que el constructor lo retenga; falta contrato de inicialización genérico. |
| Prototype / explicit-copy | Constructor seleccionado retiene entrada en campo; copia llama a ese constructor con campo original y retorna el valor nuevo. | Actualizado: `argument $state for $input` enlaza posiciones distintas y argumentos nombrados; packs no resueltos conservan incertidumbre. Copia parcial/superficial válida, no deep-copy. |

No se borraron variantes no migradas ni se degradaron sus tests para aparentar
que todo está terminado. Singleton no se modificó en esta subtarea: una consulta
sin guardas, ámbito y retención sería semánticamente inferior a la existente.

## Primitivas que faltan para terminar sin filtrar IR interno

### Enlace de argumentos por parámetro

Prototype debe aceptar estado en cualquier posición, incluidos parámetros
nombrados. Propuesta pendiente, **no sintaxis ejecutable todavía**:

```kql2
constructor $initialize {
  parameters { param $input {} }
  body { $state = $input; }
}
method $copy {
  body {
    let $replica = call $initialize { argument $state for $input; };
    return $replica;
  }
}
```

`for $input` resuelve binding real de llamada a parámetro, incluidos argumentos
nombrados; no compara simplemente un índice fuente.

### Guarda y retención Singleton

```kql2
class $unit {
  fields { field $shared { static: true; type: nominal($unit); } }
  method $obtain {
    static: true;
    body {
      if ($shared == null) {
        let $created = construct $unit {};
        $shared = $created;
      }
      return $shared;
    }
  }
}
```

Además del bloque se necesita demostrar polaridad del guard, inicialización en
todos los caminos miss relevantes y ausencia de otra escritura del slot. Existir
un camino feliz no prueba Singleton. Eager requiere inicializador de declaración,
restricciones de construcción y ámbito. Once requiere identidad de API y contrato
de ejecución del callback, nunca sólo llamar a algo cuyo nombre sea `once`.

### Lugares de miembros y snapshots

Prototype field-copy y Builder stored-product necesitan expresiones que unan el
objeto producido con el campo escrito (`$replica.$field = $source.$field`) y el
valor retornado después de esas escrituras. Asociar sólo el nombre del campo o
un alias histórico introduce falsos positivos. Una escritura posterior que
reemplace ese miembro debe invalidar el estado capturado.

### Typestate y productos asociados

Builder typestate necesita seleccionar parámetros genéricos, sustituciones en
retornos y restricciones del estado que admite finish. Abstract Factory Rust
requiere tipos asociados y compatibilidad de productos. Renombrar hechos de tipo
como funciones públicas no demuestra esas obligaciones.

### Director e identidad entre llamadas

Director debe ejecutar pasos y finish sobre la misma instancia; un binding que
se reasigna entre ellos no es la misma instancia. Hace falta captura de lectura
como Value más intervalo que preserve el receptor, con efectos explícitos y
unknown ante llamadas que puedan mutarlo. No basta ordenar llamadas.

## Pruebas

Se añadió `tests/structural/test_authored_creational_body.py`: 21 casos directos
sobre variantes (no la unión, que podría ocultar un detector roto), en Python,
Java y TypeScript. Positivos con ruido y negativos por entrada constante,
constructor que descarta estado, retorno del original y reemplazo del resultado.

Ejecutadas en este estado parcial:

- `test_graph_plans.py` + `test_algorithm_factory_method.py`: 62 passed.
- `test_algorithm_prototype.py` + `test_algorithm_builder.py`: 57 passed, 3 xfailed
  (la política adicional de independencia profunda sigue pendiente).
- `test_authored_creational_body.py` + `test_algorithm_abstract_factory.py`:
  39 passed, 3 xfailed (compatibilidad de familia aún no acreditada).

Estos resultados no sustituyen replay de corpus, matriz completa por lenguaje ni
benchmark de los nuevos BODY/joins. Deben repetirse tras integrar cambios del
motor hechos en paralelo.

## Revisión posterior de la suite global

Se corrigieron tres comprobaciones de autoría que todavía exigían textos internos
(`TARGET`, `RETURNS_NEW`, etc.). Ahora verifican el BODY publicado; sus oráculos
positivos y negativos de fuentes permanecen iguales. Las tres pasan.

Las pérdidas de detección observadas requieren motor, no invertir expectativas:

- Builder mutable/inmutable y Factory Method contractual en Rust: los positivos
  retornan construcciones o llamadas mediante la expresión final del bloque.
  BODY debe admitir ese retorno semántico, sin confundirlo con una expresión
  anterior descartada por punto y coma.
- Builder acumulativo: positivos Python `Workflow(list(self._steps))` y TS
  `new Workflow([...this.steps])` copian la colección antes de construir. Exigir
  inicializador directo pierde estos positivos. Propuesta de autoría pendiente:
  `let $snapshot = copy $state; let $built = construct $product { initializer
  $snapshot; }; return $built;`. La operación de copia debe estar acreditada por
  semántica de builtin/spread, no por nombres arbitrarios. `consume(state);
  return Product(0)` sigue siendo negativo.
- Prototype con constructor Java que escribe estado y después ejecuta
  `publish(this)` es aceptado por el BODY de asignación más `final_member_input`.
  No equivale al contrato previo de retención: un escape puede permitir mutación
  externa antes de completar la construcción. Hace falta restricción pública de
  escape/efectos sobre el receiver, con unknown donde no se pueda acreditar.
  No se agregó un predicado que oculte el detector completo.

Aunque ya existen if/else en BODY, Singleton aún necesita inicializador de campo,
inventario de escrituras por callable y cobertura de los caminos hit/miss. Una
búsqueda existencial que encuentre una inicialización y un retorno no permite
suprimir esas obligaciones. Typestate, almacenamiento de producto y copia de
campos requieren todavía miembros correlacionados a valores y sustitución de
tipos, según se detalló arriba.

## Restricción pública del receiver: escapes

Ya implementada en selectores relacionales:

```kql2
constructor $initialize {
  receiver $self { escapes: false; }
  parameters { param $input {} }
  body { $state = $input; }
}
```

El filtro resume el receiver **dentro del callable seleccionado**, reutilizando
el índice/operaciones existentes y el presupuesto del executor. Memoiza por
(callable, receiver); no se copian grafos ni se generan consultas nuevas.
Un envío directo como argumento (`publish(this)`) acredita exposición. Un alias,
contenedor, retorno del receiver, captura o llamada opaca sobre el receiver
produce unknown cuando no se puede demostrar ausencia. `escapes: false` no acepta
ese unknown. Lecturas/escrituras de miembros y logging de valores ajenos al
receiver permanecen aceptados. No es un análisis global del heap ni de reflexión.

Una delegación Java `this()` sólo se admite si el constructor destino sin
argumentos es único en el inventario nominal y su propio resumen acredita
noescape; no se generaliza por nombre a un llamado arbitrario. Recursión o
destino incierto permanece unknown. Las capturas anidadas se excluyen de manera
conservadora, incluso si posteriormente se demuestra que no se invocan.

Prototype explicit-copy ahora usa esta propiedad; vuelve a rechazar
`publish(this)` sin ocultar un detector de Prototype en el motor. Pruebas:
12 tests propios del filtro pasan; 5 casos de constructor Java delegado pasan;
53 tests de filtro/copia y algoritmos pasan con 3 xfail existentes de la política
adicional de independencia profunda. Una revisión futura puede mejorar precisión
sobre aliases locales sin escape, conservando siempre unknown ante falta de prueba.

## Copia superficial del estado acumulado

Builder accumulated-state ahora permite explícitamente:

```kql2
let $built = construct $product {
  initializer $state { transfer: [identity, shallow_copy]; };
};
return $built;
```

Usa los modelos generales recién incorporados para `list` builtin Python y array
con un único spread JavaScript/TypeScript. No acredita la transferencia por un
helper arbitrario llamado `copy`, ni por `list` ocultado por una definición local.
Dieciséis pruebas propias pasan (directo/copia/ruido y negativos correlacionados);
los diez casos de matriz accumulated-state pasan, resolviendo los seis falsos
negativos registrados para copias y ruido.

La restricción de escape también conserva unknown ante ejecución reflexiva
`eval`, `exec`, `execfile`, `compile`, `Function` y constructor base explícito de
efectos desconocidos. Sus dieciséis tests pasan, incluyendo los ejemplos Python
exec/eval y JavaScript eval. El reconocimiento conservador de esas superficies
no constituye una prueba exhaustiva frente a todas las APIs reflexivas posibles.

## Singleton lazy: migración ejecutable

`singleton.lazy_instance` ahora está escrito con selectores y BODY. Incluye
inicialización en brazo miss con retorno común, guard hit con retorno temprano,
y retornos separados en ambos brazos, con ambas polaridades de la condición.
Los comparadores nulos equivalentes se normalizan por la evidencia semántica del
binding; esto no generaliza igualdad coercitiva de JavaScript a cualquier valor.

Primitivas generales añadidas:

- `field $state { initial: null; }`: inicializador acreditado por inventario;
  una escritura histórica posterior de null no acredita el valor inicial.
- `method $get { writes: exactly($state, 1); }`: cuenta escrituras explícitas de
  ese binding **en ese callable**, con inventario cerrado. No cuenta los writes
  del resto del proyecto como si fueran del accessor; incompleto es unknown.
- `body linear`: permite operaciones intermedias, pero no atraviesa decisiones
  omitidas en la consulta. Hereda la restricción en brazos e iteraciones. En un
  brazo descrito, una salida abrupta posterior que no figura en el patrón impide
  acreditar continuación normal. Evita aceptar inicialización condicionada por
  un segundo if o `return null` oculto después de escribir la instancia.
- `out Call $creation` con `let ... as $creation`: el tipo de evidencia selecciona
  la identidad Call de esa misma ocurrencia. `out Operation` conserva la identidad
  de operación. No se preliga una captura todavía inexistente. El compilador
  público también elige el plan que conserva estos tipos.

La construcción expuesta se correlaciona mediante un segundo BODY que la consume
al escribir el mismo slot. La unicidad de escritura por accessor evita unirla a
una construcción incidental. Los roles creados dentro de un brazo no se filtran
fuera de su ámbito.

Validación de corte: 186 pruebas de lazy/null/control/uso/contratos pasan; la
prueba adicional de routing de Call también pasa. Las 147 regresiones generales
BODY/intervalos/consultas guardadas pasan después de integrar los cambios.

El antiguo presupuesto de 25k estados medía joins del perfil de grafo. BODY cobra
también recorrido CFG y procedencia de valores. El test conserva límites de
filas/tiempo y comprueba ahora 100 y 200 candidatos, todos encontrados y aumento
de estados menor o igual a 2.2x al duplicar tamaño. El límite de estados escala
con candidatos, en lugar de suprimir verificaciones de control para conservar un
contador anterior que representaba menos trabajo. No se modificó el oráculo de
los casos positivos/negativos.

**No está terminado Singleton completo**: eager, module-shared y once-primitive
siguen pendientes de autoría fuente. Necesitan bloques de inicializador en
contextos de tipo/módulo, inventarios de constructores y modelos explícitos de
celda/retención/adaptación. Las variantes válidas permanecen presentes; este corte
no las elimina ni las declara migradas.

### Corte posterior: inicialización declarativa de Singleton

`singleton.shared_instance` usa ahora campo con expresión `initializer`,
selector de accessor estático sin parámetros, inventario de cero escrituras
explícitas al campo en ese accessor y BODY que retorna el campo.
`singleton.observed_lazy_use` selecciona una ocurrencia `call` cuyo `target`
es el accessor acreditado. Los outputs `unit` del principal y variantes que
sólo exportan ese participante son `TypeDecl`.

El operador genérico de expresión inicial no confunde una construcción anidada
(`wrap(new Shared())`) con el valor inicial del campo, ni una asignación posterior
con su declaración. 24 pruebas iniciales de cuatro lenguajes cubren raíz,
paréntesis, llamada contenedora, otro tipo, nulo y asignación posterior. Se añadió
además una prueba de routing para no confundir el matcher de binding dentro de
`construct` con el prefijo BODY de inicialización de constructor.

Este corte **no cierra Singleton completo**: las restricciones de inventario de
`eager-shared`, `module-shared` y `once-primitive` siguen pendientes de migración.
Las variantes siguen disponibles. No se cambiaron a una consulta más débil para
eliminar texto interno. La suite KQL2 completa pasa tras corregir la selección
del backend para las tres formas distintas de `initializer`.

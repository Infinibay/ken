> **Actualización de esta continuación (15/09):** las cifras y las rondas de abajo son históricas. El [inventario actual por entrada](authoring-inventory.json) registra 162 entradas: **72 todavía requieren reescritura**, 12 usan sintaxis fuente pero requieren revisión semántica, 34 componen dependencias todavía no revisadas en conjunto, **43 tienen revisión conductual en esta continuación** y 1 carece de consulta. Revisión conductual no significa cobertura exhaustiva ni ausencia de defectos. No se ha completado la migración de los 33 TOML.
>
> El ejemplo Worker de la documentación se ejecuta literalmente en tests Java/C#. El backend también admite tipos fuente, receiver, if/else, parámetros sin reasignación, argumentos vinculados al parámetro destino, llamadas seleccionadas por ocurrencia, retornos implícitos Rust, escapes del receptor y copias superficiales modeladas. La suite amplia inicial de esta continuación dio **11.695 passed, 55 failed, 10 xfailed**; tras corregir causas, la suite completa revisada dio **11.832 passed, 10 xfailed, 0 failed en 325,46 s** (IR 1.81). Los resultados históricos de abajo no acreditan esta revisión.
>
> Composite `recursive-contract` y `recursive-nominal` ahora usan `iterate` y `call` dentro de BODY. Facade `object-surface` correlaciona los campos tipados con receptores de las dos llamadas en una misma ruta. Se agregaron contraejemplos de campos sin uso, ramas incompatibles y llamadas a un solo servicio, en Python/Java/TypeScript.
>
> **Ronda 16 — `state#state-enum` y lo que hizo falta para escribirlo.** La variante dejó de usar `edge GUARDS_WRITE` + `tally distinct`: ahora la máquina se escribe como dos transiciones correlacionadas por los valores comparados y escritos, y BODY **captura** esos valores (`out Value $observed, out Value $next`). Para que el contrato fuera honesto hizo falta, además: aceptar `===`/`!==` como la igualdad que KQL pide (nunca al revés), publicar `elif` como rama con sus dos brazos, normalizar la región de un `else` a la sentencia que contiene, y dar a BODY **lugares miembro** (`$context.state = $context.other`), documentados en [behavior.md](../../design/kql2/behavior.md). Efecto medido: 6 de 8 lenguajes declarados (C++/Rust quedan `pending_languages` con la brecha fijada por test), y el corpus **93/281** — la baja de 94 a 93 es una falsa positiva que se fue: `python-patterns/behavioral/state.py` lo marcaba el `tally` antiguo por `self.pos`, un cursor, no un estado. Dos reglas de proceso quedan registradas: una variante que no tiene sentido **se borra**, una que falta **se implementa**, y una sintaxis fea de KQL 2 **se mejora**.
>
> La procedencia actual **no sigue FLOWS_TO histórico** para validar un valor producido: utiliza orígenes por ocurrencia. Los argumentos sí admiten valores capturados; la limitación descrita al final de este documento quedó superada. La resolución de constructores requiere identidad de overload acreditada. Ver el [contrato ejecutable actualizado](../../design/kql2/saved-body-execution.md).

## Capturas y consumidores, IR 1.85

Validación final con los archivos de producción congelados: **12.566 passed,
10 xfailed, 0 failed en 358,70 s**, ejecutando `tests/structural`, `tests/kql2`
y `tests/common_ast`. Incluye 56 tests de usos de valores y casos multilenguaje
de callback, condiciones booleanas y cuantificadores. Los 10 xfail preexistentes
siguen pendientes; no se contabilizan como casos corregidos.

Se implementó la sintaxis aprobada de capturas dentro de iteraciones: `let`
captura un valor evaluado aunque el programa no lo almacene en una variable;
`break $loop as $exit` comprueba el destino real de la salida. Las condiciones
con negación sólo equivalen a `== false` cuando el resultado booleano está
acreditado. Se conserva la sintaxis anterior `break;`.

El nuevo selector `usages of $value as $use { ... }` encuentra consumidores
directos como argumentos, retornos, asignaciones, condiciones y operandos.
Las copias acreditadas conservan identidad; las reasignaciones la invalidan y
las operaciones derivadas no se confunden con el valor original. El inventario
es abierto: no se demuestra ausencia global de usos ni flujo exhaustivo a través
de heap, closures o llamadas interprocedurales. Contrato y ejemplos:
[valores y usos](../../design/kql2/value-usages.md).

También se implementaron `require exists constructor of $type` y
`require every constructor of $type { visibility: private; }`. Esto migra esa
parte de Singleton; no completa su consulta de conteo de asignaciones ni la
migración del catálogo. La variante de callback aún conserva un output público
de rama que necesita una decisión de autoría antes de migrarse íntegramente.

El replay externo IR 1.85 mantiene **11 TP, 5 TN, 1 FP, 3 FN y 2 ambiguos**
en los mismos 22 pares etiquetados: [resultado](reviewed-open-source-ir185-unlimited.json).
Estos cambios amplían expresividad y corrigen casos dirigidos, pero no mejoraron
ese oráculo. Sus tiempos concurrentes con tests no son un benchmark.

## Corte funcional IR 1.84, sin límites de búsqueda

La ejecución amplia sobre el corte de catálogo y motores congelado terminó con
**12.274 passed, 10 xfailed, 0 failed en 352,54 s** (`tests/structural`,
`tests/kql2`, `tests/common_ast`). Los xfail siguen siendo casos conocidos, no
casos corregidos. Los ajustes posteriores de límites y de inicializadores se
validan por separado; no atribuir esta ejecución a archivos modificados después.

El replay del oráculo manual en repositorios fijados por commit y hash se ejecutó
con `QueryBudget()` sin límites de tiempo, estados, filas ni matches. Resultado:
**11 TP, 5 TN, 1 FP, 3 FN y 2 ambiguos**, igual al corte IR 1.81. Ver
[resultado íntegro](reviewed-open-source-ir184-unlimited.json). Son 22 pares
etiquetados, no una medición exhaustiva del catálogo. Los tiempos de esta ronda
coinciden con otras pruebas y no sirven como benchmark comparativo.

Persisten el FP Observer en CompositeGraphic y los FN Adapter dinámico Python,
Visitor extrínseco Python y Mediator Rust TrainStation. La migración de sintaxis
no ha corregido por sí sola esos cuatro casos; no se cambió su etiqueta para
presentar una mejora artificial.

Decorator y Dependency Injection tienen guards de autoría fuente junto a las
familias ya cerradas. Los tests dirigidos de ambas familias y esos guards dieron
99 passed. La poda de candidatos de asignación se comparó con el evaluador de
referencia, incluidos grafos sin hechos de valor o CFG: 38 tests passed en el
módulo de optimización de joins. Las pruebas con presupuesto permanecen separadas
de este replay funcional ilimitado.

La generalización de joins/subconsultas extraídos de BODY queda diferida para
priorizar corrección: [estado y propuesta](../../design/kql2/body-relational-planning.md).

La API pública de KQL2, su CLI y la entrada MCP también usan ahora límites de
tiempo, estados y filas desactivados por defecto (`None`). Las uniones y los hits
de caché aceptan ese modo. Se conservan cancelación, límites explícitos y cuota de
caché. La validación posterior de esas áreas dio **679 passed**, incluidos 27
tests nuevos. Este conteo se solapa con la suite amplia y no debe sumarse a ella.

La revisión posterior de inicializadores encontró dos defectos: pérdida de
`unknown` al faltar enlaces o existir modalidad `may`, y rechazo de comentarios
dentro de paréntesis transparentes. Ambos se corrigieron: **147 tests dirigidos
passed**, y luego **532 tests de catálogo/contratos/migración passed**. Se
conservaron negativos de literal, otro tipo y construcción anidada dentro de una
llamada contenedora. El oráculo externo ilimitado se repitió tras esta corrección
con los mismos resultados de precisión indicados arriba.

# Reescritura del catálogo GoF en KQL 2: primera etapa

15 de septiembre de 2026. Estado: **26 de 83 variantes GoF sin `edge`** (23 reescritas desde
el perfil de grafo y 3 nuevas), verificadas
contra el oráculo congelado, la matriz por variante/lenguaje, los casos dirigidos y
el corpus negativo. Este documento registra lo habilitado, la receta de migración y
el trabajo que falta. No declara terminada la reescritura.

## Por qué el catálogo estaba escrito con `edge`

`ken/kql2/catalog.py` compila **todo** TOML guardado con `relational=True`, es decir
al plan relacional (`graph.relational_plan`). Ese backend sí entiende selectores
anidados —`source_patterns.selector` baja `class`/`method`/`field`/`param`/
`constructor`/`operation` a `ENTITY`/`HAS_METHOD`/`HAS_FIELD`/`HAS_PARAMETER`/
`HAS_OPERATION`— pero su `where` sólo aceptaba comparaciones unidas por `and`. Por
eso ningún predicado público (`possible_call`, `returns_new`) era utilizable en una
regla guardada y todas las consultas acabaron expresando los hechos con `edge`.

## Qué se habilitó

| Cambio | Archivo | Efecto |
|---|---|---|
| `where` acepta predicados públicos y los baja a `Node('fact', Edge('require', ...))` | `src/ken/kql2/graph.py` | `where possible_call($a,$b);` funciona en TOML guardado |
| `possible_call` y `returns_new` exigen `execution: possible` | `src/ken/kql2/graph.py` | El código muerto publica `CALLS` con `execution: unreachable` y sigue sin satisfacerlos (`dead-facade`, `dead-template-method`) |
| Tabla de predicados ampliada con `overrides`, `subtype`, `implements` | `src/ken/kql2/semantic.py` | Semántica documentada, no un alias de `edge` |
| `type: nominal($role)` en selectores relacionales | `src/ken/kql2/source_patterns.py` | `field $f { type: nominal($contract); }` baja a `TYPE($f,$contract)` |
| `constructor` y `context_manager` como propiedades de callable | `src/ken/kql2/compiler.py` | `method $m { constructor: false; }` es expresable |
| `receiver: $place;` dentro de `call` en BODY | `src/ken/kql2/body.py` | Correlaciona la instancia receptora, no sólo su tipo: es la forma KQL 2 de la delegación |
| `let $result = call $target { ... } as $op;` con `return $result` | `src/ken/kql2/body.py` | Captura el **valor** que produce una llamada y lo consume por procedencia (`FLOWS_TO`/`LOADED_FROM`); probado en los siete lenguajes con frontend |
| El camino de store materializa la vista de consulta y restaura el contrato de `ARGUMENT` | `src/ken/kql2/semantic.py` | Una regla guardada y una consulta independiente ven los mismos hechos; BODY sigue leyendo el operando crudo por ocurrencia |
| `let $x = construct $type { initializer $place; } as $op;` | `src/ken/kql2/body.py`, `syntax/parser.py` | Construcción acreditada por el **tipo producido** y el **lugar que transporta**, no por un símbolo invocable: cubre literales Go/Rust y llamadas a constructor |
| `where returns_value($callable, $value);` | `src/ken/kql2/semantic.py` | Liga el valor devuelto —incluida la expresión final implícita— a la construcción capturada |
| Un `call` cuyo destino es un constructor acredita la construcción | `src/ken/kql2/body.py` | `Product(self.x)` no resuelve a `__init__`, pero produce una instancia del tipo que lo declara |
| `where nominal_root($type, $root);` | `src/ken/kql2/semantic.py` | Raíz nominal declarada: la alternativa C++ de Bridge exige raíces distintas entre abstracción e implementación |
| `construct $type` liga el tipo construido si el patrón no lo nombra | `src/ken/kql2/body.py` | Evita un escaneo de todos los tipos: la variante de Builder pasó de agotar 100.000 estados a ~10.600, y recuperó el caso Java del corpus |
| `where reads($callable, $place);` / `where writes($callable, $place);` | `src/ken/kql2/semantic.py` | Lectura y escritura de lugares con `execution: possible`: el código muerto publica `unreachable` y no satisface el predicado |
| `call $place { ... }` invoca el callable **retenido** en un campo, variable o parámetro | `src/ken/kql2/body.py` | La llamada se acredita por `CALLEE_VALUE`, no por símbolo: callbacks, closures y campos de tipo función |
| `where writes_element($callable, $collection);` / `where iterates_calls($callable, $collection);` | `src/ken/kql2/semantic.py` | Registro en colección y recorrido que invoca a los elementos; `x.append(v)` publica ahora la escritura de elemento gruesa (`frontend.py`), igual que `x[i] = v` |
| Asignaciones aumentadas (`x += 1`) publican `READS`/`WRITES` gruesos | `src/ken/structural/frontend.py` | Igual que `x++`; sin ellos un iterador con estado aumentado no acreditaba la escritura |
| `where returns_self($callable, $type);` / `where returns_type($callable, $type);` | `src/ken/kql2/semantic.py` | Protocolo de iteración (`__iter__` devuelve el propio iterador) y fábricas que devuelven un valor de ese tipo sin construirlo con `new` (unit structs de Rust) |
| `where final_member_input($write, $configured);` | `src/ken/kql2/semantic.py` | Última escritura de un parámetro no reasignado en un campo: es la aportación de un paso de configuración, y distingue la escritura condicional o seguida de reasignación |
| `where linear_members($callable);` (predicados unarios de estado de análisis) | `src/ken/kql2/graph.py`, `semantic.py`, `execution.py` | Un cuerpo con rama, escritura indirecta o ámbito no resuelto publica `unsupported` con su causa |
| `DECLARED_TARGET` cuenta como destino exacto acreditado | `src/ken/kql2/body.py` | Un slot declarado por anotación nominal satisface `call $slot`; `MAY_TARGET` sólo con `dispatch: possible` |
| Un destino acreditado distinto, o ninguno, no es «unknown» | `src/ken/kql2/body.py` | La ocurrencia simplemente no es la descrita; evita `source_body:unknown` espurio en cada llamada no resuelta |

## Variantes ya reescritas (21)

`abstract-factory#nominal-families`, `abstract-factory#associated-products`,
`adapter#object-adapter`, `adapter#class-adapter`, `bridge#runtime-composition`,
`builder#mutable-product`, `command#retained-object`, `facade#object-surface`,
`factory-method#virtual-slot`,
`interpreter#expression-objects`, `iterator#generator`, `iterator#delegated-generator`,
`iterator#external-cursor`, `iterator#explicit-cursor`, `iterator#paired-cursor`,
`state#state-object`, `strategy#strategy-object`, `strategy#strategy-callable`,
`template-method#virtual-skeleton`, `template-method#trait-default`. Además `prototype#derived-clone` y
`singleton#lazy-guarded` ya eran KQL 2 puro (sólo componen una operación).

Delegación con receptor, en `adapter#object-adapter`:

```kql2
pattern detect(out TypeDecl $unit) {
  type $adaptee { method $delegate { } }
  type $contract { method $slot { } }
  type $unit {
    field $place { type: nominal($adaptee); }
    method $method {
      body {
        call $delegate { receiver: $place; };
      }
    }
  }
  where subtype($unit, $contract);
  where overrides($method, $slot);
  where $contract != $adaptee;
}
```

## Migraciones intentadas y revertidas (bloqueadas por primitiva)

* `decorator#object-wrapper`: la delegación con receptor es expresable, pero la
  **responsabilidad añadida** (llamada extra o transformación del resultado) no.
  Sin ella el detector acepta un envoltorio transparente, que
  `test_gof_executable.py::test_similar_collaboration_without_defining_behavior`
  rechaza. Revertida.
* `command#retained-contract`: en C++ el receptor llega por **lista de
  inicialización** (`Job(Sink* r):receiver(r){}`), que el frontend publica como
  `CONSTRUCTOR_FIELD_INPUT` sin operación de asignación, así que BODY no puede
  describirla. Revertida.
* `mediator#direct-colleagues`: la coordinación canónica despacha dentro de un
  `if/else`; BODY no secuencia instrucciones de ramas distintas, así que las dos
  llamadas correlacionadas no aparecen en un mismo camino. Revertida.
* `bridge#runtime-composition`: la alternativa C++ exige raíces nominales
  distintas (`NOMINAL_ROOT`), que no tiene predicado público equivalente;
  sustituirla por una restricción de lenguaje perdía cobertura C++. Revertida.
* `adapter#functional-adapter`: la invocación con **dos argumentos distintos
  obtenidos indexando el mismo parámetro de entrada** (`VALUE`/`INDEX`/`CONTAINER`)
  no es expresable todavía. `argument $request[$i] at any;` no compila: BODY sólo admite
  operandos `member`, rol, literal o binarios, y un rol de índice libre no está
  ligado (`source operand requires a bound storage, parameter or captured value`).
  Necesita un **origen de valor por índice** como primitiva pública. Revertida.
* `builder#mutable-product` **migrada**: `construct` + `returns_value` +
  `final_member_input` + `constructor: false` conservan los negativos del oráculo
  (constructor como paso, rama, reasignación del parámetro, sobreescritura muerta).
  `linear_members($step)` queda disponible como predicado unario y está probado en
  `tests/kql2/test_write_inventory.py`.


```kql2
pattern detect(out TypeDecl $unit, out TypeDecl $creator, out Callable $factory, out TypeDecl $product) {
  type $unit {
    method $factory { constructor: false; static: false; }
  }
  type $base {
    method $slot { constructor: false; static: false; }
  }
  type $product { }
  where subtype($unit, $base);
  where overrides($factory, $slot);
  where returns_new($factory, $product);
  bind $creator = $unit;
}
```

## Receta de migración por variante

1. Leer la obligación en [contratos de comportamiento](../../design/kql2/catalog-behavior-contracts.md)
   y la consulta `edge` actual; los roles públicos (`out`) no cambian, porque el
   contrato congelado los compara.
2. Escribir participantes con selectores anidados y conducta con predicados
   públicos; **no** traducir `edge X` a una función con otro nombre.
3. Verificar, en este orden:
   * `pytest tests/structural/test_catalog_kql2_migration.py -q -k <patrón>` — paridad
     de bindings/status/unknown contra las consultas congeladas pre-KQL 2.
   * `pytest tests/structural/test_catalog_adversarial_matrix.py -q -k <patrón>` —
     familias canónica/inert/ruido/algoritmo-eliminado y casos dirigidos.
   * `pytest tests/structural/test_negative_corpus.py -q` — que la variante no
     empiece a marcar diseños que no son el patrón.
   * `pytest -q` completo antes de cerrar el lote.

## Variantes nuevas (no sustituyen a ninguna)

* `mediator#registered-colleagues` (python/java/typescript): coordinador con dos campos
  tipados por colegas, una invocación por colega acreditada **por separado** (dos
  invocaciones del mismo patrón auxiliar), de modo que dos ramas de un `if` cuentan
  igual que dos llamadas consecutivas, y cada colega vuelve a llamar al coordinador.
* `observer#registered-listeners` (python/java/typescript): un método registra
  elementos en una colección y otro distinto la recorre invocándolos.
* `builder#accumulated-state` (python/typescript): el constructor acumula pasos en un
  campo y devuelve lo acumulado (ronda 13; es la única variante nueva que **sí** añadió
  recall: 92 → 94/281).

Las dos primeras pasan la matriz por variante/lenguaje, los casos dirigidos y el corpus
negativo, pero **no añadieron recall sobre el corpus etiquetado** (90/281 antes y
después): los ejemplos reales de mediator y observer usan diccionarios, buses de eventos
y `forEach`, formas que exigen iteración con clave y callbacks — la siguiente primitiva.

## Intentos revertidos con la causa medida (ronda 12)

* `singleton#guarded-storage` (almacenamiento estático + escritura bajo guarda +
  devolución del almacenamiento): marcaba dos casos nuevos (cpp, typescript) pero
  aceptaba el contraejemplo documentado de **polaridad invertida**
  (`test_lazy_null_flow.py[wrong-polarity-*]`). Añadir `null_test($branch,$place,true)`
  (predicado con atributo booleano) lo endureció y entonces aceptaba
  `nested-condition-*`, donde la escritura está fuera del brazo nulo: la evidencia
  correcta es la **estructura de la guarda** (brazo nulo → escritura → retorno en
  ambos caminos), que la operación `lazy_instance` ya codifica. Revertida, junto con
  los predicados y el mecanismo de atributos que sólo ella usaba. Queda sólo
  `static` como propiedad registrada de `field`.

## Auditoría del corpus (ronda 12)

De los 189 casos perdidos, **186 son `complete-no-match`** y sólo 3 `unknown`
(`cardinality:open_world` ×2, `source_body:unknown` ×1): el presupuesto y la
completitud no son el cuello de botella — falta evidencia o sobra exigencia en la
consulta. Los peores: singleton 14, builder 13, decorator 13, memento 11, state 11,
mediator 10 (antes de la variante de esta ronda).

## Intentos revertidos con la causa medida (ronda 9)

* `memento#snapshot-roundtrip`, forma **fuerte** (`$state = $stored as $store;` tras
  `construct`+`returns_value`): no marca ningún positivo del corpus — los mementos
  reales restauran con **accesor** (`self._content = memento.get_state()`) o copiando,
  no leyendo un campo. La forma **débil** (`writes($restore,$state)` +
  `reads($restore,$supplied)`) sí marcaba tres casos (cpp, rust, typescript) pero
  aceptaba dos negativos documentados (`restore-overwrite`, y la mutación que
  sustituye la restauración por una constante): cobertura falsa. Revertida entera.
  Lo que falta es flujo de argumentos/resultados en BODY para expresar la restauración
  por accesor sin quedarse en la evidencia gruesa.

Sí quedó, como mejora de motor probada, que una asignación desde una **lectura de
miembro** del lugar ligado cuenta como ese lugar (`self.state = other.stored`), sin
aceptar valores que sólo fluyen por otras vías (`tests/kql2/test_body_member_read.py`).

## `possible_call` incluye la implementación que sobrescribe (ronda 11)

Una llamada nombra el slot **declarado** (`Party.act`), mientras el patrón liga la
**implementación** (`PartyImpl.act`): el join fallaba y con él mediator, chain y
observer en proyectos con interfaces. `possible_call` ahora es la clausura del grafo
de llamadas bajo `OVERRIDES`, **precalculada en la vista de consulta** como
`POSSIBLE_CALL` (directa + cada implementación, conservando `execution`). La primera
versión la expandía como disyunción en el plan y agotaba el presupuesto en facade
(100.000 estados, tres casos perdidos); precalcularla deja un solo join.

Con eso se añadió `mediator#broadcast-colleagues` (java/csharp): el coordinador
registra una colección de colegas, la recorre invocándolos, y cada colega retiene al
coordinador y vuelve a llamarlo. Corpus: **90 → 92/281**.

## Enlace entre archivos en Rust y `builder#accumulated-state` (ronda 13)

`semantic.module_path` no conocía Rust: `use` no se parseaba en absoluto, así que
ningún tipo importado entre archivos enlazaba y todo detector multiarchivo perdía el
caso. Ahora `rust_module_path` resuelve `crate::` (raíz del crate, no del archivo),
`self::` (directorio) y `super::` (padre), con `mod.rs` como alternativa, y el
`IMPORT_SYNTAX` de Rust acepta `use a::b::C;`, `use a::b::{self, C, D as E};` y rutas
relativas (`use model::Product;`), ligando siempre por nombre **local** al alias.
El efecto medido en el corpus etiquetado fue **neutro** (92/281 antes y después): los
repositorios Rust del corpus resuelven sus tipos por ruta o por único candidato, no por
`use`. Se conserva porque es corrección de enlace, no cobertura, y queda probado con
`tests/structural/test_semantics.py::test_rust_crate_relative_use_resolves_from_the_crate_root`
—que además comprueba el caso negativo **sin** el `use`, para que la aserción no pueda
satisfacerse por resolución intra-archivo.

La variante nueva `builder#accumulated-state` (python/typescript) detecta el constructor
cuyo paso **acumula elementos** en una colección, y cuya finalización **lee** esa
colección, **construye** el producto y **devuelve el valor construido**:

```kql2
pattern detect(out TypeDecl $builder, out Callable $finish, out TypeDecl $product) {
  type $builder {
    field $state { }
    method $step { constructor: false; }
    method $finish {
      constructor: false;
      body {
        let $built = construct $product { } as $building;
      }
    }
  }
  where writes_element($step, $state);
  where reads($finish, $state);
  where returns_value($finish, $built);
  where returns_new($finish, $product);
  where $step != $finish;
}
```

Acota lo que **no** prueba: que el producto reciba exactamente esos elementos, el orden,
ni que la finalización sea la única salida. Corpus: **92 → 94/281**
(builder/python y builder/typescript), sin pérdidas ni `unknown` nuevos.

## Enlace entre archivos: import absoluto de Python (ronda 10)

`semantic.module_path` resolvía un import absoluto (`from memento import Memento`)
sólo respecto de la **raíz del proyecto**. En un proyecto con paquetes anidados el
módulo vive junto al importador, así que la construcción no enlazaba:
`Memento(self._content)` quedaba sin `ALLOCATES_TYPE`/`INSTANCE_OF`/`RETURNS_NEW` y
varios detectores multiarchivo perdían el caso. Ahora se prueban los candidatos en
orden —directorio del importador (`sys.path[0]`), luego la raíz— y se deduplican
antes de juzgar ambigüedad. Efecto medido en el corpus etiquetado: **+2 casos**
(`behavioral/memento/document_editor/python/` y `behavioral/strategy/payment_processing/python/`)
sin tocar ninguna consulta; con las rondas 11 y 13 el total acumulado es **94/281**.

## Coste: medir, no suponer

Una variante en KQL 2 puede ser mucho más cara que su equivalente `edge`: los
selectores añaden joins y el nodo `source_body` se evalúa por fila candidata. La
primera versión de `builder#mutable-product` agotaba el presupuesto de 100.000
estados en el corpus y **perdía en silencio** un caso que la consulta anterior
encontraba. Regla: medir estados sobre el grafo real, y dejar que BODY ligue los
tipos que introduce (`construct $type`) en vez de escanearlos. El corpus etiquetado
se re-mide tras cada lote: la comparación [v5 vs v8](../../../examples/bench/validate_pattern_corpus.py)
da 89/282 en ambos, sin pérdidas ni errores.

## Trabajo que falta

La reescritura completa necesita primitivas que el motor todavía no publica. Por
frecuencia de uso en las variantes que siguen con `edge`:

| Primitiva necesaria | Variantes que la usan |
|---|---:|
| `ARGUMENT` + `VALUE` + `LOADED_FROM` (flujo de entrada y resultado; BODY ya acepta `argument $x at n`) | 26 / 26 / 16 |
| `ALLOCATES_TYPE` + `RESULT` + `RETURNS` + `RETURNS_VALUE` + `RETURNS_CALL` (construcción y retorno) | 12 / 11 / 9 / 6 / 8 |
| `ASSIGNMENT_TARGET` + `ASSIGNED_FROM` + `STORES_VALUE` (escritura de lugares fuera de una asignación BODY) | 14 / 8 / 6 |
| `CALLEE_VALUE` + `INSTANCE_RECEIVER` (callable invocado como valor; instancia propia como receptor) | 7 / 9 |
| `ITERATES_CALLS` + `ITERATED_CALL` + `CONTAINER` + `INDEX` (iteración y colecciones) | 5 / 4 / 4 / 4 |
| `CFG_NEXT` + `SYNTAX_PARENT`/`SYNTAX_NODE` + `OPERAND` (guardas, continuación y forma de una transformación) | 5 / 12 |
| `BINDS_TYPE_PARAMETER` + `TYPE_PARAMETER_*` (genéricos estáticos) | 4 |
| `BINDING_*` + `CALL_BINDING` (procedencia por ocurrencia de argumento) | 5 |

La lista completa por variante se regenera con el clasificador de relaciones usado
en esta etapa (relaciones de cada `query` que no tienen forma de selector ni
predicado público todavía).

Límites deliberados que siguen abiertos: los selectores con `exact` no se bajan al
perfil relacional; una guarda (rama que decide la delegación) todavía no tiene forma
KQL 2 en BODY, así que `proxy#guarded-access` y
`chain-of-responsibility#linked-handlers` esperan a esa primitiva; y un argumento
**no** puede consumir todavía un valor capturado con `let` — el compilador lo
rechaza con `source operand requires a bound storage or parameter` en lugar de
aceptar texto que nunca coincidiría.

## Nota de honestidad

Durante un experimento con variantes en el perfil `edge`, `adapter.toml` se dañó
(se perdió `object-adapter` y su raíz quedó con las restricciones de esa variante).
Se reconstruyó desde `HEAD` y el oráculo congelado; la paridad de contrato en los
fixtures multilingües, la matriz adversarial y el corpus negativo confirman que el
comportamiento es el mismo. El texto exacto original no se pudo recuperar byte a
byte (el hash de inventario difiere), sólo su semántica.


## Revisión externa de esta continuación

[Resultados por caso](reviewed-open-source.json), sobre los 22 pares con etiquetas
manuales y fuentes fijadas por commit/hash del informe anterior, tras distinguir
interfaces de constructores base: **11 TP, 5 TN, 1 FP, 3 FN y 2 ambiguos**. Se parseó código sin ejecutarlo. Esta
ronda convivió con tests: sus tiempos no son un benchmark de rendimiento.

El FP pendiente es CompositeGraphic de python-patterns identificado como Observer.
Los FN pendientes son Adapter dinámico y Visitor extrínseco de python-patterns,
y TrainStation de guru-rust Mediator. EmployeeRecord de Pandovski/Java ahora es TP:
implementar una interfaz no ejecuta un constructor base. La primera ronda lo
clasificó unknown conservadoramente; la distinción nominal lo recupera sin permitir
clases base opacas. Hay un TP adicional respecto del oráculo anterior; esta muestra
pequeña no prueba precisión general en todos los lenguajes o variantes.


Validación global revisada: `pytest tests/structural tests/kql2 tests/common_ast -q -o addopts=''`, **11.832 passed, 10 xfailed**, 325,46 segundos. Los diez xfail existentes siguen siendo deuda explícita, no aciertos. No se modificaron producción ni tests durante esta ejecución completa.


## Regresión de rendimiento encontrada

El [benchmark anterior a la optimización](timings-ir181.json) usa 5 repeticiones,
35 archivos Python, 24 C++ y 35 Rust, sin tests en paralelo. Suma de medianas de
33 consultas: Python 9.932 ms, C++ 9.658 ms y Rust 6.132 ms; el catálogo histórico
sobre el mismo grafo empleó 414, 204 y 171 ms respectivamente. Varias consultas
agotaron un millón de estados. Las semánticas difieren, así que no es una medida
pura del motor; sí demuestra una regresión práctica inaceptable de la migración.

Causas: un BODY se ejecutaba repetidamente para filas que sólo diferían en roles
externos irrelevantes; además, los filtros de subtipado/override escritos después
quedaban detrás de una barrera rígida. La solución mantiene la sintaxis autorada:
memo por inputs efectivos del BODY y adelanto de filtros puros que no dependan de
sus capturas. Las capturas son una frontera de dependencia real, no una barrera
para todos los predicados de declaraciones independientes.


La [primera optimización medida](timings-ir181-optimized.json) redujo esas sumas a
2.452 ms, 1.681 ms y 1.133 ms respectivamente. Completaron 32 de 33 consultas en
cada muestra: Abstract Factory todavía agotó un millón de estados. Se mantiene
como problema de planificación pendiente, no como ausencia de matches. Los datos
incluyen fingerprint del motor y cinco repeticiones por consulta. No hay suite
concurrente durante este benchmark.

## Medición posterior a índices y optimizador (IR 1.81)

El artefacto más reciente de esa revisión es
[timings-ir181-indexed.json](timings-ir181-indexed.json), posterior a los informes
`optimized` y `final` (este último nombre no significa estado actual). Las 33
consultas completan en los tres repositorios. Se hicieron cinco repeticiones sin
suite concurrente; la suma de medianas por consulta es:

| Corpus | Consultas fuente actuales | Catálogo congelado sobre el mismo IR |
| --- | ---: | ---: |
| python-patterns, 35 archivos | 2.799 ms | 368 ms |
| cpp-patterns, 24 archivos | 1.222 ms | 194 ms |
| guru-rust, 35 archivos | 690 ms | 198 ms |

Se redujo el coste frente a la primera medición fuente de esta continuación
(9.932/9.658/6.132 ms). Las consultas congeladas y las actuales verifican contratos
diferentes; esta comparación no demuestra que el nuevo motor sea más rápido ni
mide precisión. Abstract Factory sigue siendo la consulta más costosa en Python
(1.023 ms). Estos números preceden a IR 1.82 y a las siguientes migraciones.


## Segundo corte de autoría (IR 1.82)

Se añadieron condiciones sobre valores capturados, transformaciones binarias con
orígenes por operando, `body linear`, alias de evidencia `Call`, campos efectivos
por identidad, inventarios de escritura por callable y selectores de exportación
y destino resuelto. El contrato de cada capacidad está en
[saved-body-execution.md](../../design/kql2/saved-body-execution.md).

Consultas revisadas en este corte:

- Adapter `class-adapter`: llamada al adaptee heredado sobre la propia instancia;
  otro receptor o código inalcanzable no satisfacen el algoritmo.
- Facade `module-surface`: exportación, subsistemas de tipos/módulos distintos,
  producción y consumo del mismo valor, sin seguir escrituras históricas.
- Decorator `typed-delegator`, `object-wrapper`, `result_forwarding`: actividad
  añadida en una misma ruta o transformación explícita del resultado delegado.
- Bridge `returned_primitive` y `refined-composition`: BODY y campo heredado
  resuelto por identidad; sombras y ambigüedad no se unen por nombre.
- Singleton `lazy_instance`: inicialización tras null-miss con recorrido lineal
  descrito, retorno del lugar compartido y una única escritura explícita.

Los 82 bloques restantes con operadores internos siguen siendo trabajo pendiente.
Los wrappers que usan una variante pendiente también dependen de esa migración.
`legacy_query` se inventaría por separado: que una consulta nueva use sintaxis
fuente no implica que todo el fichero esté libre de contenido legado.

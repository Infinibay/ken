# Bloqueos medidos — registro histórico (ninguna variante pendiente)

Estado: **registro histórico**. **No queda ninguna variante en `design`**: las 33 se
cerraron. Este archivo conserva las mediciones que costaron trabajo y las correcciones de
notas equivocadas, para quien retome las capacidades que quedaron sin modelar. Fecha: 2026-09-14. Base: IR 1.71.0, inventario **77 `ready` / 0 `design`**. Cada entrada trae la medición, el archivo y símbolo siguiente, y el
contraejemplo mínimo que la desbloquea.

## 0. Lo que este documento se equivocó, y por qué importa

La versión anterior de este archivo registraba `observer#event-bus` como
bloqueada porque "Java no tiene `operator[]` para `Map`" y hacía falta una forma
de API de mapa modelada. **Era falso.** La forma de método ya era expresable con
hechos existentes: el acceso es una llamada con `RECEIVER $registry` y el topic
como `ARGUMENT`, y el valor cargado se une con `ARGUMENT --VALUE-->
<loaded-value> --LOADED_FROM--> $topic`. Con eso la variante se cerró **sin
cambio de IR** (74 tests, ver
[`observer#event-bus`](observer-event-bus.md)), aceptando las dos formas de acceso
en una sola query.

El error de método fue razonar desde "el IR sólo emite `LOOKS_UP` desde la
sintaxis de índice" hacia "hace falta un modelo de API", en vez de **medir la
query**. Es la misma regla que ya estaba escrita en
[`adapter#class-adapter`](adapter-class-adapter.md): escribir la query y correrla
antes de asumir que falta análisis.

Un segundo error de la misma versión: se registró una "colisión de ids de entidad
`CALL`" que **no existe**. `entity()` incluye el byte final
(`{scope}/CALL:{name}@{start}:{end}`); lo que engaña es que el `name` de una
entidad `CALL` es su byte de **inicio**, así que dos llamadas distintas se
imprimen con el mismo número. Lección para los volcados: imprimir el **id**, no el
nombre, antes de diagnosticar un problema de identidad.

## `interpreter#expression-sum` y `composite#algebraic-tree` — cerradas

Las dos se cerraron con la forma **etiquetada**: ver
[`composite#algebraic-tree`](composite-algebraic-tree.md) y
[`interpreter#expression-sum`](interpreter-expression-sum.md). La codificacion de
suma **por casos** sigue sin modelarse y esta medición se conserva como contexto
histórico para quien la aborde.
## La codificación de suma por casos (contexto histórico)

**El contrato:** casos hoja y compuesto, payload de hijos recursivos y dispatch
por tag/match; la evaluación de cada hijo relacionada con el resultado combinado.

**Actualización (IR 1.70).** Se midió además la forma **etiquetada** —un tag de enum
más un tipo con campos recursivos (`kind`, `value`, `left`, `right`) y un método que
despacha sobre el tag y recurre por los dos campos— contra la query mínima de
`algebraic-tree`. Resultado: **las seis cierran** (2 matches cada una, las dos
permutaciones de los operandos) y hacía falta **un solo** arreglo de motor: en Rust el
campo `left: Box<Expr>` no producía `TYPE`, porque `normalized_type` despoja `&`/`*`
pero no conoce `Box`, y el `TYPE_HEAD` de la anotación genérica es `Box`, que no declara
nada. IR 1.70 hace que la grafía desenvuelta gane al head **sólo** cuando se desenvolvió
de verdad; con eso `TYPE left -> Expr` existe también en Rust.

Lo que **sigue faltando** para cerrar la variante no es el esqueleto —ya está en las
seis— sino la **evidencia de dispatch**: la ficha pide "dispatch por tag/match" y hoy no
hay ningún hecho que ligue el test del branch con el campo del tag (`TRUTH_TEST` está en
la lista de relaciones pero nada lo emite para estas formas; el `COMPARE` existe como
operación, sin operandos ligados). Sin eso, la query que cierra en las seis sólo prueba
"un tipo con dos campos de su propio tipo y un método que recurre por ambos", que es más
débil que la ficha. El subconjunto honesto que sí se podría publicar es eso; publicarlo
como `algebraic-tree` sería sobreafirmar, así que la variante sigue en `design`.

**Medición de las formas de suma reales** (enum de Rust, unión discriminada de
TypeScript, records de Java/C#, `std::variant` de C++):

| Lenguaje | Forma medida | Casos | Payload recursivo | Qué falta |
|---|---|---|---|---|
| java | `sealed interface` + `record` posicional | `SUBTYPE_OF Num/Add -> Expr` | ✗ los componentes del record no dan `HAS_FIELD`: el acceso es la **llamada** `add.left()` | modelar los componentes del record (o escribir el fixture con clases y campos) |
| csharp | `record` posicional | `SUBTYPE_OF` | ✗ `add.Left` es un `MEMBER` sin `TYPE` | ídem |
| go | `interface` + structs | `IMPLEMENTS Num/Add -> Expr {basis: method-set}` | parcial: `HAS_FIELD Add -> left/right`, sin `TYPE left -> Expr` | `TYPE` del campo al contrato |
| rust | `enum` + `match` | `IS Expr[CLASS]`, **sin casos** | ✗ las variantes no producen entidad ni hecho | variantes como tipos con campos + binding de patrón |
| typescript | unión discriminada | ✗ la unión no es un tipo | ✗ | miembros de la unión como tipos con campos |
| cpp | `std::variant` + structs | `HAS_FIELD Add -> left/right` pero sin vínculo a `Expr` | parcial | vínculo variante↔caso |

Lo que ya está en las seis: la **recursión** es visible (`CALLS` de la operación a
sí misma, dos veces, con el `ARGUMENT` correspondiente al operando: la llamada al
accesor en Java, el `MEMBER` en C#/Go/TS, el `STORAGE` del patrón en Rust, el
scrutinee en C++). Lo que falta en las seis, con distinta gravedad, es el **caso
como tipo con campos recursivos**: Java/C# lo tendrían escribiendo clases con
campos en vez de records posicionales, Go casi lo tiene, y Rust/TS/C++ necesitan
que el lenguaje de variantes se modele.

**Siguiente símbolo:** la rama que IR 1.58 agregó para enums (`ENUM_TYPES` /
`ENUM_CONSTANTS` y `enum_constant_names` en `src/ken/structural/frontend.py`),
extendida a `enum_variant` / `enum_variant_list` —una entidad por variante con sus
campos como `STORAGE` (`HAS_FIELD`) tipados por su declaración— más el binding de
patrón emitido desde el lowering de `match_pattern`/`tuple_struct_pattern`, y el
mismo tratamiento para los miembros de una `union_type` de TypeScript y para los
casos de un `std::variant`.

**Antes de tocar el frontend, cerrar `algebraic-tree` con cuatro lenguajes no es
una opción**: la variante declara seis. Pero sí conviene medir primero la query
contra la forma de **clases con campos** en java/csharp/go/cpp (donde el payload
recursivo sí es un campo) para fijar el contrato, y dejar Rust/TS como lo que la
capacidad nueva desbloquea.

## `proxy#remote-subject` (8 lenguajes) — el contrato sin nombres cierra en tres, JavaScript no tiene tipos de campo

**Medición nueva (misma sesión).** Se probó un contrato **sin tabla de nombres de API**,
que es la segunda alternativa que la ficha permite ("implementación local visible que
serializa la llamada y devuelve su respuesta"):

```
any { $unit SUBTYPE_OF $contract } or { $unit IMPLEMENTS $contract }
$unit HAS_FIELD $client;  $client TYPE $client_type;  different $client_type $contract
$unit HAS_METHOD $method; $method OVERRIDES $slot
$method HAS_CALL $transport;  $transport RECEIVER $client
$transport ARGUMENT $argument;  $argument VALUE $encoded;  $encoder RESULT $encoded
$method RETURNS_CALL $decoder;  different $transport $decoder
```

Cierra con **un match** en `python`, `java` y `go` **sin ningún cambio de motor**. Cada
cláusula se ganó midiendo: la unión `SUBTYPE_OF`/`IMPLEMENTS` porque Go satisface la
interfaz por method set; `$encoder RESULT $encoded` (no `$encoded VALUE $encoder`) porque
en la vista de query el valor de una llamada es su entidad `result`; y
`different $transport $decoder` porque sin ella la propia línea del decodificador se
colaba como transporte (Java daba 2 matches).

**Dónde se rompe: JavaScript.** El contrato necesita `$client TYPE $client_type` para
probar que el cliente **no** es el contrato local, y JavaScript no declara tipos de
campo: el `this.client = client` del constructor no produce `TYPE`. Sin esa cláusula la
variante aceptaría cualquier decorador con códec, y con ella JavaScript no puede
satisfacerla. Es el mismo muro que `abstract-factory#structural-families` encontró con
los objetos literales: en JavaScript el IR no tiene por dónde distinguir "el cliente es
otro contrato" sin una anotación.

**Siguiente símbolo:** dos caminos, y conviene medir cuál es honesto antes de tocar nada.
(a) Ligar el cliente a la **procedencia** de sus llamadas: el campo se asigna desde un
parámetro del constructor y ese parámetro se usa en un call site con un tipo declarado en
otro lenguaje no ayuda; en JavaScript haría falta modelar los **miembros de un objeto
literal** (el mismo hueco que dejó `abstract-factory#structural-families`), que es una
capacidad propia y más general. (b) Aceptar la forma sin la cláusula de tipo y reforzar
la serialización (p. ej. exigir que el argumento del transporte recorra un códec y que el
retorno recorra el decodificador **del mismo objeto**), declarando el límite; hay que
medir si eso sigue rechazando "HTTP helper sin contrato de subject", que es el
contraejemplo que la ficha nombra.

**Lo medido antes, que sigue valiendo:** un proxy mínimo sobre `requests`
(`requests.post(url, data=json.dumps(request))`) produce sólo una llamada de transporte
anónima con un códec anidado; nada marca la llamada como remota, así que una tabla de
nombres de API de transporte sería la otra vía, con ~40 entradas por lenguaje y el
problema de que el nombre del cliente viaja en el **receptor** (`requests`), no en
`CALLEE_NAME` (`post`), que es demasiado genérico por sí solo.

## Detalle del bloqueo anterior

**El contrato:** representación local del contrato remoto, operación RPC y
transformación de argumentos/resultado.

**Lo medido (Python).** Un proxy mínimo sobre `requests`:

```python
response = requests.post("http://example.invalid/api", data=json.dumps(request))
return json.loads(response.text)
```

produce `CALLEE_NAME -> post`, `RECEIVER -> requests`, `ARGUMENT` posicional 0
(la URL) y `ARGUMENT` nombrado `data` → la llamada a `dumps`, con
`CALLEE_VALUE -> dumps`. Es decir: un call anónimo de transporte y un códec
anidado, **sin modelo de "esto es remoto"**: nada distingue `requests.post` de
una llamada local cualquiera.

**Siguiente símbolo:** un modelo de transporte anclado por nombre, con el mismo
patrón que los códecs de `memento#serialized-snapshot` y que la forma
`collection-api-shape` de `INSERTS_INTO` (`src/ken/structural/frontend.py`, rama
de `ARGUMENT`): un conjunto de nombres por lenguaje (`requests.*`, `fetch`,
`axios.*`, `HttpClient`, `OkHttpClient`, `curl`, `resty`, `reqwest`) que emita
`REMOTE_CALL`/`TRANSPORT` sobre la llamada, más la transformación
argumento↔resultado. Es la variante con menos guía de diseño: la tabla de
`docs/design/structural/algorithms/proxy.md` sólo describe las formas
`guarded`/`lazy`, y la fila `remote` no tiene requisito particular escrito.

## Orden sugerido

**Ninguna.** `proxy#remote-subject` se cerró con el contrato sin nombres (ver
[`proxy#remote-subject`](proxy-remote-subject.md)); lo que sigue abierto es la capacidad de
**modelar los miembros de un objeto literal** de JavaScript, que ampliaría el contrato a la
forma no construida y desbloquearía también el proveedor de objeto literal de
`abstract-factory#structural-families`. El resto de lo medido aquí —la codificación de suma
por casos, la tabla de nombres de API RPC— no bloquea ninguna variante ya. Nota histórica: el
contrato sin nombres cerró en python, java y
go; lo que falta es decidir el camino para JavaScript, y las dos opciones están medidas
arriba (modelar los miembros de un objeto literal, o reforzar la serialización sin la
cláusula de tipo declarado y comprobar que sigue rechazando el "HTTP helper sin contrato
de subject" que la ficha nombra). La codificación de suma por casos (Rust enum, TypeScript discriminated union,
Java/C# records, `std::variant`) no bloquea ninguna variante ya: las dos que la
necesitaban se cerraron con la forma etiquetada, y queda como medición para quien quiera
ampliar el contrato a esa forma.

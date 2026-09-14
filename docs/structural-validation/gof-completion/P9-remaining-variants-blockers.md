# Bloqueos medidos de las dos variantes restantes

Estado: **registro de bloqueo**, no cierre. Quedan dos variantes en
`status = "design"`. Fecha: 2026-09-14. Base: IR 1.71.0, inventario 75 `ready` /
2 `design`. Cada entrada trae la medición, el archivo y símbolo siguiente, y el
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

## 1. `interpreter#expression-sum` (6 lenguajes) — cerrable por la forma etiquetada

**`composite#algebraic-tree` ya se cerró** (IR 1.70/1.71) con la forma etiquetada:
ver [`composite#algebraic-tree`](composite-algebraic-tree.md). Esta entrada queda para
su hermana, que comparte lenguajes y forma y añade el **contexto** de evaluación y la
**combinación** de los resultados de los dos operandos. La combinación es lo que
`expression-objects` deja declarado como no probado; si no hay flujo de valores para
probarla, se cierra con la parte que sí se pruebe y el límite escrito, como se hizo en
`singleton#once-primitive`.

## 1b. La codificación de suma por casos (contexto histórico)

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

## 2. `proxy#remote-subject` (8 lenguajes) — falta el modelo de transporte

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

1. Las **variantes de tipo suma** en Rust y TypeScript (más el vínculo
   variante↔caso en C++), que desbloquean **dos** variantes de una vez. El resto
   del contrato ya está medido: la recursión es visible en las seis formas.
2. `proxy#remote-subject`, que necesita el modelo de transporte.

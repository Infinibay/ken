# Bloqueos medidos de las tres variantes restantes

Estado: **registro de bloqueo**, no cierre. Quedan tres variantes en
`status = "design"`. Fecha: 2026-09-14. Base: IR 1.69.0, inventario 74 `ready` /
3 `design`. Cada entrada trae la medición, el archivo y símbolo siguiente, y el
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

## 1. `composite#algebraic-tree` e `interpreter#expression-sum` (6 lenguajes cada una)

**El contrato:** casos hoja y compuesto, payload de hijos recursivos y dispatch
por tag/match; la evaluación de cada hijo relacionada con el resultado combinado.

**Lo que sí existe (medido, Rust).** Con `enum Expr { Num(i32), Add(Box<Expr>,
Box<Expr>) }` y un `match`:

```
IS Expr[CLASS]
HAS_CALL evaluate -> <llamada>   CALLEE_NAME -> evaluate   (recursión)
ARGUMENT <llamada> -> left / right / ctx        (los bindings del patrón)
IS left[STORAGE]   IS right[STORAGE]
CALLS evaluate -> evaluate
```

**El bloqueo.** Las **variantes del enum no se modelan**: `enum_variant` aparece
como operación pero no produce entidades ni hechos, así que no hay tipo por caso
ni campo por payload. Y los bindings del patrón (`left`, `right`) son `STORAGE`
sin ninguna arista al enum, al scrutinee ni a la variante que los declara: no se
puede decir de qué caso salió cada hijo ni que `left` es el campo recursivo de
`Add`. Sin eso, `interpreter#expression-sum` no puede exigir "los dos operandos
del mismo caso" y `composite#algebraic-tree` no puede distinguir hoja de
compuesto.

**Siguiente símbolo:** la rama que IR 1.58 agregó para enums (`ENUM_TYPES` /
`ENUM_CONSTANTS` y `enum_constant_names` en `src/ken/structural/frontend.py`),
extendida a `enum_variant` / `enum_variant_list`: una entidad por variante con sus
campos como `STORAGE` (`HAS_FIELD`) tipados por su declaración, y una relación del
binding de patrón a la variante emitida desde el lowering de
`match_pattern`/`tuple_struct_pattern`.

**Ojo con el orden:** conviene medir primero si las dos variantes pueden
compartir una query. `expression-sum` pide además el **contexto** y la
**combinación** de los resultados de los dos operandos, que es justo lo que
`expression-objects` deja declarado como no probado; `algebraic-tree` sólo pide
el árbol y la ejecución recursiva. Si la combinación necesita flujo de valores
que no existe, `expression-sum` se cierra con la parte que sí se pruebe y el
límite escrito, como se hizo en `singleton#once-primitive`.

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

1. Las **variantes de tipo suma**, que desbloquean **dos** variantes de una vez y
   son la única familia que queda sin medición de query (sólo se midió el grafo).
   Antes de tocar el frontend, escribir la query de `composite#algebraic-tree`
   contra el grafo actual para ver exactamente qué cláusula falta.
2. `proxy#remote-subject`, que necesita además el modelo de transporte.

# Bloqueos medidos de las cuatro variantes restantes

Estado: **registro de bloqueo**, no cierre. Las cuatro variantes siguen en
`status = "design"`. Fecha: 2026-09-14. Base: IR 1.69.0, inventario 73 `ready` /
4 `design`. Cada entrada trae la medición, el archivo y símbolo siguiente, y el
contraejemplo mínimo que la desbloquea.

## 1. `observer#event-bus` (8 lenguajes) — dos formas de acceder al registro

**El contrato que pide la ficha:** relacionar el alta del subscriber con la
publicación sobre el **mismo bus/topic**, con callback y payload. El diseño es
explícito: "en un registro filtrado por topic debe preservarse la relación entre
topic del alta y el topic del publish; que ambas operaciones tengan una cadena no
alcanza".

**Lo que sí existe (medido, Go).** Con un registro indexado por un campo topic:

```
WRITES_ELEMENT <assign de b.handlers[b.topic]>  -> handlers
INDEX          <assign>                          -> topic
LOOKS_UP       <método Suscribe/Publish>         -> handlers
CONTAINER      <acceso b.handlers[b.topic]>      -> handlers
INDEX          <acceso>                          -> topic
ITERATED_CALL  <llamada handler(payload)>        -> <acceso>
ITERATION_INVOKES_VALUE <for_statement>          -> <llamada>
```

Las dos aristas `INDEX` apuntan al **mismo** `STORAGE:topic`, así que la
identidad del topic se une por identidad y no por nombre. La query es escribible
con lo que hay.

**El bloqueo.** Esa evidencia sólo la produce la **sintaxis de índice**:
`LOOKS_UP`, `WRITES_ELEMENT`, `CONTAINER` e `INDEX` se emiten en la rama `INDEXES`
de `Lowerer.assign`/`Lowerer.value` (`src/ken/structural/frontend.py`, el bloque
que empieza en `if kind in INDEXES:` hacia la línea 1471). Java **no tiene
`operator[]` para `Map`**: medido con

```java
handlers.computeIfAbsent(topic, key -> new ArrayList<>()).add(handler);
...
List<Consumer<String>> bucket = handlers.get(topic);
for (Consumer<String> handler : bucket) { handler.accept(payload); }
```

el grafo da `CALLEE_NAME 487 -> get`, `RECEIVER 487 -> handlers`,
`ARGUMENT 487 -> topic`, y **ningún** `LOOKS_UP`/`CONTAINER`/`INDEX`; la
iteración es sobre el **local** `bucket` (`ITERATED_CALL 608 -> bucket`), no sobre
el acceso. El enlace local↔llamada sí existe (`ASSIGNED_FROM bucket -> 487`).

**Siguiente símbolo:** una forma de API de mapa modelada, en la línea de
`name in {"append","add","push","push_back","Add"}` que ya produce `INSERTS_INTO`
con `model="collection-api-shape"` (`src/ken/structural/frontend.py`, rama de
`ARGUMENT`). Debe cubrir, por lenguaje, la lectura y la escritura: Java
`Map.get`/`put`/`computeIfAbsent`, Rust `HashMap::get`/`insert`/`entry`, C#
`TryGetValue`/`Add`, Python `dict.get`/`setdefault`, JS `Map.get`/`set` — y emitir
`LOOKS_UP`/`WRITES_ELEMENT` + `INDEX` con el mismo argumento/índice que ya usa la
forma de subíndice, para que la query sea una unión de dos formas y no ocho.

**Obstáculo transversal que hay que resolver antes o a la vez:** los ids de
entidad `CALL` se indexan por el **byte de inicio** de la llamada
(`self.entity("CALL", str(node.start_byte), ...)`), así que dos llamadas anidadas
que comparten inicio **colisionan**. Medido en Python y Java:

```
self.handlers.setdefault(self.topic, []).append(handler)
  HAS_CALL subscribe -> 139 (append)
  HAS_CALL subscribe -> 139 (setdefault)     ← misma entidad
  RECEIVER 139 -> 139                        ← el append se apunta a sí mismo

handlers.computeIfAbsent(topic, ...).add(handler)
  HAS_CALL subscribe -> 333 (add)
  HAS_CALL subscribe -> 333 (computeIfAbsent)
  RECEIVER 333 -> 333
```

Mientras eso no se arregle (incluir el byte final en el id, con el coste de
cambiar todos los ids de llamada y cualquier test que los afirme), los fixtures
deben esquivar la forma anidada `x.f(...).g(...)`.

## 2. `composite#algebraic-tree` y `interpreter#expression-sum` (6 lenguajes cada una)

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

**Siguiente símbolo:** la rama que IR 1.58 agregó para enums
(`ENUM_TYPES`/`ENUM_CONSTANTS` y `enum_constant_names` en
`src/ken/structural/frontend.py`), extendida a `enum_variant` /
`enum_variant_list`: una entidad por variante con sus campos como `STORAGE`
(`HAS_FIELD`) tipados por su declaración, y una relación del binding de patrón a
la variante (`<binding> PATTERN_OF <variante>` o equivalente) emitida desde el
lowering de `match_pattern`/`tuple_struct_pattern`.

## 3. `proxy#remote-subject` (8 lenguajes) — falta el modelo de transporte

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
una llamada local cualquiera, y `$unit` no tiene por dónde unirse al contrato
local que representa.

**Siguiente símbolo:** un modelo de API de transporte anclado por nombre, con el
mismo patrón que los códecs de `memento#serialized-snapshot` y que la forma
`collection-api-shape`: un conjunto de nombres por lenguaje (`requests.*`,
`fetch`, `axios.*`, `HttpClient`, `OkHttpClient`, `curl`, `resty`, `reqwest`) que
emita `REMOTE_CALL`/`TRANSPORT` sobre la llamada, más la transformación
argumento↔resultado. Es la variante con menos guía de diseño en las fichas: la
tabla de `docs/design/structural/algorithms/proxy.md` sólo describe las formas
`guarded`/`lazy`, y la fila `remote` no tiene requisito particular escrito.

## Por qué no se cierran ahora

Las tres familias necesitan una capacidad nueva cada una (forma de API de mapa,
variantes de tipo suma, modelo de transporte), y las tres tocan
`src/ken/structural/frontend.py`. El orden sugerido es: primero el id de `CALL`
(colisión, transversal y hoy silencioso), después la forma de API de mapa
(`observer#event-bus`, 8 lenguajes, la más cercana: la forma de subíndice ya
funciona en Go y la query sólo necesita la unión), y después las variantes de tipo
suma, que desbloquean **dos** variantes de una vez.

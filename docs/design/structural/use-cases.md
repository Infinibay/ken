# Casos de uso y consultas que ponen a prueba el diseño

Estado: diseño; KenQL propuesto, no ejecutado. Volver al [índice](README.md).

## 1. Un Iterator no tiene un único grafo

Estos dos programas Python completos ilustran recorridos con grafos diferentes:

```python
def generated(xs):
    for x in xs:
        yield x

class Cursor:
    def __init__(self, xs):
        self.xs = xs
        self.position = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.position >= len(self.xs):
            raise StopIteration
        value = self.xs[self.position]
        self.position += 1
        return value
```

| Variante | Evidencia de IR | Hechos que no se exigen |
|---|---|---|
| Generador | callable → operación yield → elemento; loop y resume | Clase Cursor, campo position, método next |
| Cursor explícito | protocolo, lectura/escritura del progreso, fin, retorno de elemento | Sintaxis yield |
| Delegación | yield_delegate → iterable delegado | Bucle escrito a mano |
| Función iteradora | callback yield recibe elemento y su booleano gobierna continuidad | Objeto con método next |

La regla `gof.iterator` contiene varias variantes, cada una con sus requisitos.
Una coincidencia dice cuál encontró. No se «traduce» el generador a una clase
imaginaria para forzarlo a satisfacer la variante de cursor.

Consulta de la **forma generadora**, deliberadamente sin probar corrección:

```kenql
query generator_shape {
  callable(generator: true) as $iterator;
  any {
    operation(kind: yield) as $suspend;
  } or {
    operation(kind: yield_delegate) as $suspend;
  }
  require $iterator HAS_OPERATION $suspend;
  emit $iterator;
}
```

La variante de protocolo añade consumo o conformidad al protocolo. Un async
generator pertenece a otra variante con su propio protocolo de consumo. Un yield
nativo no modelado no se borra: da cobertura incompleta de esa variante.

## 2. Builder mutable e inmutable

Programa Python completo de ambas formas:

```python
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class Request:
    url: str
    timeout: int

class MutableRequestBuilder:
    def __init__(self):
        self.url = "/"
        self.timeout = 30

    def with_url(self, url):
        self.url = url
        return self

    def build(self):
        return Request(self.url, self.timeout)

@dataclass(frozen=True)
class ImmutableRequestBuilder:
    url: str = "/"
    timeout: int = 30

    def with_url(self, url):
        return replace(self, url=url)

    def build(self):
        return Request(self.url, self.timeout)

mutable = MutableRequestBuilder().with_url("/users").build()
immutable = ImmutableRequestBuilder().with_url("/users").build()
```

Mutable: argumento de `with_url` → escritura de campo → lectura en `build` →
argumento de construcción de `Request`. Inmutable: valor builder anterior → nuevo
builder modificado → lectura en `build` → producto. `replace` necesita un modelo de
API, o queda una llamada opaca; no se infiere su semántica por el nombre.

Consulta conceptual de la variante mutable, usando vistas de callable `WRITES` y
`READS` y retorno de tipo construido:

```kenql
query mutable_builder {
  type_decl() as $builder;
  require $builder HAS_METHOD $step;
  require $builder HAS_METHOD $finish;
  different $step $finish;
  require $builder HAS_FIELD $state;
  require $step WRITES $state;
  require $finish READS $state;
  require $finish HAS_OPERATION $construction;
  operation(kind: construct) as $construction;
  require $construction RESULT $created;
  require $finish RETURNS_VALUE $created;
  require $created INSTANCE_OF $product;
  require $construction ARGUMENT $argument;
  require $argument VALUE $input;
  operation(kind: load) as $read;
  require $finish HAS_OPERATION $read;
  require $read READS $state;
  require $read RESULT $loaded;
  path $loaded VALUE_FLOW{0,6} $input as $flow;
  emit $builder, $finish, $product;
}
```

La operación de construcción queda ligada al valor realmente devuelto. Así, un
objeto auxiliar construido en `build` no sirve como falso producto. Esta variante
cubre retorno directo; si hay phi o transformación intermedia hace falta otra
variante con flujo de retorno contextual. La consulta exige relación de datos, pero
no demuestra que el método de paso se haya invocado antes en toda ejecución.

Rust consuming builders añaden move/retorno por valor; typestate añade sustitución
de `Builder<Missing>` a `Builder<Ready>`. El nombre «Builder» no es una condición.
Un método que actualiza un objeto persistente puede compartir forma; el resultado
sigue siendo evidencia de construcción, no intención probada.

## 3. «Qué directorios concentran factories»

Ejecutar la colección de construcción y luego agrupar **coincidencias**, sin cambiar
el IR por carpeta. El usuario elige unidad de medición: archivo, tipo o callable.

Ejemplo de salida de diseño:

| Directorio | Tipos analizables | Tipos con rol principal factory | Cobertura | Lectura |
|---|---:|---:|---|---|
| `src/factories` | 12 | 10 | 12/12 archivos | 83% de tipos con evidencia de factory |
| `src/builders` | 8 | 0 | 8/8 archivos | Consultar Builder por separado |
| `plugins` | 20 conocidos | 3 | 6 archivos omitidos | Proporción total desconocida |

«Solo hay factories» requiere definir qué se cuenta, revisar los no coincidentes
y tener cobertura suficiente. Un archivo factory puede contener utilidades; los
roles secundarios no convierten todo el directorio en factories. Si no hay tipos
analizables, el porcentaje es `null`, nunca 100%. Un patrón con tres variantes
satisfechas cuenta una vez para el mismo rol principal.

La agrupación recursiva debe ser explícita. Cambiar denominador de archivos a tipos
no es una presentación inocua: cambia la afirmación. Conservar numerador,
denominador, exclusiones y ejemplos no coincidentes.

## 4. APIs exportadas y uso de argumentos

```kenql
query exported_debug_argument {
  module() as $module;
  callable() as $api;
  require $module EXPORTS $api;
  require $api HAS_PARAMETER $parameter;
  parameter(name: /^debug$/i, type_family: boolean) as $parameter;
  emit $module, $api, $parameter;
}
```

Esto es una convención de equipo, no un bug universal. Reexports deben conservar
el camino de exposición. Python `__all__`, exports ES y accesibilidad Java/C# tienen
modelos distintos. No asumir que todo nombre público se exporta a todos los clientes.

Para encontrar llamadas que fijan el parámetro por keyword o posición, consultar
argument_occurrence → BINDS_TO → parameter. Mirar solamente el segundo argumento
fallará con argumentos nombrados, defaults, `*args` y `**kwargs`.

## 5. Default mutable

Fuente:

```python
def append_item(item, items=[]):
    items.append(item)
    return items
```

Plan de consulta: parameter → default expression → valor mutable; fase de
evaluación `definition`; una llamada escribe un lugar alcanzable desde ese valor.
La forma de default mutable ya es una advertencia útil; demostrar mutación da una
variante más específica. La regla no debe ser un `if language == python` dentro
del buscador: la fase de evaluación viene del adaptador del lenguaje.

Negativos: `items=None` con lista nueva por llamada; default inmutable; función
JavaScript cuyo `items=[]` se evalúa al invocar. Desconocido: default que llama una
factory sin resumen de mutabilidad. La recomendación puede sugerir sentinel, pero
no aplicar un fix automático sin analizar el contrato.

## 6. Recurso y generador

```python
def lines(path):
    with open(path) as f:
        for line in f:
            yield line
```

Un escaneo textual puede señalar «yield con archivo abierto», pero el contexto
permanece activo durante la suspensión. La consulta útil distingue: suspensión con
recurso retenido, escape del generador y cierre eventual desconocido. No debe
llamar fuga confirmada al patrón anterior por sí solo.

Otra forma retorna un generador que usa un archivo ya cerrado:

```python
def broken_lines(path):
    with open(path) as f:
        return (line for line in f)
```

La evidencia relevante es captura del recurso por ejecución diferida, salida del
scope y consumo posterior; exige modelo de generator expression y context manager.
Para un generador C#, usar su modelo de `using` y disposición, no copiar las reglas
Python palabra por palabra.

## 7. Threads, tareas y joins

Casos que deben producir resultados distintos:

```python
from threading import Thread

def start_worker(work):
    thread = Thread(target=work)
    thread.start()
    return thread

def wait_worker(work):
    thread = start_worker(work)
    thread.join()
```

`start_worker` devuelve ownership práctico del handle al llamador. No tiene join
local; eso no demuestra abandono. `wait_worker` espera sin timeout; un `join(0.01)`
solo espera hasta un plazo y debe conservar `may_complete`. Una llamada a `start()`
de una clase de negocio no genera `CREATES_CONTEXT`.

Para encontrar posibles accesos concurrentes: resolver el mismo lugar abstracto,
al menos una escritura, contextos que pueden solaparse, falta de orden conocido y
protecciones analizadas. «Falta de lock visible» no prueba una carrera. Accesos
atómicos, locks por alias, canales y ownership pueden establecer seguridad o dejar
el resultado indeterminado.

En async, llamar coroutine, programarla y esperarla son acciones distintas. Una
llamada dentro de un cuerpo async puede bloquear; se necesita un modelo de API
bloqueante para proponer `blocking-in-async`, con evidencia de ejecución en ese
contexto y no dentro de un callback enviado a un executor.

## 8. Taint y consultas de flujo

Caso: entrada de usuario → concatenación → SQL. La consulta necesita source,
transferencias, sink y sanitización **específica de contexto**. Escapar HTML no
sanitiza SQL. Una llamada parametrizada puede ser un negativo aunque reciba el
mismo valor externo. `VALUE_FLOW` solo cubre transferencia; `DATA_DEPENDS_ON` con
modelos de transformación expresa contaminación.

No prometer análisis de taint completo en la primera entrega. Requisitos de una
variante útil: campo sensible, source/sink resueltos, callsite context, caminos
factibles o marcado explícito de aproximación, test de sanitizador equivocado y
escape fuera del scope. Los modelos se guardan fuera del matcher y se versionan.

## 9. Más bibliotecas sobre las mismas primitivas

| Consulta/regla | Evidencia requerida | Contraejemplo o límite |
|---|---|---|
| Return en finally | CFG de return/exception sustituido por finally | No todos los returns son un bug intencionalmente |
| Código inalcanzable | Terminador y control del bloque | Función anidada no ejecutada no pertenece al flujo padre |
| Self-assignment | Identidad de storage y ausencia de efecto especial | Setter sobrecargado puede tener efectos |
| Doble liberación | Identidad de recurso, caminos y lifecycle | Dos handles no necesariamente mismo recurso |
| Uso tras close | Valor capturado, close dominante y uso | Reapertura o ownership transferido |
| Locks en orden inverso | Adquisiciones correlacionadas y contextos solapables | Un mismo thread sin concurrencia no prueba deadlock |
| Await con lock retenido | Lock activo en punto de suspensión | Lock async cooperativo cambia la interpretación |
| Callback no desuscrito | Registro, escape de lifetime, cierre de dueño | Suscripción de vida global puede ser intencional |
| Memento con alias mutable | Snapshot comparte storage mutable con originador | Copy-on-write modelado puede ser seguro |
| Builder ignora resultado inmutable | Retorno builder sucesor descartado y uso del anterior | Método con efectos adicionales o intención de descartar |
| Factory rompe contrato | Tipo de producto incompatible con slot | Anotación incompleta o conversión modelada |
| Dependency inversion | Dependencia/import a implementación desde capa definida | Necesita configuración de capas del equipo |
| Código duplicado estructural | Operaciones normalizadas y bindings renombrados | Duplicación no demuestra conveniencia de extraer |
| N+1 consultas | Llamada I/O en iteración sobre resultados | Batching/prefetch o colección acotada |
| Cache sin cota | Inserción por clave y retención persistente | Evicción fuera del archivo analizado |
| Retry no acotado | Ciclo, error y ausencia de salida demostrable | Política externa o cancelación |

Cada regla usa el mismo formato de fichero, roles y evidencia. Puede pertenecer a
más de una colección, por ejemplo `architecture` y `correctness`.

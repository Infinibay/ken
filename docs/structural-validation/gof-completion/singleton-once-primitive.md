# `singleton#once-primitive` (5 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **cinco** lenguajes declarados
(`java`, `csharp`, `cpp`, `go`, `rust`).
Fecha: 2026-09-14. Base: IR 1.66.0 (`memento#serialized-snapshot`), IR 1.67.0.

## Qué se publica

Una **celda compartida de una API de inicialización única** recibe un *thunk* que
construye un tipo, y el accessor devuelve el valor retenido por esa misma celda. La
identidad de la celda y la del valor son las dos juntas:

```
%accessor --HAS_CALL--> call --ARGUMENT--> <argument/0> --VALUE--> thunk
%thunk    --HAS_CALL--> construction --ALLOCATES_TYPE--> %type
%celda    --DECLARES--  por el módulo (o `static: true`)
```

Cinco APIs estándar, y ninguna se reduce a "llama una vez":

| Lenguaje | Celda | Transferencia del valor |
|---|---|---|
| Go | `sync.Once` | el thunk **publica** un slot del módulo que el accessor devuelve |
| C++ | `std::once_flag` | el thunk publica un slot `static` que el accessor devuelve |
| Rust | `OnceLock` | el accessor devuelve **la llamada** `get_or_init` |
| Java | `AtomicReference` | el accessor devuelve **la llamada** `updateAndGet` |
| C# | `Lazy<T>` | el accessor devuelve un **miembro** de la celda (`Value`) |

C++ es la forma que obligó a medir: `std::call_once` es una **función libre**, así que la
celda llega como **primer argumento** y no como receptor. El `or` de la query cubre las
dos colocaciones. C# es la otra: la celda se **construye a partir** del thunk
(`new Lazy<Service>(() => new Service())`), así que la llamada no es la que hace el
accessor sino la que asigna la celda.

## El defecto real que había debajo (Go)

La variante entera se escribe con hechos que ya existían **salvo uno**, y el que faltaba
no era una capacidad exótica sino un defecto de atribución:

```go
var shared *Config
var guard sync.Once

func current() *Config {
    var guard sync.Once          // nueva en cada invocación
    guard.Do(func() { shared = &Config{value: 1} })
    return shared
}
```

Antes de IR 1.67 existía **una sola** entidad `STORAGE:guard`: el `var` local no bajaba
como declaración, así que la lectura resolvía hacia fuera al slot del módulo y la guarda
local compartía el conjunto de escrituras de la compartida. La query no podía rechazar
"guarda nueva cada vez".

El modo `shadowed-guard` de los tests es exactamente esa forma (declaración de fichero
**más** declaración local de la misma grafía) y es la que mide el arreglo: con el motor
anterior al commit, **2 de los 40** tests fallan —
`test_negative_shapes_are_rejected[go-shadowed-guard]` y
`test_a_function_local_var_is_not_the_module_slot`. El modo `local-guard`, que declara
la guarda local sin una de fichero del mismo nombre, no distinguía nada: sin binding
previo, la lectura ya creaba un slot del callable. `

Go es el único lenguaje analizado cuyo nodo de declaración **es** la asignación (el nombre
vive en un `var_spec` hijo), así que nunca quedó cubierto por el camino de declaraciones
de bloque que usan `let` de JS/TS, `local_variable_declaration` de Java y
`variable_declaration` de C#. IR 1.57 había bajado el `var` de ámbito de fichero para que
las lecturas dentro de un callable lo resolvieran, y el `var` local se fue con él.

## Por qué el slot también tiene que ser compartido

En Go y C++ la guarda y el valor son **dos** entidades, y las dos tienen que serlo. Con
solo la celda compartida, esto pasaba:

```go
var guard sync.Once

func current() *Config {
    var shared *Config            // nuevo en cada invocación
    guard.Do(func() { shared = &Config{value: 1} })
    return shared
}
```

La primera invocación inicializa el slot local; las siguientes no vuelven a entrar al
thunk y devuelven `nil`. La query exige, en la rama de slot, `$module DECLARES $slot` o
`variable(static: true)`; los dos negativos locales están en la matriz.

## El tipo declarado del slot sí se comprueba (Go y C++)

En Go y C++ el slot lleva su tipo nominal (`TYPE shared -> Config`), así que la rama lo
une con el tipo que construye el thunk: un slot `*Config` inicializado con `Other` no
matchea. En Rust, Java y C# el tipo retenido vive en el **argumento de tipo** de la celda
(`OnceLock<Config>`, `AtomicReference<Config>`, `Lazy<Config>`), que el IR no publica como
relación, así que ahí la identidad del tipo la da solo la construcción del thunk. Está
declarado en el `query_claim`, no escondido.

## Lo que se dejó sin resolver a propósito

* **Reset.** Una escritura posterior del valor retenido (o una reasignación de la celda)
  no se rechaza. Para Go y C++ el `BINDING_WRITE_COUNT` del accessor no existe: el
  accessor **posee** el thunk, y el pase de escrituras marca ese ámbito como
  `control-or-dynamic-scope` (`unsupported`) porque un callable anidado puede capturar y
  reasignar los bindings. Sin recuento no hay forma de decir "una sola escritura", así que
  el test `test_a_later_write_of_the_retained_value_is_not_yet_rejected` **fija** el
  match en vez de afirmar una garantía que el contrato no da. Es el mismo límite que
  `module-shared` declara ("nunca repetida por otro escritor fuera del grafo analizado").
* **Hilos, reentrada, fallo del inicializador.** El IR no modela memoria ni cancelación.
* **Umbral de la API.** El ancla es la forma de la llamada (receptor o primer argumento,
  más un thunk que construye), no un nombre de API de una lista. Un método homónimo sobre
  una celda compartida con un thunk que construye matchea; la ficha lo acepta porque la
  identidad de la celda y del slot es lo que se prueba, no el nombre.

## Validación

* `tests/structural/test_singleton_once_primitive.py`: 40 tests. Positivo y renombrado en
  los cinco lenguajes; **cinco** negativos por lenguaje en Go y C++ (`local-guard`,
  `shadowed-guard`, `local-slot`, `crossed`, `fresh`), tres en Rust, C# y Java (`local`,
  `crossed`, `fresh`); un test de frontera del reset en los cuatro lenguajes donde se
  puede escribir; la consulta raíz `singleton` en los cinco; la comprobación de alcance
  de Go.
* Suite estructural completa: **7194 passed / 140 xfailed** (antes: 7153 / 140; los 41
  nuevos son los 40 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`).
* `mypy src/ken`: limpio (109 ficheros).
* Medición del cambio de motor: con el catálogo nuevo y el frontend anterior, **2 de los
  40** tests fallan (`[go-shadowed-guard]` y el de alcance). El fichero completo **no
  corre** contra el catálogo anterior: la variante es `design` y `named_rule` no la
  registra, así que ahí la medición informativa es el falso positivo, y es la de arriba.

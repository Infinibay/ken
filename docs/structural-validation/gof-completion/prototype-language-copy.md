# `prototype#language-copy` (5 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **cinco** lenguajes declarados.
Fecha: 2026-09-14. Base: `d01ad5b` (IR 1.59.0), IR 1.60.0.

## Qué la separa de sus tres vecinas

Las tres variantes `ready` de Prototype describen una copia **escrita a mano**: un
campo homónimo copiado (`field-copy`), una construcción explícita que recibe estado de
la instancia (`explicit-copy`), o un `derive` de Rust (`derived-clone`).

`language-copy` es la otra mitad de la ficha —*resolver protocolo, constructor de copia
o derive*—: la copia la produce **el mecanismo propio del lenguaje**. Y ese mecanismo
es distinto en cada una de las cinco lenguas declaradas:

| Lenguaje | Forma | Señal |
|---|---|---|
| Python | `copy.deepcopy(self)` | `CALLEE_NAME deepcopy` |
| Java | `(Config) super.clone()` | `CALLEE_NAME clone` |
| C# | `this.MemberwiseClone()` | `CALLEE_NAME MemberwiseClone` |
| C++ | `Config(const Config&)` | constructor de aridad 1 con parámetro del propio tipo |
| Rust | `fn clone(&self) -> Self` | método `clone` que devuelve una construcción del propio tipo |

Buena parte de esto no necesitó nada nuevo: la delegación a primitiva es una llamada
cuyo nombre es el de la API estándar (el catálogo ya identifica protocolos por nombre
—`__iter__`, `next`, `hasNext`— y la ficha de Iterator dice que son "evidencia
intencional de API"), y el constructor de copia se reconoce porque el parámetro tiene
`TYPE` a la propia clase.

## Dos falsos positivos, medidos y cerrados

La primera versión de la query los tenía ambos. No se documentaron: se arreglaron.

### 1. Un constructor de movimiento no es un constructor de copia

`Config(Config&&)` matcheaba, porque el tipo del parámetro resuelve a `Config` igual
que en la copia. Nada más los distinguía: mismo nombre, misma aridad, mismo `TYPE`.

Ese "nada más" es literal — la única diferencia está en la grafía del declarador. Se
añadió `reference_kind` al parámetro (`lvalue` para `&`, `rvalue` para `&&`, ausente
por valor) y la rama exige `lvalue`. Eso excluye también `Config(Config)`, que tampoco
es el constructor de copia.

Que haga falta un atributo para esto es en sí el hallazgo: dos protocolos distintos
del lenguaje se veían idénticos en el grafo.

### 2. Un `clone` que devuelve un valor fresco no copia

```rust
fn clone(&self) -> Config { Config { value: 0 } }
```

Devolver una instancia nueva del tipo **no** es copiar el receptor. La rama exigía
"método llamado `clone` que devuelve una construcción del propio tipo", y eso lo
satisface. Ahora exige además que la construcción se inicialice desde un campo de ese
tipo (`HAS_INITIALIZER` → `STORES_VALUE` → un `HAS_FIELD` de la unidad), que es lo que
convierte una construcción en una copia.

Es el mismo error conceptual que la variante vecina `explicit-copy` ya evitaba con su
propia cadena de transferencia.

## Negativos cubiertos

19 pruebas en `tests/structural/test_prototype_language_copy.py`:

| Negativo | Por qué se rechaza |
|---|---|
| devolver el propio receptor (alias) | no hay copia |
| devolver una instancia fresca (Python/Java/C#) | no hay mecanismo de copia ni lectura del receptor |
| constructor con otro tipo de parámetro (C++) | el parámetro no es del propio tipo |
| **constructor de movimiento** (C++) | `reference_kind` es `rvalue`, no `lvalue` |
| **constructor por valor** (C++) | sin `reference_kind`: no es una referencia |
| método con otro nombre (Rust) | no es el método del trait `Clone` |
| **`clone` que devuelve un valor fresco** (Rust) | la construcción no se inicializa desde un campo del tipo |

## Límites declarados

La identificación del protocolo es **por nombre de API**: `copy`, `deepcopy`, `clone`,
`MemberwiseClone`. Es evidencia de forma, no resolución de biblioteca, y una función
de usuario con ese nombre contaría. Es la misma concesión que el resto del catálogo
hace con los nombres de protocolo.

**La profundidad no se resuelve**, y es deliberado: una copia somera y una profunda son
indistinguibles con estos hechos, y por eso las tres formas comparten una sola variante
en vez de una cada una. Los alias internos desconocidos no se registran.

## Validación

`tests/structural/` completo, sin regresiones, más las 19 pruebas nuevas.
`mypy src/ken` limpio.

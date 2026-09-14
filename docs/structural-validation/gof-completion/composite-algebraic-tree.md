# `composite#algebraic-tree` (6 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **seis** lenguajes declarados
(`typescript`, `java`, `csharp`, `cpp`, `go`, `rust`). Fecha: 2026-09-14.
Base: IR 1.70.0 (`singleton#once-primitive`… IR 1.70), IR 1.71.0.

## Qué se publica

Un tipo **etiquetado** sin interfaz ni clase base, con dos operandos recursivos y una
operación que despacha por el tag y recurre por los dos:

```
struct Expr { kind: Kind, value: i32, left: Box<Expr>, right: Box<Expr> }
if self.kind == Kind::Num { return self.value; }
self.left.evaluate() + self.right.evaluate()
```

Tres hechos, y el tercero es el que separa esta variante de `recursive-nominal` (que
prueba la llamada recursiva uniforme pero no el despacho):

| Rol | Hecho |
|---|---|
| Operandos recursivos | `$unit HAS_FIELD $first/$second` y `$first TYPE $unit`, `$second TYPE $unit`, distintos |
| Recursión uniforme | `$operation HAS_CALL $first_call` con `RECEIVER $first` y `where $operation.name == $first_call.name`, ídem el segundo |
| Dispatch | `$operation HAS_OPERATION $branch`, `operation(kind: branch)`, `$branch TRUTH_TEST $tested`, y `$tested` es un campo del mismo tipo |

La última cláusula tiene tres formas porque el campo probado se escribe de tres maneras:
el campo pelado (`kind` en java/cpp), `self.`/`this.` (rust/typescript, unido por
`MEMBER_OF` + `INSTANCE_RECEIVER`) o el receptor del método (`e.kind` en go, unido por
`HAS_PARAMETER` con `receiver: true`).

## Las dos capacidades que faltaban

**IR 1.70 — los envoltorios de propiedad de Rust denotan su payload.** `Box<Expr>`,
`Rc<Expr>` y `Arc<Expr>` no producían `TYPE`: `normalized_type` despoja `&`/`*`/`mut`
pero no conoce `Box`, y el `TYPE_HEAD` de la anotación genérica es el *head* (`Box`), que
no declara nada. Ahora la grafía desenvuelta gana al head **sólo** si se desenvolvió, lo
que deja `Vec<Expr>` en su camino de elemento y conserva la lectura de celda de
`OnceLock<T>`; el desenvoltorio está guardado por lenguaje.

**IR 1.71 — una rama de comparación publica el valor que discrimina.** `TRUTH_TEST`
existía para un test pelado (`if value`), donde el valor probado es la condición misma.
Una **comparación** tiene otra forma: la condición no es el valor discriminado, así que
no se publicaba nada y la query sólo podía preguntar "este callable contiene una rama".
Ahora `if kind == Num` publica `TRUTH_TEST` sobre `kind`. Se ofrecen los dos lados y sólo
se publican los que denotan un slot (`STORAGE` o `MEMBER`); **no se afirma polaridad**,
porque qué brazo elige una comparación no es la verdad del valor. Una comparación contra
un literal nulo queda **excluida**: esa forma ya publica `NULL_TEST` con su polaridad, y
emitir las dos hacía que la rama llevara **dos pares de brazos** (28 tests de
`test_negated_null_tests.py` lo detectaron). El `if` de Rust es un `if_expression`, así
que el manejo de ramas cubre las dos grafías: sin eso Rust no publicaba ningún
`TRUTH_TEST` y la evidencia de dispatch faltaba justo en uno de los seis.

## Lo que se dejó sin resolver a propósito

* **Codificación por casos.** El contrato es la forma **etiquetada**. La suma real
  —variantes de un `enum` de Rust, unión discriminada de TypeScript, records de Java/C#,
  casos de un `std::variant`— **no** se acepta: sus casos no se modelan como tipos con
  campos, y la medición está en
  [bloqueos medidos](P9-remaining-variants-blockers.md). Eso significa que
  `interpreter#expression-sum`, cuya ficha habla de "enum/sum type de constantes", puede
  cerrarse por esta misma forma (es la que usa el nombre), pero un árbol escrito con
  `enum Expr { Num(i32), Add(...) }` y `match` no matchea.
* **Valores del tag.** No se prueba que sean distintos entre ramas, ni que las ramas sean
  exhaustivas, ni que la rama hoja no recurra.
* **Reasignación.** Nada impide que los operandos se reasignen antes de la llamada
  recursiva.
* **Alcance por lenguaje.** Los seis son los validados; la query no filtra por lenguaje.

## Validación

* `tests/structural/test_composite_algebraic_tree.py`: 49 tests. Positivo y renombrado en
  los seis lenguajes, cuatro negativos por lenguaje (`no-tag-field`, `one-operand`,
  `foreign-operation`, `no-branch`), la consulta raíz `composite` en los seis, la
  comprobación de que el positivo publica dos `TRUTH_TEST` y que sin rama no matchea, y
  los metadatos.
* Suite estructural completa: **7501 passed / 140 xfailed** (antes: 7451 / 140; los 50
  nuevos son los 49 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`). Los 28 fallos intermedios de `test_negated_null_tests.py` fueron el
  aviso de la exclusión del nulo, no una expectativa acomodada.
* `mypy src/ken`: limpio (109 ficheros).
* Medición contra el catálogo anterior: los **49** tests fallan, porque la variante era
  `design` y `named_rule` no la registra.

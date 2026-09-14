# `interpreter#expression-sum` (6 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **seis** lenguajes declarados
(`typescript`, `java`, `csharp`, `cpp`, `go`, `rust`). Fecha: 2026-09-14.
Base: IR 1.71.0. **Sin cambio de IR**: la query se escribe con hechos que ya existían.

## Qué se publica

Una expresión **etiquetada**, sin subtipado, evaluada con un contexto:

```
struct Ctx { depth: i32 }
struct Expr { kind: Kind, value: i32, left: Box<Expr>, right: Box<Expr> }
if self.kind == Kind::Num { return self.value; }
self.left.evaluate(ctx) + self.right.evaluate(ctx)
```

Es la forma de [`composite#algebraic-tree`](composite-algebraic-tree.md) más el contexto,
y comparte con ella las tres cláusulas de estructura y dispatch. Lo que añade:

```
$operation HAS_PARAMETER $context          (parameter(receiver: false))
$first_call  ARGUMENT $first_argument   --VALUE--> <loaded> --LOADED_FROM--> $context
$second_call ARGUMENT $second_argument  --VALUE--> <loaded> --LOADED_FROM--> $context
```

La correlación es **por identidad del parámetro**: las dos llamadas recursivas tienen que
cargar el **mismo** contexto. Eso es lo que rechaza `no-context-argument`, donde las dos
llamadas llevan una constante.

Por qué no se duplica con `expression-objects` (la otra variante de interpreter, ya
`ready`): aquélla exige `SUBTYPE_OF` y `OVERRIDES` —subtipado nominal— y ésta no los
exige en absoluto, porque los casos son un tag. Un fixture con contexto satisface las
dos, y el catálogo permite explícitamente que dos contratos se cumplan a la vez.

## Lo que se dejó sin resolver a propósito

* **La combinación de los dos resultados.** La ficha pide "relacionar cada evaluación de
  hijo con el resultado combinado del operador", y eso **no** se prueba: haría falta flujo
  de valores desde las dos llamadas hasta el retorno, que el IR no tiene porque los
  operandos de un `binary_expression` viven como atributo de la operación y no como
  relación. Es el mismo límite que `expression-objects` ya declara en su `caveat`, y por
  eso el negativo "evaluación de hijos seguida de retorno constante" **no** se puede
  rechazar todavía.
* **Exhaustividad y hoja.** No se prueba que los valores del tag sean distintos, que las
  ramas sean exhaustivas, ni que la rama hoja no recurra.
* **Codificación por casos.** Igual que en `algebraic-tree`, la suma real —variantes de un
  `enum`, unión discriminada, records, `std::variant`— no se acepta: sus casos no se
  modelan como tipos con campos. Sigue medido en
  [bloqueos medidos](P9-remaining-variants-blockers.md).

## Validación

* `tests/structural/test_interpreter_expression_sum.py`: 49 tests. Positivo y renombrado
  en los seis lenguajes, cuatro negativos por lenguaje (`no-context-argument`,
  `one-operand`, `no-tag-field`, `no-branch`), la consulta raíz `interpreter` en los seis,
  la comprobación de que el contexto aparece como `LOADED_FROM` en la vista de query, y
  los metadatos. Los fixtures se construyen **derivando** el generador de
  `test_composite_algebraic_tree` con una transformación explícita por lenguaje (firma +
  argumento de las llamadas), y cada fuente se parsea en `build()`, así que una
  transformación inválida falla en vez de analizarse como otra cosa.
* Suite estructural completa: **7551 passed / 140 xfailed** (antes: 7501 / 140; los 50
  nuevos son los 49 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`). Ningún test existente cambió de expectativa.
* `mypy src/ken`: limpio (109 ficheros).
* Medición contra el catálogo anterior: los **49** tests fallan, porque la variante era
  `design` y `named_rule` no la registra.

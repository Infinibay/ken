# Interpreter: del algoritmo en palabras al IR

Esta revisión separa **la firma estructural GoF**, **el contrato de una familia de
intérpretes** y **la semántica de una gramática concreta**. La query actual es
`interpreter#expression-objects` en
[`interpreter.toml`](../../../../src/ken/structural/patterns/interpreter.toml).
Reconoce un subtipo que evalúa un hijo del mismo contrato y le pasa un valor
cargado desde un parámetro. No demuestra una gramática ni que el resultado se use.

## Algoritmo en palabras

Para una gramática pura de expresiones binarias:

1. Recibir un nodo de expresión y un contexto de evaluación.
2. Si el nodo es terminal, obtener su literal o consultar el contexto mediante el
   identificador del terminal. Producir ese valor.
3. Si representa una operación binaria estricta, obtener sus dos operandos,
   evaluar cada operando con el contexto correspondiente y conservar ambos
   resultados.
4. Aplicar la operación declarada por ese nodo a esos resultados. Retornar el
   resultado de la operación, conservando su procedencia hasta el retorno.
5. Si la operación tiene evaluación condicional, evaluar el segundo operando
   solamente cuando lo exijan el primer resultado y la política de la gramática.

Esta familia no abarca intérpretes imperativos que escriben el entorno y retornan
`void`, evaluadores con contextos derivados por alcance, máquinas de bytecode ni
compiladores de closures. Necesitan variantes; no deben rechazarse por no cumplir
el contrato de expresiones puras.

## Identidades e invariantes

| Identidad | Relación que se debe conservar |
| --- | --- |
| Nodo | El dispatch corresponde a su variante o implementación del contrato |
| Operandos | Los objetos evaluados provienen de sus posiciones del nodo |
| Contexto | Cada evaluación usa el contexto recibido o una derivación autorizada |
| Resultado izquierdo/derecho | Son los valores de esas evaluaciones, no otras lecturas |
| Resultado compuesto | Depende de los resultados exigidos por la operación |
| Valor retornado | Conserva la procedencia del resultado compuesto |
| Región condicional | El operando perezoso sólo se evalúa dentro de la rama adecuada |

Para suma pura, ambos resultados son necesarios. Cambiar suma por resta **sigue
siendo Interpreter**: sólo viola una búsqueda especializada en una gramática de
suma. Descartar un operando tampoco refuta cualquier intérprete imaginable: hay
operaciones de secuencia, efectos y operadores selectivos. Por eso las expectativas
más fuertes abajo se etiquetan como contrato propuesto de evaluación binaria pura.

No alcanza con congelar el binding de contexto. Puede conservar su dirección y
cambiar su mapa interno. Tampoco se puede asumir que evaluar un hijo es puro porque
el método se llame `evaluate`. La pureza necesita resumen de efectos, contrato
confiable o resultado `unknown`.

## IR objetivo

Notación explicativa, no un programa aceptado por un parser de texto ni una nueva
sintaxis KenQL implementada:

```text
function evaluate_sum(%node, %context) {
  %left_address = field.addr %node [field = left]
  %left = memory.load %left_address
  %a = call %left.evaluate(%context) [effects = unknown]
  %right_address = field.addr %node [field = right]
  %right = memory.load %right_address
  %b = call %right.evaluate(%context) [effects = unknown]
  %result = binary %a, %b [operator = +]
  return %result
}
```

El núcleo tiene instrucciones de direcciones, cargas, llamadas, valores y
operadores para representar este flujo. Los bindings locales pueden agregar
`slot.store`/`slot.load`; el buscador tiene que seguir los valores a través de
esas operaciones, no equiparar apariciones con el mismo nombre.

Contrato deseado de la búsqueda: seleccionar `%node` y el método; vincular ambos
operandos por posición; correlacionar el argumento de ambas llamadas con el
contexto; vincular los resultados a los operandos de `binary`; vincular su salida
al retorno. Permitir instrucciones independientes entre estos eventos. Si una
escritura corta la procedencia de `%b`, ese flujo deja de cumplir el contrato.

Para un AND perezoso:

```text
%a = call %left.evaluate(%context)
%result = short_circuit %a [operator = and, truth_policy = grammar.boolean] {
  %b = call %right.evaluate(%context)
  output %b
}
return %result
```

`truth_policy` es un requisito de diseño, no un atributo ya reconocido por el
matcher. Python `and` puede retornar un operando, mientras que Java `&&` produce
un booleano. Un intérprete puede definir otra política. El lowering no debe
normalizar todas estas operaciones como booleanas ni ejecutar el segundo brazo
para construir una lista plana de instrucciones.

## Variantes por lenguaje y representación

| Variante | Ejemplos | Evidencia requerida / límite actual |
| --- | --- | --- |
| Árbol de clases | Python, Java, TypeScript, C++ | Subtipado o contrato + hijos + contexto; query actual disponible |
| Suma etiquetada | Rust `enum`, TypeScript unión discriminada, Go type switch | Dispatch exhaustivo/por variantes y recursión por campos; variante declarada `design` |
| Evaluador externo | Visitor Java/C++, funciones Python | Nodo y contexto pueden ser argumentos; no exigir recursión en método del nodo |
| Closure compilada | JavaScript/TypeScript, Python | Captura de operandos/contexto y consumo diferido; requiere flujo de closures |
| Entornos anidados | Python/JS, Rust con mapas y scopes | Contexto hijo derivado del padre; la identidad estricta sería un falso negativo |
| Evaluación imperativa | Java/C#/Go/Python | Escrituras de entorno y control como resultados observables; no exigir retorno numérico |
| Préstamos y referencias | Rust, C++ | `&Context`, `&mut Context` o referencias no son pruebas universales de pureza |

Las pruebas nuevas ejecutan el analizador sobre Python, Java y TypeScript. Esta
tabla no afirma validación de las otras variantes. El catálogo declara también
C++ para expression-objects y tiene regresiones previas independientes.

## Ruido permitido y negativos

Ruido ensayado: aritmética con variables locales nuevas y logging de esos números,
antes de evaluar y entre las dos evaluaciones. No se pasa nodo, contexto ni
resultado al logger. El matcher conserva la detección; esto no prueba pureza
interprocedural de logging arbitrario.

Negativos rechazados por la firma actual:

- Ambos hijos reciben una constante en vez del contexto.
- Ambos hijos reciben otro local, inicializado de forma independiente.
- Se reemplazan ambas llamadas recursivas por lecturas del contexto.

Gaps del contrato binario puro, reproducidos como `xfail(strict=True)`:

- Sólo el hijo derecho recibe otro contexto: el izquierdo satisface toda la query.
- Se descarta el resultado izquierdo.
- Se descartan ambos resultados y se retorna una constante.
- Se sobreescribe el resultado derecho con cero antes de combinarlo.

La causa común es que la query exige **existencia de un hijo** y un argumento
correlacionado. No expresa universalidad sobre operandos relevantes, ni consumo de
resultados, ni procedencia hasta el retorno. La metadata `graph_requirements`
menciona combinación de resultados, pero la query ejecutable no la comprueba.

## Evidencia reproducible y siguiente paso

[`test_algorithm_interpreter.py`](../../../../tests/structural/test_algorithm_interpreter.py)
contiene 36 casos en tres lenguajes:

- 12 positivos con cuatro posiciones de ruido.
- 9 negativos rechazados: tres rupturas × tres lenguajes.
- 3 positivos para otra operación binaria válida.
- 12 expectativas todavía incumplidas del contrato binario puro, señaladas con
  `xfail(strict=True)` para que una mejora obligue a convertirlas en regresiones
  normales. **No cuentan como negativos correctamente detectados.**

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_interpreter.py
```

El siguiente paso es una query más específica para evaluación binaria pura que
componga el contrato de operandos con el de flujo de resultados. No endurecer la
única query global con `operator = +`, ni exigir dos hijos a todas las variantes:
eso excluiría terminales, operadores unarios e intérpretes de otros lenguajes.
La representación debe añadir políticas de evaluación y resúmenes de efectos
cuando haya evidencia; sin ella, conservar `unknown`.

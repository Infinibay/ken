# Strategy: del algoritmo en palabras al IR

Strategy selecciona una política para realizar una operación. La
[query existente](../../../../src/ken/structural/patterns/strategy.toml) combina
políticas como objetos y callables suministrados. La operación pública
`strategy.supplied_policy` permite reutilizar la evidencia de retención en
búsquedas de uso más concretas, sin convertir todas las políticas en una misma
forma de clase.

## Algoritmo en palabras

1. Elegir o recibir una implementación del algoritmo según una decisión externa
   al consumidor de esa operación.
2. Retenerla o pasarla hasta el punto de uso con el contrato necesario.
3. Cuando se solicita la operación, invocar la política seleccionada con los
   datos que requiere la tarea.
4. Consumir su resultado o sus efectos conforme al contrato del consumidor.
   Puede retornarlo, combinarlo, almacenarlo o utilizarlo para otra decisión.
5. Si se cambia la política, hacer que los usos posteriores observen esa selección
   según el ciclo de vida del consumidor.

No es necesario que el código instancie varias políticas durante una misma
invocación. Tampoco todas las estrategias retornan valores: ordenamiento in-place,
renderizado y acciones con efectos pueden ser legítimos. Las obligaciones de
identidad de input y retorno directo usadas abajo son un **refinamiento elegido**,
no condiciones universales para clasificar Strategy.

## Identidades e invariantes

| Elemento | Contrato |
| --- | --- |
| Política suministrada | Es la implementación seleccionada o una adaptación autorizada |
| Slot retenido | Guarda esa política en la configuración modelada |
| Uso | Invoca el slot seleccionado, no otro campo con un objeto parecido |
| Input | Proviene de la operación del consumidor o de una transformación permitida |
| Resultado / efectos | La operación consume la evidencia producida por esa misma invocación |
| Nueva selección | Su visibilidad temporal es coherente con el uso posterior |
| Familia de algoritmos | La compatibilidad viene del contrato, no de nombres como Fast/Slow |

Un context con policy inyectada se parece a State, Command, Bridge y otros
patrones. Strategy enfatiza elección de algoritmo; la presencia de un setter no
prueba transición de estado por evento. Estas intenciones pueden solaparse y las
queries deben exponer evidencias concretas.

## IR objetivo

Notación de diseño, no una nueva gramática textual implementada:

```text
function configure(%context, %supplied) {
  %slot = field.addr %context [field = policy]
  memory.store %slot, %supplied
}

function apply(%context, %input) {
  %selected = memory.load (field.addr %context [field = policy])
  %result = call %selected.run(%input)
  return %result
}
```

Para una política funcional, `%selected` es el callee en lugar del receiver:

```text
%selected = memory.load %context.policy
%result = call %selected(%input)
return %result
```

El IR debe conservar qué valor fue suministrado, cuál se carga al usarlo y qué
resultado pertenece a qué llamada. Para estrategias genéricas/estáticas, la
selección puede ser un argumento de tipo y no debe materializarse un campo de
objeto ficticio sólo para satisfacer una query de runtime.

Un resultado intermedio puede almacenarse en un local y atravesar logging/cálculos
independientes. Si ese local se sustituye por otra cosa antes de retornar, la
búsqueda de retorno de política debe dejar de afirmar esa procedencia, aunque el
código siga teniendo una llamada a la política.

## Query de uso ejecutable hoy

El siguiente ejemplo se ejecuta como `SavedRule` en la nueva matriz. Es una query
componible documentada, **no una nueva entrada built-in del catálogo**:

```kenql
query same_input_policy_result {
  match "strategy.supplied_policy"(unit:$unit, configure:$configure, policy:$policy);
  require $unit HAS_METHOD $algorithm;
  different $configure $algorithm;
  require $algorithm HAS_PARAMETER $input;
  parameter(receiver:false) as $input;
  require $algorithm HAS_CALL $invocation;
  any { require $invocation RECEIVER $policy; }
  or { require $invocation CALLEE_VALUE $policy; }
  call() as $invocation { has_argument(pos:0, kind:positional) as $argument; }
  require $argument VALUE $read;
  require $read LOADED_FROM $input;
  require $algorithm RETURNS_VALUE $result;
  require $invocation RESULT $result;
  emit $unit, $policy, $algorithm, $invocation, $input, $result;
}
```

La búsqueda vincula la política retenida con su invocación, el primer argumento
con un parámetro de entrada y el valor retornado con el resultado de **esa misma
llamada**. Así no toma como prueba cualquier resultado del método ni el simple
hecho de que existió una llamada.

Este contrato exige retorno directo en términos de flujo de valores: admite un
alias local, pero no modela una transformación arbitraria posterior. Para detectar
políticas usadas mediante efectos, agregación o predicados se compone otra query.
También debe agregarse resolución de contrato/slot cuando se necesite distinguir
qué método de un objeto policy constituye el algoritmo; la query de uso por sí
sola no demuestra toda la intención GoF.

## Variantes por lenguaje

| Representación | Ejemplos | Qué necesita el IR |
| --- | --- | --- |
| Objeto inyectado | Python, Java, TS, C#, C++ | Retención, contrato de método y dispatch |
| Función/closure | Python, JS/TS, Go | Valor callable, capturas, identidad del callee y resultado |
| Functional interface | Java, C# delegates | Adaptación de lambda/method-reference a contrato callable |
| Política por tipo | C++ templates, Rust generics/traits | Sustitución de tipos y dispatch estático |
| Política por llamada | Muchos lenguajes | Argumento callable sin exigir almacenamiento persistente |
| Composición de políticas | Comparadores/predicados/estrategias combinadas | Orden, entradas compartidas y consumo de resultados intermedios |
| Política async | Aplicaciones web/servicios | Await, error/cancelación y procedencia de respuesta |

`static-policy` figura como `design` en el catálogo. La validación nueva usa
objetos en Python/Java/TypeScript y callables en Python/TypeScript. Las formas
restantes son requisitos o cobertura previa separada, no resultados nuevos de
este ejercicio.

## Evidencia reproducible

[`test_algorithm_strategy.py`](../../../../tests/structural/test_algorithm_strategy.py)
complementa las matrices existentes de última escritura/configuración; se concentra
en **consumo de la política** y composición de named queries.

**30 passed, sin xfail**:

- 10 positivos: cinco combinaciones lenguaje/representación, con y sin cálculo y
  logging independientes entre la llamada y el retorno.
- 15 negativos del refinamiento: input constante ajeno, resultado descartado o
  resultado sobrescrito antes del retorno.
- 5 negativos adicionales: el parámetro se reasigna a cero antes de invocar la
  política; los modelos actuales rechazan la procedencia requerida en esos casos.

En los 15 contrastes se comprueba también que la firma Strategy genérica sigue
reconociendo la composición. Esto evita confundir “no cumple mi búsqueda de
retorno del mismo input” con “no hay Strategy”. Los tests analizan fuentes; no
se ejecuta código de los fixtures.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_strategy.py
```

No se modificó el motor ni el TOML: la mejora aquí consiste en expresar y verificar
una búsqueda más fuerte utilizando relaciones y operaciones públicas existentes.

## Límites que la matriz no demuestra

La retención en configure es evidencia de una escritura modelada, no de que el
slot conserve esa policy durante toda la vida del objeto. Descriptores, setters,
callbacks y otras llamadas pueden cambiar el heap. Tampoco se prueba pureza,
seguridad concurrente, equivalencia de algoritmos ni el orden global entre
configure y apply.

Para ampliar el IR hacen falta valores actuales y aliases entre métodos, resúmenes
de efectos y transformaciones de input/output, sustitución de políticas estáticas
y mejores modelos de closures/await. No endurecer el patrón genérico con retorno
obligatorio ni dos implementaciones visibles en cada archivo: las propiedades de
uso se deben pedir explícitamente y mantener su incertidumbre donde falte modelo.

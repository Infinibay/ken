# Bridge: dos ejes y el valor de la implementación retenida

Estado: revisión algoritmo→IR con pruebas complementarias a
`test_refined_bridge.py`. La [regla actual](../../../../src/ken/structural/patterns/bridge.toml)
reconoce dos dimensiones nominales; esta revisión estudia flujo del resultado,
selección del backend y límites de las escrituras.

## Algoritmo en palabras

1. Separar las operaciones de la abstracción de las primitivas de una
   implementación. Ambas dimensiones pueden admitir variantes.
2. Una instancia de la abstracción conserva una implementación compatible con
   su contrato. Puede recibirla por constructor, seleccionarla por configuración
   o resolverla mediante otra política declarada.
3. Al ejecutar una operación, leer la implementación retenida y usar sus
   primitivas para realizar el trabajo de la abstracción.
4. Una abstracción refinada modifica o amplía la operación sin acoplarla
   necesariamente a un backend concreto. El resultado de una primitiva puede
   retornarse, transformarse o combinarse según el contrato.
5. Si se promete respetar una implementación inyectada, el backend usado debe
   proceder de esa selección o de una transformación expresamente permitida.

Dos árboles de herencia son evidencia estructural, no prueba de evolución
independiente ni de que todas sus combinaciones sean válidas en ejecución.
Una implementación elegida internamente no invalida universalmente Bridge;
ignorar un argumento inyectado incumple un contrato adicional de selección.

## Traducción al IR

Representación conceptual: sus anotaciones de contrato no son sintaxis ejecutable
del exportador de instrucciones.

```text
function Panel.render(%self) {
  %field = field.addr %self, "driver"
  %backend = memory.load %field
  %primitive_result = call %backend, slot: Driver.run
  @value = slot.declare int
  slot.store @value, %primitive_result
  %metric = binary.add 1, 2
  call @log, argument[0]: %metric
  %returned = slot.load @value
  return %returned
}
```

La dirección del campo, su valor y la llamada son identidades distintas. Que dos
llamadas accedan a `self.driver` no demuestra que encuentren el mismo backend
si hay una escritura entre ambas. La relación con el argumento del constructor
requiere flujo interprocedural y una etapa de vida útil, no sólo `TYPE Driver`.

Para una abstracción que transforma resultados, el IR debe conservar:

```text
%raw = call %backend, slot: Driver.run
%result = call @compose, argument[0]: %raw
return %result
```

La prueba de transformación pertenece a un contrato diferente de «retornar
directamente el resultado». No se deben rechazar como no-Bridge todas las
abstracciones que combinan o ignoran un retorno mientras aprovechan sus efectos.

## Invariantes seleccionables

| Contrato | Evidencia | Negativo correspondiente |
|---|---|---|
| Dos dimensiones nominales | Relación abstracción/refinamientos y contrato/backends | Confundir una jerarquía de Decorator con dos ejes independientes |
| Backend retenido | Receptor obtenido del campo de implementación | Construir un backend fijo directamente en la llamada e ignorar el campo |
| Resultado propagado | Origen del valor retornado | Delegar y retornar una constante cuando se exige retorno directo |
| Backend inyectado respetado | Parámetro constructor→campo→receptor actual | Ignorar el parámetro y almacenar siempre `First()` |
| Selección estable | Estado de memoria entre puntos de uso | Sustituir el campo antes de delegar |

La matriz nominal previa cubre jerarquías, herencia de campos y receptores
equivocados. La [matriz nueva](../../../../tests/structural/test_algorithm_bridge.py)
añade cuerpos con variables locales, logging, aliases y escrituras; no repite
las combinaciones de jerarquía ya ensayadas.

## Refinamiento KenQL ejecutable del retorno

```kenql
query bridge_returned_primitive {
 match "bridge#refined-composition"(unit:$unit,operation:$operation,access:$access);
 require $operation HAS_OPERATION $return;
 require $return RETURN_ORIGIN $call;
 require $call RECEIVER $access;
 emit $unit,$operation,$call;
}
```

Se ejecuta como `SavedRule` temporal en las pruebas, sin modificar la regla del
catálogo. El refinamiento une el retorno a la llamada sobre el acceso de
implementación identificado por Bridge. En los cuerpos lineales ensayados,
`RETURN_ORIGIN` conserva un resultado asignado a una variable y un alias guardado
antes de reasignar la variable original. `RETURNS_CALL` no proporcionaba esa
misma cobertura para estos cuerpos, por lo que no es intercambiable sin pruebas.

La consulta demuestra un origen de retorno representado por el análisis, no una
obligación universal sobre todos los caminos. Cuerpos ramificados necesitan
atender a las modalidades de los hechos y a la completitud del análisis.

Los negativos que descartan o sobrescriben el resultado siguen siendo candidatos
Bridge nominales, pero no satisfacen este refinamiento de retorno. Mantener esa
distinción evita endurecer indebidamente la definición general del patrón.

## Variantes por lenguaje

| Lenguaje | Dos ejes posibles | Necesidad del IR |
|---|---|---|
| Python | Jerarquía de vistas y protocolo/clases backend | Campos dinámicos, aliases e instancia heredada |
| Java | Abstracción/refinamientos e interfaz de implementación | Slots, inyección y campo de instancia |
| TypeScript | Clases más interfaz estructural | Relación estructural y selección del objeto retenido |
| JavaScript | Objetos/prototipos y backend por métodos o closures | Evidencia de dimensión alternativa sin exigir herencia nominal |
| C# | Clases/interfaz o genéricos | Virtual dispatch, genéricos y campos heredados |
| C++ | Interfaz virtual o parámetro template de backend | Raíces nominales, ownership y especialización |
| Go | Interfaces/structs embebidos | Composición y contratos implícitos, sin inventar jerarquías de clases |
| Rust | Traits con `dyn` o parámetros genéricos | Borrow del backend, sustitución de tipos y dispatch estático/dinámico |

La independencia conceptual no exige dispatch virtual. `generic-composition` pasó a
`ready` en IR 1.64 para sus seis lenguajes, y **sin pedir subtipo, interfaz ni
implementaciones**: la evidencia es que un tipo liga un parámetro de tipo, un campo suyo
está tipado por él y un método delega en el campo, **y que al menos dos tipos ligan el
mismo parámetro** — eso último es lo que lo separa de `strategy#static-policy`, que lee
la misma forma. Esta matriz valida solamente Python, Java y TypeScript, no certifica las
otras formas de la tabla.

## Resultados y gaps

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_bridge.py
```

Resultado inicial: **18 passed, 3 xfailed estrictos**.

- Seis positivos de retorno: local o alias, con logging y cálculo independiente.
- Seis negativos del refinamiento: resultado descartado o sobrescrito.
- Tres rechazos de llamada directa a un backend fijo que ignora el campo.
- Tres controles de abstención: escribir el campo del backend dentro de la
  operación produce `RETURN_FLOW_STATUS=unsupported`, con motivo
  `nonlocal-or-nested-write`. El refinamiento no encuentra match, pero eso no
  demuestra un negativo semántico: la consulta carece de evidencia suficiente.
- Tres `xfail(strict=True)` del contrato de selección inyectada: reemplazar el
  argumento almacenado por `First()` en el constructor conserva el match y el
  origen del retorno. El refinamiento no relaciona constructor y receptor actual.

Las fuentes se parsean y se consultan; no se ejecutan ni compilan. Logging sobre
números no afecta el algoritmo ensayado, pero no se prueba pureza de funciones
arbitrarias ni ausencia de excepciones. Las limitaciones pendientes son flujo
interprocedural de selección, versiones del campo, caminos de control y variantes
estructurales/genéricas, además de contratos de transformación del resultado.

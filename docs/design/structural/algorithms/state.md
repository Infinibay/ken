# State: del algoritmo en palabras al IR

State hace depender el comportamiento del **estado actual** de un contexto. Una
policy intercambiable también puede delegar mediante una interfaz y cambiar de
objeto, por lo que esa estructura por sí sola no distingue State de Strategy.
El [catálogo](../../../../src/ken/structural/patterns/state.toml) ofrece la firma
`state-object` y una variante más correlacionada `context-transition`.

## Algoritmo en palabras

1. Conservar el estado activo de un contexto o representarlo como valor explícito.
2. Al recibir un evento, obtener ese estado activo y seleccionar su comportamiento
   para el evento recibido.
3. Ejecutar la acción y, cuando la condición de transición se cumple, decidir el
   sucesor de acuerdo con la política de la máquina.
4. Instalar el sucesor en el slot que gobierna los próximos dispatches del mismo
   contexto, o devolver un contexto sucesor si la implementación es inmutable.
5. Hacer que eventos posteriores observen la transición según el orden y ciclo de
   vida definidos por esa implementación.

Puede haber transiciones al mismo estado, estados sin transición para cierto
evento, entry/exit actions, estados jerárquicos y transición decidida por el
contexto en lugar del objeto State. No exigir clases distintas para toda transición
ni imponer un setter como única representación.

## Identidades e invariantes

| Elemento | Contrato |
| --- | --- |
| Contexto | Es la instancia cuyo comportamiento se está seleccionando |
| Slot de estado | La transición modifica el slot que alimenta el dispatch siguiente |
| Estado activo | El objeto/valor leído es el actual en ese punto, no uno asignado históricamente |
| Evento | La acción recibe el evento original o una transformación autorizada |
| Decisión | Sus condiciones corresponden al estado/evento seleccionado |
| Sucesor | Tiene el contrato requerido y se instala o devuelve efectivamente |
| Backreference | La transición apunta al contexto seleccionado en ese instante |
| Orden | La siguiente observación del estado concuerda con el momento de instalación |

La diferencia con Strategy es de contrato: una política elegida por el cliente no
constituye por sí sola una evolución de estado dirigida por eventos. Aun viendo
un método que cambia la policy, puede faltar evidencia para clasificar intención.
Es razonable ofrecer firmas candidatas y queries más fuertes de transición.

## IR objetivo

Notación de diseño; no gramática textual IR/KenQL nueva:

```text
function request(%context, %event) {
  %slot = field.addr %context [field = state]
  %active = memory.load %slot
  call %active.act(%event)
}

function Idle.act(%self, %event) {
  %owner = memory.load (field.addr %self [field = context])
  %enabled = compare %event, 0 [operator = >]
  if %enabled {
    %next = construct @Ready()
    call %owner.install(%next)
  }
}

function Context.install(%self, %replacement) {
  memory.store (field.addr %self [field = state]), %replacement
}
```

El núcleo puede expresar loads/stores, argumentos, llamadas y control. Para buscar
el algoritmo debe correlacionarlos entre métodos: el estado instalado inicialmente
retiene ese contexto; el dispatch invoca su acción; su acción cambia el estado de
ese mismo contexto. Los valores actuales importan: no basta con saber que alguna
vez el campo `context` recibió un argumento de constructor.

En un diseño con valores:

```text
%next_state, %effects = transition(%current_state, %event)
apply %effects
memory.store %context.state, %next_state
```

La transición puede ser un `match` sobre enum/tag y no crear objetos State. No
introducir clases ficticias al bajar esa forma al IR. En una máquina inmutable,
la salida puede ser un nuevo contexto y el caller debe conservarlo: ignorar esa
salida puede ser el bug que una query de uso quiere detectar.

## Variantes por lenguaje

| Representación | Ejemplos | Necesidad de análisis |
| --- | --- | --- |
| Objetos State con backreference | Python, Java, TS, C# | Constructor → contexto actual → setter del slot de dispatch |
| Contexto pasado a action | C++/Java/Go y otros | Vincular argumento explícito, no exigir campo de backreference |
| Sucesor retornado | Python/TS/Rust y otros | Retorno de acción consumido por la escritura del estado activo |
| Enum/tag con ramas | Rust/Go/C/C++/Java/TS | `match`/switch, guardas y def-use del discriminante |
| Typestate | Rust/C++ | Tipo de sucesor, ownership y uso del valor devuelto |
| Máquina de tablas | Muchos lenguajes | Clave estado/evento y resultado de lookup, no sólo existencia de mapa |
| Async/event loop | Aplicaciones web y servicios | Orden de eventos, suspensión, reentrancia y transiciones pendientes |

La variante `state-enum` del catálogo pasó a `ready` en IR 1.58 para los ocho
lenguajes declarados: el discriminante es un valor, la guarda que lo menciona
gobierna la escritura (`GUARDS_WRITE`) y el mismo callable escribe al menos dos
constantes distintas, contadas **por identidad de declaración** y no por posición de
sintaxis. Esta revisión prueba Python, Java y TypeScript con backreference; la tabla
no acredita cobertura de las otras representaciones ni equivalencia completa de
máquinas de estados.

## Pruebas nuevas y límites comprobados

[`test_algorithm_state.py`](../../../../tests/structural/test_algorithm_state.py)
parte de los fixtures de context-transition existentes y agrega un evento que
condiciona el paso Idle → Ready. Intercala cálculo/logging de valores independientes
en la acción y en el setter, sin pasarles estado ni contexto a esas llamadas.
Evalúa específicamente `state#context-transition`, para no ocultar sus resultados
con la firma más amplia `state-object`.

**Resultado: 9 passed, 9 xfailed**:

- 6 positivos con/sin ruido en tres lenguajes.
- 3 negativos: el setter escribe otro slot, aun con ese ruido.
- 3 expectativas pendientes de preservación del evento: el dispatch cambia el
  evento recibido por cero, por lo que la acción ya no responde al pedido positivo.
- 3 expectativas pendientes de contexto actual: la acción reasigna su backreference
  a otro contexto antes de invocar install.
- 3 expectativas pendientes de estado activo: request reemplaza el estado por
  Ready antes de dispatch, pero el matcher utiliza la acción histórica de Idle.

Los nueve xfail estrictos son fallos de la **búsqueda refinada de transición
correlacionada**. No significa que una aplicación deje de usar State por filtrar
un evento o tener transiciones preparatorias legítimas: esas políticas requieren
contratos distintos. La query actual no verifica estas obligaciones temporales.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_state.py
```

No se repite la matriz anterior de posiciones de argumentos/setters y tipos de
sucesor; esas regresiones permanecen en
[`test_state_context_transitions.py`](../../../../tests/structural/test_state_context_transitions.py).

## Causas y requisitos pendientes

`context-transition` correlaciona bindings de constructor, backreference, acción y
setter. Sin embargo, `CONSTRUCTOR_FIELD_INPUT` describe la captura en construcción,
no el valor del campo en todos los instantes posteriores. La relación nominal del
slot de dispatch tampoco demuestra que siga conteniendo aquel estado cuando se
produce el evento. Además, la query no une el argumento del request con el de act.

No se cambió motor/TOML en este ejercicio. Exigir un último store lineal en todas
las transiciones excluiría transiciones condicionales válidas sin resolver estas
correlaciones interprocedurales. Los requisitos son:

1. Llegada de definiciones al load del estado activo y al load de su contexto.
2. Propagación de valores de evento entre llamadas, con políticas explícitas de
   transformación y posibles efectos.
3. Resúmenes de transición que vinculen estado previo, condición, sucesor y slot
   afectado, indicando lo conocido y lo desconocido.
4. Búsquedas de uso que comprueben que el sucesor retornado se instala o consume.
5. Modelo de orden/reentrancia cuando action puede suspenderse o provocar otro
   evento antes de completar la transición.

No se infieren exhaustividad, alcanzabilidad, ausencia de ciclos ni corrección de
protocolo por nombres como Idle/Ready. El IR debe permitir plantear esas búsquedas
cuando exista evidencia suficiente y conservar `unknown` en los demás casos.

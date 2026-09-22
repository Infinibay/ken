# Continuation wrappers: diseño de autoría KQL 2

15 de septiembre de 2026. Subrevisión limitada a `continuation-wrapper.toml` y
`adapted-continuation-wrapper.toml`. **Los TOML permanecen sin modificar**: el
motor todavía rechaza tres piezas necesarias. Este documento propone la autoría
objetivo, no declara que ya sea ejecutable.

## Continuation Wrapper

Obligación: un proveedor devuelve un callable que conserva una continuación
recibida y la invoca al ejecutar el wrapper. Un wrapper de propagación debe
además pasar los datos seleccionados y entregar el resultado correspondiente.
El wrapper puede añadir logging, validación o una transformación acreditada.
No se exige un nombre, framework, aridad cero ni exactamente una invocación.

Autoría objetivo de la variante que propaga un argumento y el resultado:

```kql2
language "kql/2";
module ken.catalog.architecture.continuation_wrapper;
import ken.core;

pattern ForwardingWrapper(out Callable $factory, out Callable $handler,
                          out Parameter $continuation) {
  callable $factory {
    parameters { param $continuation {} }
    callable $handler {
      parameters { param $request {} }
      body {
        let $response = call $continuation { argument $request at any; };
        return $response;
      }
    }
    body { return $handler; }
  }
}

query results {
  use ForwardingWrapper(factory: $factory, handler: $handler,
                        continuation: $continuation);
  select $factory, $handler, $continuation;
}
```

La variante sólo-de-efectos debe mantener el `call` sin exigir `return $response`.
Una variante que transforma datos requiere expresar esa transformación en BODY;
no se debe confundir con un falso positivo por no reenviar la misma identidad.
El parámetro request tampoco es obligatorio para continuaciones sin argumentos.

**Falta una obligación adicional de preservación de la continuación**. El código
anterior por sí solo no debe aceptarse si `next` se sustituye antes de la llamada.
Un cierre captura una celda o un valor según el lenguaje: la procedencia del
callee en su ocurrencia debe corresponder a la entrada del factory. `gap` local
entre dos operaciones del mismo BODY no cubre el intervalo entre creación del
cierre, retorno del factory e invocación posterior. Debe existir captura de valor
de entrada + análisis de efectos/captura, con resultado unknown donde runtime
pueda escribir a la celda y no haya prueba suficiente.

Fixture mínimo:

```python
def wrap(next):
    def handler(request):
        audit(request)
        result = next(request)
        audit(result)
        return result
    return handler
```

Negativos esenciales: `next = other` antes de devolver el cierre; parámetro
interno llamado `next` que oculta el externo; retornar otro cierre; ejecutar
`other(request)`; resultado de `next` descartado si se afirma propagación;
`next(other_request)` sin transformación acreditada. En JavaScript hay que
cubrir arrow expression, bloque y async; en Go, func literal y variable local.

## Adapted Continuation Wrapper

Obligación: el adaptador recibe un handler que delega en la continuación recibida;
el factory entrega el valor producido por esa adaptación. Para afirmar wrapper
funcional se necesita además acreditar que el resultado es invocable y conserva
el handler. Que no se pueda demostrar que sea escalar no demuestra callability.

Autoría objetivo para continuación objeto:

```kql2
pattern AdaptedWrapper(out Callable $factory, out Callable $handler,
                       out Parameter $continuation, out Callable $adapt) {
  callable $factory {
    parameters { param $continuation {} }
    callable $handler {
      parameters { param $request {} }
      body {
        call $invoke {
          receiver: $continuation;
          argument $request at any;
        };
      }
    }
    body {
      let $wrapped = call $adapt { argument $handler at any; };
      return $wrapped;
    }
  }
}
```

Falta el contrato del adaptador: puede ser una conversión de tipo con semántica
conocida (Go `http.HandlerFunc`), una función que devuelve el mismo handler, o una
función que produce otro cierre/objeto invocable conservándolo. La consulta base
sólo es un candidato de flujo hasta que un modelo acreditado o un subpatrón
verifique esa conservación. No esconder todo el detector en un predicado Python.
Usar composición por named patterns con roles de entrada/salida es apropiado.

Fixture que no basta para probar el patrón:

```python
def adapt(handler):
    return 42

def wrap(next):
    def handler(request):
        return next(request)
    return adapt(handler)
```

También debe rechazarse `adapt(handler); return adapt(other)`. Una adaptación
válida que devuelve objeto con método callable no puede rechazarse sólo porque
el resultado no sea una función. Identidad de API debe provenir de resolución;
un identificador arbitrario `HandlerFunc` no es prueba del contrato estándar.

## Cambios concretos requeridos en el motor

1. Selector anidado `callable` dentro de otro `callable`. Propiedad inmediata de
   declaración, no descendencia transitiva: impedir mezclar un cierre hermano.
   La pertenencia se baja internamente al índice de ownership existente.
2. `return $handler` y `argument $handler at any` cuando `$handler` es Callable.
   Tratar esa declaración como valor de función y seguir su identidad por
   ocurrencia, incluyendo aliases y asignaciones que los invalidan. No convertir
   una historia de asignaciones en prueba del valor actual.
3. BODY de retorno implícito para arrow/lambda/func literal según lenguaje.
   El IR ya tiene evidencia de retorno en varios de estos casos, pero no todos
   representan un RETURN explícito: normalizar semántica sin inventar control.
4. Uso del parámetro capturado sin sustitución. Capturas por valor y por celda
   tienen obligaciones distintas; tomar en cuenta escrituras del factory y de
   cierres relevantes, y ser conservador con escapes y ejecución diferida.
5. Valores invocables: funciones, closures y objetos con protocolo invocable.
   Propiedades de tipo/familia y modelos de adaptación deben acreditar retención
   del handler y distinguir desconocido de una adaptación comprobada.
6. Preservar output de evidencia separado de Callable: el TOML antiguo llama
   `$adapter` a la ocurrencia de llamada. La autoría nueva puede exponer `$adapt`
   como Callable y `as $adaptation` como Operation, sin mezclar ambas identidades.

## Prueba de los bloqueos

Tres consultas mínimas fueron compiladas el 15 de septiembre:

| Construcción | Resultado actual |
| --- | --- |
| `callable $factory { callable $handler {} }` | `callable cannot immediately own callable` |
| `callable $handler {}; ... body { return $handler; }` | `source operand requires a bound storage, parameter or captured value` |
| `... call $adapt { argument $handler at any; }` | Mismo rechazo de operando Callable |

No se añadió xfail para declarar normales estas carencias. No se cambió ningún
TOML a una consulta que perdiera ownership, preservación o tipo de resultado.
Se conservaron los fixtures existentes como baseline diagnóstico; todavía no
validan la autoría objetivo de este documento.

## Actualización tras ampliar el motor en esta sesión

El motor ya acepta el selector Callable anidado y Callable como operando de
retorno/argumento. El wrapper directo de este documento (sin exigir propagación
de argumentos/resultado) encuentra los cuatro fixtures Python, Go, JavaScript y
TypeScript. Rechaza el cierre que oculta el parámetro y el factory que retorna
otro callable.

**No permite todavía migrar preservando precisión**. Las dos mutaciones siguientes
se aceptan con `call $continuation`, a pesar de que ya no invocan la entrada:

```python
def wrap(next):
    next = other
    def handler(x):
        return next(x)
    return handler
```

```python
def wrap(next):
    def handler(x):
        return next(x)
    next = other
    return handler
```

La consulta previa excluía ambas mediante inventario de escrituras. Para la
nueva autoría se necesita una restricción de preservación de entrada, expresada
como propiedad/restricción fuente con semántica pública, y basada en evidencia
completa de escritura. No se debe sustituir por ausencia no cerrada de un BODY
que escriba, ni aceptar silenciosamente ese falso positivo.

Baseline anterior conservado: `test_closure_ownership.py` y
`test_adapted_continuation.py`: **51 passed en 3.28s**.

## Migración del wrapper directo en curso

Con la propiedad pública `param $continuation { reassigned: false; }` ya
implementada, `continuation-wrapper.toml` pasó a selectores fuente anidados y
BODY. La propiedad exige inventario soportado de escrituras explícitas del
binding y cero escrituras; desconocido no se interpreta como ausencia.
No se afirma estabilidad del heap ni ausencia de efectos ocultos.

Se agregó `tests/structural/test_authored_continuation_body.py`: reasignaciones
antes y después de declarar el cierre, shadowing y escrituras de otras variables.
Primera ejecución: 18 pasan, falla el positivo Go que retorna un alias local de
func literal. Pruebas existentes: 17 pasan, fallan 8 wrappers arrow de expresión
JavaScript/TypeScript (incluido async), por retorno implícito en BODY.

Estos fallos permanecen visibles, sin xfail ni cambio de expectativa; requieren
normalización del retorno implícito y origen actual de valores Callable a través
de aliases. El motor está siendo ampliado en paralelo; repetir las pruebas antes
de declarar completa la migración. Adapted wrapper sigue sin modificar.

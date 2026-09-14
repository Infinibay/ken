# Chain of Responsibility: del algoritmo en palabras al IR

La [query ejecutable](../../../../src/ken/structural/patterns/chain-of-responsibility.toml)
reconoce handlers enlazados mediante un contrato común y forwarding condicional.
Esa firma se solapa con Proxy. Para distinguir responsabilidades se necesita
analizar la petición, la decisión de atenderla y el uso de la siguiente etapa.

## Algoritmo en palabras

En una cadena con atención exclusiva:

1. Recibir una petición y decidir si este handler puede atenderla.
2. Si puede, realizar la responsabilidad local y producir la respuesta; terminar
   ese recorrido sin delegarla a otro handler.
3. Si no puede, obtener el siguiente handler y reenviarle esa petición, preservando
   los datos requeridos por el contrato. Propagar su respuesta o resultado de fallo.
4. Si no hay siguiente handler, aplicar el resultado terminal acordado: error,
   “no atendida”, valor por defecto o terminación sin efecto.

Otros contratos permiten que varios handlers observen/procesen la petición. Una
cadena de middleware puede ejecutar trabajo antes y después de `next`, modificar
el contexto y esperar una continuación asíncrona. No imponer exclusividad a esas
variantes. Un pipeline incondicional puede parecerse, pero carece de una decisión
de detener o continuar por handler si todas sus etapas siempre se ejecutan.

## Invariantes y políticas

| Identidad / evento | Obligación |
| --- | --- |
| Handler actual | Implementa la operación seleccionada del contrato |
| Siguiente handler | Tiene un contrato compatible y es el objeto realmente invocado |
| Petición | El forwarding conserva su identidad o una transformación autorizada |
| Decisión | Controla la llamada real de forwarding, no otra llamada del método |
| Resultado | Se propaga según el contrato, sin descartarlo o sustituirlo inadvertidamente |
| Atención exclusiva | Una ruta atendida localmente no llega además al siguiente |
| Topología | La cadena ensamblada y sus terminales son coherentes con el uso |
| Continuación | En middleware, orden y número de invocaciones se ajustan al contrato |

Una petición puede enriquecerse, copiarse o normalizarse legítimamente. “Misma
petición” debe parametrizarse como identidad estricta, origen de campos o relación
de transformación, según la búsqueda. Un contrato void tampoco obliga a retornar
el valor de `next`.

## IR objetivo

Notación de diseño, no nueva gramática KenQL ya implementada:

```text
function handle(%self, %request) {
  %eligible = call %self.can_handle(%request)
  %response = choose %eligible {
    yes {
      %local = call %self.process(%request)
      output %local
    }
    no {
      %next = memory.load (field.addr %self [field = following])
      %downstream = call %next.handle(%request)
      output %downstream
    }
  }
  return %response
}
```

Las regiones expresan la alternativa entre procesar y continuar. El IR debe
conservar el origen de `%request`, el receiver de forwarding y el resultado de
cada rama. Los temporales, logging de valores independientes y cálculos ajenos
no deberían romper esa correlación.

Una forma equivalente usa salida temprana:

```text
if %eligible { return call %self.process(%request) }
return call %next.handle(%request)
```

El forwarding está controlado por el fracaso de la decisión anterior aunque no
esté escrito dentro de un `else`. El matcher actual necesita todavía un modelo
más completo de dependencia de control para aceptar esa forma.

En middleware:

```text
%before = call @prepare(%request)
%response = await call %next(%request)
call @finalize(%before, %response)
return %response
```

`await` no convierte automáticamente una función en middleware. Hay que demostrar
la captura/provisión de `next`, el orden de ejecución y qué eventos ocurren si
hay excepción, cancelación o terminación anticipada. La query GoF actual no prueba
ese protocolo ni la invocación exactamente una vez de la continuación.

## Variantes por lenguaje

- **Python/Java/TypeScript:** handlers con campo `following` y método del contrato;
  son los tres lenguajes de la nueva matriz.
- **Java/C#/C++:** interfaz/base, variantes terminales y enlaces nullable. Requieren
  modelar el terminal sin asumir que `next` siempre existe.
- **Python/JS/TS:** closures y listas de handlers pueden representar la cadena sin
  subtipado nominal. Decoradores y captura de `next` necesitan flujo de closures.
- **Go/Rust:** funciones/traits, opciones y enums pueden codificar continuar o
  atender mediante valores en lugar de un campo nullable.
- **Web async:** handlers pueden suspenderse y reanudarse; resultado, error y
  cancelación forman parte del protocolo, no sólo la llamada `next`.

`middleware-closures` pasó a `ready` **sin cambio de IR** (el IR sigue en 1.60.0): la
captura de `next`, la rama y el retorno del resultado delegado ya estaban en el grafo,
incluida la expresión de cola de Rust vía `SYNTAX_NODE`. Queda un residuo **medido y
ejecutable**: una rama que delega en ambos desenlaces sigue matcheando, porque expresar
«este ramal no delega» exige clausura de cardinalidad sobre `HAS_CALL`, que KenQL no
declara (ver
[`chain#middleware-closures`](../../../structural-validation/gof-completion/chain-middleware-closures.md)).
Esta lista no significa que las formas no ensayadas ya sean detectadas.

## Pruebas y corrección

[`test_algorithm_chain_of_responsibility.py`](../../../../tests/structural/test_algorithm_chain_of_responsibility.py)
analiza handlers con petición numérica, procesamiento local con escritura de
estado, forwarding y respuesta. El ruido calcula/loguea números independientes
antes de decidir y dentro del brazo de delegación.

La primera ejecución reprodujo seis falsos positivos:

- Una llamada `following.audit()` era condicional, pero el forwarding
  `following.handle(request)` se ejecutaba incondicionalmente.
- El forwarding aparecía dentro de la **condición** del if, por lo que ya se
  ejecutaba para evaluar la decisión; no estaba protegido por ella.

La query ahora vincula `SYNTAX_NODE` de la llamada elegida con un brazo
`consequence`/`alternative` de una operación `branch`. Esto elimina la mezcla de
pruebas de llamadas diferentes y excluye llamadas en la propia condición. Reutiliza
hechos existentes; no cambia el motor ni compara nombres de patrones.

Resultado propio: **12 passed, 12 xfailed**:

- 6 positivos con/sin ruido, tres lenguajes.
- 6 negativos anteriores ahora rechazados.
- 9 expectativas pendientes de contratos más fuertes: petición reemplazada por
  constante, resultado de forwarding descartado y procesamiento local además de
  forwarding en una política de atención exclusiva.
- 3 falsos negativos de la forma válida con salida temprana local.

Los últimos doce casos son `xfail(strict=True)`, no éxitos de detección. Procesar
y continuar puede ser correcto para middleware; esos tres casos sólo son negativos
de la política explícita de atención exclusiva ensayada.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_chain_of_responsibility.py
```

Canónicos y propios: **27 passed, 348 deselected, 12 xfailed**. No se midió aquí
la repercusión del cambio sobre repositorios externos.

## Requisitos pendientes del IR y la búsqueda

1. Dependencia de control y salidas tempranas, manteniendo distinción entre
   condición, cuerpo y alternativas.
2. Correlación de argumentos y resultados de la invocación seleccionada, con
   políticas explícitas de transformación de petición.
3. Restricciones de rutas: exclusividad, terminación y ausencia de invocaciones
   posteriores del siguiente handler, sin confundir middleware legítimo.
4. Topología de enlaces/colecciones/closures, ciclos y terminales. Un solo handler
   con un campo no demuestra el ensamblado de una cadena completa.
5. Resúmenes de efectos y continuación asíncrona para permitir ruido independiente
   y reconocer cambios que sí alteran el algoritmo.

La firma sigue siendo un candidato: ni el nombre `Handler` ni un forwarding
condicional distinguen por sí mismos Chain of Responsibility de Proxy o Decorator.

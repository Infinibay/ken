# Template Method: esqueleto, slots y dependencia entre pasos

Estado: ejercicio algoritmo→IR con [21 pruebas nuevas](../../../../tests/structural/test_algorithm_template_method.py)
en Python, Java y TypeScript. La [regla del catálogo](../../../../src/ken/structural/patterns/template-method.toml)
reconoce una base con un algoritmo que llama un método sobrescrito. Las
obligaciones de receptor, orden y datos requieren contratos adicionales.

## Algoritmo en palabras

1. Una base define el esqueleto de un algoritmo y los puntos que una
   implementación puede reemplazar. Otros pasos permanecen concretos.
2. El algoritmo invoca esos puntos sobre la instancia que está ejecutando el
   esqueleto. La especialización aporta los pasos reemplazables.
3. Mantener el orden exigido por el algoritmo y las dependencias entre sus
   resultados. Por ejemplo, preparar un valor mediante un slot reemplazable y
   entregar ese resultado a un paso concreto que lo completa.
4. Admitir hooks opcionales con una implementación por defecto, incluso vacía.
   No exigir que cada hook sea sobrescrito para reconocer el patrón.
5. Permitir métricas o logging entre fases cuando respeten sus precondiciones,
   valores y efectos requeridos.

Un template puede ser `void`, usar varios hooks, ejecutar ramas o repetir un
paso. «Dos pasos con traspaso directo de resultado» es un refinamiento útil,
pero no la única forma válida del patrón.

## Traducción conceptual al IR

El texto expresa instrucciones y contratos objetivo; no es una gramática nueva
ejecutable del exportador.

```text
function Base.run(%self, %key) {
  call %self, slot: Base.before
  %prepared = call %self, slot: Base.first, argument[0]: %key
  %result = call %self, slot: Base.second, argument[0]: %prepared
  return %result
}

function Base.before(%self) {
  return
}

function Concrete.first(%self, %key) overrides Base.first {
  %prepared = binary.multiply %key, 2
  return %prepared
}
```

Los dos receptores de `first` y `second` deben corresponder a `%self` en este
contrato. Invocar `other.first(key)` no es un punto de extensión de la misma
instancia, aunque el destino estático tenga el mismo slot nominal.

La relación `%prepared` como argumento impone producción antes de consumo en la
expresión síncrona ensayada. Un requisito puramente de orden entre operaciones
independientes necesita evidencia de control; `CALLS` no la proporciona.

Si se guarda `%prepared` en una variable antes de consumirlo, hace falta
resolver qué definición alcanza la carga del argumento. Ese problema general
se documenta en [Facade](facade.md); no se soluciona comparando nombres locales.

## Firma y refinamientos

| Contrato | Evidencia | Negativo |
|---|---|---|
| Slot reemplazable | Relación entre método y override | Dos métodos concretos sin especialización observada |
| Mismo receptor del esqueleto | Receptor de llamada ligado a instancia base | Despachar el hook sobre `other` |
| Misma operación contenedora | Ocurrencias de llamada en ese cuerpo | Unir pasos hallados en métodos distintos |
| Resultado del primer paso consumido | Resultado→argumento | Llamar el hook y descartar su resultado |
| Orden requerido | Dependencia de datos o control alcanzable | Consumir un valor antiguo antes de producir el nuevo |
| Hook opcional | Slot con comportamiento por defecto | No es obligatorio que todo hook tenga override |

La ausencia de un override dentro del repositorio no prueba ausencia del
patrón en una biblioteca extensible: el cliente puede definirlo fuera de la
unidad analizada. La regla actual exige especialización observada y su cobertura
queda limitada por ese supuesto de mundo cerrado.

## Query refinada ejecutable

Las pruebas usan el siguiente `SavedRule` temporal, sin cambiar la consulta
general del catálogo:

```kenql
query template_dependent_steps {
 match "template-method"(unit:$unit);
 require $unit INSTANCE_RECEIVER $self;
 require $unit HAS_METHOD $template;
 require $unit HAS_METHOD $first_slot;
 require $unit HAS_METHOD $second_slot;
 require $override OVERRIDES $first_slot;
 require $template HAS_CALL $first;
 require $template HAS_CALL $second;
 require $first TARGET $first_slot;
 require $second TARGET $second_slot;
 require $first RECEIVER $self;
 require $second RECEIVER $self;
 require $first RESULT $value;
 require $second ARGUMENT $argument;
 require $argument VALUE $value;
 different $first_slot $second_slot;
 different $template $first_slot;
 different $template $second_slot;
 emit $unit,$template,$first,$second;
}
```

El refinamiento acepta `self.second(self.first(key))` y sus equivalentes Java/TS.
Ambas llamadas están en el cuerpo del template, apuntan a slots de la misma
base y reciben el receptor expuesto por `INSTANCE_RECEIVER`. El primer resultado
llega directamente al argumento del segundo.

La firma general continúa detectando los casos con `other.first(key)` y los que
descartan el resultado; el refinamiento los rechaza para este contrato. No se
endureció universalmente la regla: un patrón con pasos independientes puede
ser válido sin pasar este refinamiento de datos.

La consulta no prueba qué override se ejecutará para cada objeto concreto, ni
que todo camino del template invoque ambos pasos. El positivo ensayado usa una
expresión directa síncrona, sin ramas entre producción y consumo. Retornos,
excepciones, bucles y hooks que alteran estado requieren contratos adicionales.

## Variantes por lenguaje

| Lenguaje | Forma | Distinciones del IR |
|---|---|---|
| Python | Base nominal, ABC, mixins | Dispatch dinámico, MRO y hooks por defecto; `super` no es receptor arbitrario |
| Java | Método template y hooks abstractos/protected | Slots, posible `final` en esqueleto, covarianza y excepciones |
| TypeScript | Clase abstracta y métodos por defecto | Herencia nominal observada frente a estructura de callbacks |
| JavaScript | Prototipos o funciones hook inyectadas | Overrides frente a composición explícita, capturas |
| C# | Métodos abstract/virtual y template concreto | Override, métodos sealed y tareas async |
| C++ | Virtual hooks o CRTP | Dispatch dinámico frente a especialización estática y vida útil |
| Go | Función que recibe hooks/interfaz | Variante compuesta, no inventar una jerarquía de clases |
| Rust | Método default de trait | Resolución del slot implementado, genéricos y borrow |

`trait-default` y `composed-skeleton` siguen en diseño. Un algoritmo que recibe
callbacks puede compartir el esqueleto conceptual, pero no debe producir un
override nominal ficticio para entrar en la variante existente.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_template_method.py
```

Resultado: **21 passed**, sin xfail.

- Nueve positivos: baseline, ruido y renombrado en tres lenguajes, con hook por
  defecto no sobrescrito.
- Seis negativos refinados: receptor de otra instancia y resultado descartado.
- Tres negativos sin especialización observada.
- Tres negativos con llamadas independientes en orden inverso. Se rechazan por
  falta de la dependencia de datos requerida, **no** porque se haya implementado
  un análisis general de orden en esta entrega.

Los fixtures se parsean, no se ejecutan ni compilan. El logging de números no
cambia la colaboración ensayada; no prueba pureza de funciones arbitrarias.
Permanecen pendientes evidencia de ejecución entre regiones, efectos de hooks,
despacho por instancia y variantes sin herencia nominal. No hubo cambios al
motor ni al TOML de Template Method.

# Proxy: política que controla el acceso al sujeto

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[diseño de Proxy](../patterns/proxy.md) y la
[regla ejecutable](../../../../src/ken/structural/patterns/proxy.toml).

## Algoritmo en palabras

El cliente solicita una operación mediante un contrato. Un intermediario ofrece
ese contrato y decide cómo acceder al sujeto real. Para un proxy de protección,
evalúa una política: si permite la operación, invoca la operación correspondiente
del sujeto; si la rechaza, termina con un resultado de rechazo o una excepción.
La decisión debe controlar esa invocación concreta. Una condición que decide si
se imprime una métrica no protege una llamada posterior incondicional.

Un proxy virtual retrasa la creación/carga del sujeto hasta que una operación lo
necesita y usa después la misma instancia o almacenamiento resuelto. Un proxy
remoto traduce una operación del contrato a una llamada de transporte y mapea
argumentos, resultado y errores. Esos algoritmos no requieren necesariamente un
booleano allowed ni un if local: son variantes distintas, no fallos del diseño.

Un guard puede rechazar temprano y dejar el acceso permitido después del if.
También puede delegar la decisión en una función que lanza una excepción.
Reconocer esos casos exige control de flujo o un contrato de llamada; un nombre
check o authorize no basta para inferir que una llamada garantiza permisos.

## Roles e invariantes

| Rol o requisito | Evidencia requerida |
|---|---|
| Contrato visible | Proxy y sujeto son utilizables mediante la misma operación/slot |
| Sujeto real | Dirección de almacenamiento y valor del receiver de la llamada |
| Decisión | Valor de política y sucesores permitido/rechazado, con polaridad |
| Acceso controlado | La llamada pertinente se ejecuta sólo en el camino admitido para la variante de protección |
| Delegación | El target corresponde al slot solicitado; un método auxiliar sobre el mismo sujeto no alcanza |
| Resultado | Reenvío, transformación o rechazo según el contrato concreto |
| Argumentos | Procedencia de los argumentos y transformaciones permitidas; una política puede cambiar credenciales de forma legítima |

Una detección estructural no demuestra que la política sea correcta para el
negocio, que la información de autorización sea confiable ni que todas las
operaciones del contrato estén protegidas. Proxy y Decorator pueden coexistir;
condicionar una llamada tampoco resuelve por sí solo esa intención arquitectónica.

## Traducción al IR objetivo

Las instrucciones siguientes describen un contrato de protección. La anotación
policy es una obligación de la búsqueda, no una etiqueta inferida del nombre de
la variable. El texto es pseudocódigo de diseño, no nueva sintaxis KenQL aceptada.

```text
func request(subject, allowed, input) {
  %decision = slot.load @allowed
  if %decision {
    then {
      %target = slot.load @subject
      %argument = slot.load @input
      %answer = call %target.request(argument[0]=%argument)
      return %answer
    }
    else {
      %rejection = const denied
      return %rejection
    }
  }
}
```

La forma equivalente con rechazo temprano es:

```text
if (not %decision) { return denied }
%answer = call %target.request(%argument)
return %answer
```

En esa segunda forma, la llamada no está dentro de la región del if. El lenguaje
de búsqueda necesita poder afirmar que el camino hasta esa llamada implica la
decisión favorable; una relación de ancestro sintáctico no expresa ese requisito.
El núcleo con regiones, if, choose y short_circuit conserva más estructura para
analizarlo, pero exportar esas instrucciones no realiza por sí solo la prueba.

En contraste, `%decision = call %target.request(...)` usado como condición ya
accedió al sujeto para poder decidir. La llamada no está protegida por el branch
que consume su resultado. Es necesario distinguir región de evaluación de
condición de los brazos controlados por ella.

## Variantes por lenguaje

Estos esquemas indican requisitos del IR. La nueva matriz ejecuta Python, Java y
TypeScript; no certifica el resto de lenguajes o bibliotecas.

| Lenguaje | Implementación representativa | Requisito particular |
|---|---|---|
| Python | if allow: return subject.read(); decoradores o __getattr__ | Flujo del guard, exceptions y resolución dinámica de atributos |
| JavaScript | Wrapper, Proxy con trap get/apply | El trap puede cambiar receptor/argumentos; modelos de reflexión separados de clases nominales |
| TypeScript | Clase que implementa la interfaz del sujeto | Correspondencia de slots estructurales y tipos borrados en ejecución |
| Java | Interfaz, proxy dinámico, invocation handler | Dispatch reflectivo y contrato de excepciones/resultado |
| C# | Interfaz y método async que espera delegación | await y efectos concurrentes entre autorización y acceso |
| C++ | Wrapper con método virtual y puntero a sujeto lazy | Lifetime, ownership y misma instancia después de inicialización |
| Go | Struct que satisface interfaz y mantiene otro implementador | Satisfacción implícita de interfaz; contexto/cancelación que fluye al sujeto |
| Rust | Wrapper que implementa trait y presta o posee el sujeto | Borrow/move, async y construcción perezosa sin inventar identidad estable |

Un proxy puede devolver un iterador/generador. Autorizar la creación del iterador
no es lo mismo que autorizar cada lectura al consumirlo. Yield/await pueden
separar comprobación y acceso; una política que cambia con el tiempo exige un
contrato temporal diferente y posiblemente sincronización.

## Ruido, mutaciones y pruebas

El algoritmo debe sobrevivir a cálculos independientes y logging antes del guard
o dentro del brazo permitido. Las fixtures usan literales y métricas locales;
esto no convierte cualquier llamada llamada log en pura. Pasar el sujeto o una
credencial mutable a una función desconocida puede invalidar una prueba estricta.

[test_algorithm_proxy.py](../../../../tests/structural/test_algorithm_proxy.py)
parsea las fuentes y ejecuta la regla pública gof.proxy. No ejecuta el código
inspeccionado.

| Casos nuevos | Resultado | Interpretación |
|---|---|---|
| 18 positivos | Pasan | Ruido antes/dentro/ambos, con y sin renombrado, tres lenguajes |
| 9 negativos básicos | Pasan | Ausencia de guard, otro receiver o método auxiliar en lugar del slot solicitado |
| 3 guards prestados de audit | Pasan tras corregir query | La condición de otra llamada ya no justifica forwarding incondicional |
| 3 llamadas en condición | Pasan tras exponer role en IR | La query exige un brazo del branch y excluye su condición |
| 3 rechazos tempranos | xfail estricto | Variante válida no detectada por falta de control de flujo entre regiones |
| 3 caminos de bypass | xfail estricto | Falta contrato de protección en todos los caminos; no garantía de la firma amplia |

Los xfail conservan el resultado esperado y XPASS exige revisión. No se cuentan
como requisitos satisfechos ni como métricas de precisión en repositorios.
La nueva matriz y las regresiones Proxy del catálogo dieron **45 passed,
6 xfailed, 264 deselected** con:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_proxy.py tests/structural/test_gof_executable.py -k proxy
```

## Corrección realizada y límites

La query anterior combinaba CONDITIONAL_DELEGATION a nivel de método con una
llamada distinta cuyo nombre coincidía con el método del proxy. Esto aceptaba:

```text
if allowed { subject.audit() }
return subject.request()
```

La query final de IR 1.47 conserva relaciones existentes y añade el selector
del rol sintáctico, ahora expuesto en los hechos OPERATION:

```text
require $forward SYNTAX_NODE $forward_syntax;
path $forward_syntax SYNTAX_PARENT{0,32} $arm as $guard_scope;
operation(role: [consequence, alternative]) as $arm;
require $arm SYNTAX_PARENT $guard;
operation(kind: branch) as $guard;
```

La corrección liga un brazo del branch a la llamada forward concreta. El límite de
32 es el máximo actual de paths KenQL; mayor anidamiento queda fuera de esta
variante. Se expone el atributo role preservado del parser; no es una nueva prueba
de dependencia de control ni una regla especial de Proxy en el motor.

Esto corrige mezcla de ocurrencias, pero aún es una condición léxica. No prueba
polaridad, factibilidad ni ausencia de caminos que eluden el guard. Los nuevos
xfail impiden confundir esa mejora con una solución completa de control de acceso.

El selector role permite distinguir la condición del brazo sin exigir
BRANCH_TRUE/FALSE, que sólo se emiten para ciertos tests de verdad/null. El nombre
del rol es el campo del AST nativo: no sustituye un CFG ni inventa semántica de
autorización. Un brazo alternative también puede delegar legítimamente.

El siguiente paso del IR es representar y consultar dependencia de control sobre
la ocurrencia de llamada, incluyendo salida abrupta previa y contratos de calls
que pueden rechazar. Después se necesitan relaciones entre slots virtuales,
proveniencia de argumentos/resultados, y estado del sujeto entre check y use.
Las variantes lazy y remote del catálogo siguen en estado de diseño.

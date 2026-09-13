# State: transiciones iniciadas por el objeto de estado

Estado: implementado en IR 1.29.0. La [auditoría externa](../../structural-validation/multilanguage/state-context-transitions.md) registra validación y ambigüedades.

El ejemplo Order (TypeScript, across-languages) instala NewOrderState(this), delega
acciones a IOrderState y expone setState(s). Los estados conservan el contexto y
llaman order.setState(new PendingPaymentState(order)). La firma actual sólo ve
construcciones realizadas dentro del método del contexto que escribe el estado;
no une el argumento construido por un colaborador con ese setter.

## Criterio de la nueva variante

`context-transition` exige una construcción inicial almacenada en el slot de
estado, que recibe el receptor del contexto y lo guarda en un campo del estado.
Una acción del estado concreto debe corresponder al slot de método usado por el
dispatch del contexto. Esa acción invoca, mediante el campo de contexto retenido,
un método del contexto que almacena su parámetro directamente en el mismo slot
de estado. El argumento explícito de esa llamada debe construir un estado distinto
con el mismo contrato nominal. Los bindings se correlacionan por llamada y parámetro.

No basta un setter de Strategy ni configurar un objeto nuevo desde código cliente.
Tampoco basta construir otro estado sin instalarlo, escribir otro campo, cambiar
otro contexto recibido o realizar la transición desde una operación no delegada.
Un State puede seguir coincidiendo con Strategy: ambas interpretaciones deben
conservar evidencia y no se suprimen por nombre ni por etiqueta del directorio.

## Primitivas generales necesarias

- `INSTANCE_RECEIVER`: tipo → valor receptor relativo al tipo. Es el valor fuente
  que ya usa el frontend para `this/self`; no identifica un objeto runtime ni
  unifica todas las instancias. Se emite al observar usos del receptor de instancia.
- Parámetros-propiedad TypeScript: `constructor(public/private/protected/readonly
  context: Context)` declara dos entidades distintas, parámetro y campo, con el
  mismo nombre. `PARAMETER_INITIALIZES_FIELD` relaciona parámetro → campo y conserva
  evidencia de la sintaxis. La anotación pertenece a ambos. Un parámetro ordinario
  o un modificador en el texto de un comentario/default no declara un campo.
- `CONSTRUCTOR_FIELD_INPUT`: campo → parámetro explícito de su constructor,
  `basis=linear-syntax`. El modelo lineal considera primero las
  inicializaciones implícitas TypeScript y luego las escrituras del cuerpo. Una
  sobrescritura elimina la entrada anterior; no se confunde una inicialización
  sintáctica con el valor final del campo al salir del constructor.

No se crean statements ficticios de asignación dentro del AST/CFG para representar
los parámetros-propiedad. Las relaciones declaran su propio origen. No se modelan
parámetros-propiedad en firmas sin implementación ni propiedades arbitrarias C#.

## Validación requerida y límites

Se probaron Python, JavaScript con herencia nominal, TypeScript, Java y C#, con
campos explícitos y, en TypeScript, parámetros-propiedad. Positivos renombrados y
negativos cercanos deberán cubrir llamada/slot/campo/contexto/argumento incorrectos,
construcción abandonada, falta de dispatch, sobrescrituras y parámetros ordinarios.
El corpus externo y los proyectos reales se repetirán sobre las mismas fuentes.

La variante describe una estructura de transición; no prueba reachability de todas
las ramas, cierre del despacho dinámico, identidad de objetos entre todos los
callers, ni estabilidad global del campo retenido frente a escrituras posteriores,
aliases, reflexión o threads. Requiere constructores explícitos únicos y un setter
con transferencia lineal soportada. Enum/match, transiciones directas a campos,
herencia de constructores y funciones/closures de estado requieren otras variantes.

## Separar contrato nominal de destinos posibles

El probe mostró además que el campo anotado IOrderState acumula NewOrderState
como tipo posible por su inicialización. `TARGET` conserva ambas posibilidades y
queda ambiguo. No se debe escoger un destino runtime para hacer pasar la query.
Se añadió `DECLARED_TARGET` (llamada → método único del tipo anotado del receptor),
con `basis=nominal-annotation`: expresa el slot del contrato, sin reemplazar TARGET
ni eliminar MAY_TARGET. La query aceptará ese slot y su implementación OVERRIDES.
Las sobrecargas homónimas del contrato no reciben un DECLARED_TARGET único.

La interpretación de parámetros-propiedad se contrasta con la
[documentación oficial de TypeScript](https://www.typescriptlang.org/docs/handbook/2/classes.html#parameter-properties):
el modificador del parámetro constructor declara e inicializa un campo con el
mismo nombre. No se infiere esa semántica a partir de texto libre en el cuerpo.

## Variante dinámica dentro del mismo recorrido

En JavaScript, retener el argumento `this` en el constructor prueba una conexión
estructural con el contexto aunque el campo no tenga anotación para resolver
TARGET. Para ese caso se admite una llamada sin resolver sobre el mismo campo
retenido, con el nombre del setter del contexto y su único parámetro explícito.
El primer argumento debe ser posicional y la construcción de sucesor debe ser su
valor directo. Un spread, otro receptor, otro nombre o un setter de varios parámetros
no usa esta alternativa. La evidencia previa de construcción/retención sigue siendo
obligatoria; no es reconocimiento de setters por nombre aislado. No se generaliza
esta regla a resolución global de llamadas ni a monkey patches.


La asignación inicial almacenada es evidencia sintáctica: esta variante aún no
comprueba que sea la última escritura antes del primer dispatch. Un reemplazo
posterior o una inicialización en un camino que no se ejecuta puede mantener un
candidato. Tampoco se prueba que el campo del contexto retenido permanezca intacto
durante toda la vida del estado. Estos límites son distintos de la correlación de
argumentos y de las sobrescrituras dentro del setter/constructor modelado.

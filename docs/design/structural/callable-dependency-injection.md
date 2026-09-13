# Inyección de dependencias funcionales

Estado: implementado y verificado en IR 1.40.0. Este diseño se escribió antes
del cambio; los resultados están en la [auditoría](../../structural-validation/multilanguage/callable-dependency-injection.md).

Flask ScriptInfo recibe create_app en su constructor y la llama desde load_app.
ConfigAttribute recibe get_converter y la llama desde __get__. Ambas son
colaboraciones suministradas por el cliente sin un método invocado sobre el campo.
La regla anterior sólo seguía DELEGATES_TO y omitía esas dos formas.

## Variantes y composición

La regla architecture.dependency-injection conserva sus roles unit, dependency,
inject y operation. Su consulta canónica une dos variantes en el mismo TOML:

- object-assignment: la consulta anterior, con campo escrito desde un parámetro
  del configurador y otro método que delega en ese campo. Conserva evidencia de
  asignación histórica; no garantiza que el parámetro sobreviva a escrituras
  posteriores ni que todos los caminos lo almacenen.
- callable-input: reutiliza strategy.supplied_policy para una última escritura
  fuente directa, o inicialización final de constructor soportada. Otro método
  llama al campo mismo, mediante CALLEE_VALUE. No requiere nombres de factory,
  converter, callback o proveedor ni que el callable pertenezca a un framework.

La operación pública pertenece a un patrón pero puede usarse desde reglas de
arquitectura: las colecciones no cambian la ejecución. La consulta por sí sola
reutiliza los hechos existentes; el siguiente problema de lowering exige además
una revisión del IR y la invalidación de su caché.

## Binding invocado entre paréntesis

Rust requiere `(self.callback)(value)` para invocar un campo de tipo función.
El IR ya conserva el input escrito, pero no emitía CALLEE_VALUE al envolver el
callee en paréntesis. Ahora se preserva ese binding en identificadores, miembros e
indexaciones envueltos únicamente en parenthesized_expression, ignorando comments
entre esos paréntesis. Se conserva el nodo sintáctico completo.

No se borran casts, operadores de dirección/desreferencia, tuplas, secuencias,
condicionales o suspensión para inventar un único binding. INVOKES_RESULT_OF
continúa distinguiendo invocar el resultado de otra llamada. Esta ampliación no
promete resolución nominal de métodos ni binding de receiver para todos los
miembros parentizados: CALLEE_VALUE identifica la expresión llamada, sin resolver
su implementación runtime. IR_VERSION pasa a 1.40.0 porque cambian los hechos.

C# tiene una distinción sintáctica relevante: `(callback)(value)` se clasifica
como cast cuando callback es un identificador, sin consultar si denota un tipo.
`((callback))(value)` sí ofrece la forma de invocación probada. No se reinterpretan
casts para satisfacer las pruebas; ver la [regla de desambiguación de C#](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/language-specification/expressions#1298-cast-expressions).
La gramática también clasifica `(callbacks[0])(value)` como cast/array-type;
queda registrado como límite del parser. La indexación con doble paréntesis
sí conserva el binding en las pruebas. No se cuenta esa ausencia como TN.

La nueva variante describe suministro y uso de una función como colaboración.
Incluye generadores de objetos, conversores y políticas. Puede coincidir con
Strategy; los patrones no son categorías excluyentes. No demuestra contenedor DI,
lifetimes, orden temporal entre configuración/uso ni identidad runtime del callable.
Los descriptores Python mantienen evidencia de escritura fuente, sin garantía
de que conserven el mismo valor. Una función que se construye localmente o un
binding escrito y después reemplazado no proporciona el input final requerido.

## Límite de la variante por objeto

Un probe con la restricción lineal aplicada a toda la regla perdería AppContext.app,
AppContext._request y BlueprintSetupState.app de Flask. Sus configuradores tienen
ramas o estructuras fuera del pase. Por eso no se atribuye a object-assignment
la garantía más fuerte de callable-input. Antes de corregir sus asignaciones
históricas hay que ampliar el análisis de flujo o representar resultados parciales
de forma consultable. El probe y las pérdidas potenciales están guardados como evidencia.

## Validación realizada

Fuentes propias en Python, JS, TS, Go, C#, C++ y Rust para callables almacenados;
Java mediante la llamada al método de una interfaz funcional en la variante
por objeto. Positivos por renombrado, escrituras anteriores, constructor,
invocación anidada/async soportada, distintos argumentos y argumentos variádicos
cuando la gramática los conserva. Negativos por input/field sobrescrito, invocación
de otro campo, callback almacenado sin uso, construcción local y uso en el mismo
método sin separación entre configuración y operación.

La misma matriz de 98 fuentes contra el catálogo anterior recupera 49 FN y
conserva 49 TN. Los tests verifican el aislamiento de los roles públicos y los
escaneos conservan todas las coincidencias anteriores. Se revisaron en fuente
cuatro TP estructurales añadidos en Flask y RxJS. Los 281 ejemplos GoF no cambian.
La suite pasa 4.938 tests; se verificaron presupuesto de consultas y wheel fuera
del checkout. Los resultados y límites se detallan en la auditoría enlazada arriba.

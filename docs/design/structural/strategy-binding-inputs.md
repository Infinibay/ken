# Strategy: entradas escritas y slots de contrato

Estado: contrato implementado en IR 1.39.0; diseño escrito antes del cambio.
Ver [auditoría y límites](../../structural-validation/multilanguage/strategy-binding-inputs.md).

La firma anterior aceptaba cualquier ASSIGNED_FROM histórico del campo. Por eso
`policy=input; policy=null` conservaba un Strategy candidato, igual que un input
reasignado antes de almacenarlo. En objetos, DELEGATES_TO tampoco exigía que la
llamada usada pertenezca al contrato del campo. Estos errores de correlación
son distintos de la ambigüedad de intención entre algoritmos y otros colaboradores.

## Última entrada sintáctica de un binding

FINAL_BINDING_INPUT enlaza la operación de última asignación con un parámetro
explícito del mismo callable. El destino se consulta mediante ASSIGNMENT_TARGET.
El parámetro no puede tener una reasignación explícita en el cuerpo. Sólo se
consideran escrituras antes del primer return en cuerpos lineales soportados;
ramas, bucles, excepciones, suspensión, escritura indirecta no modelada y ámbitos
dinámicos mantienen un estado unsupported. Una escritura posterior al binding
elimina el input anterior; una escritura anterior no lo elimina si luego se
escribe directamente el parámetro.

La revisión de fuentes también encontró declaraciones sin valor clasificadas
como ASSIGN sin operandos, bloqueando el pase: declaradores JS/TS/Java/C#,
anotaciones Python sin asignación y let de Rust sin inicializador. Se clasifican
como DECLARATION cuando no tienen value/right ni un token de asignación escrito.
El token también protege los inicializadores C# cuyo valor no tiene field name.
Esto distingue ausencia de asignación explícita de una asignación no modelada;
no modela inicialización implícita a undefined, TDZ ni validez del programa.

El pase reutiliza el recorrido de transferencias de miembros y cubre destinos
STORAGE, PARAMETER o accesos MEMBER_OF ya resueltos. BINDING_FLOW_STATUS separa
su disponibilidad del resumen de miembros. FINAL_MEMBER_INPUT mantiene su
contrato anterior y no se extiende a campos static por esta incorporación.
La evidencia usa basis=linear-syntax y analysis=linear-bindings/1.

FINAL_BINDING_INPUT certifica una última escritura fuente, no la identidad del
valor almacenado por un descriptor, setter o proxy ni el estado posterior del
heap. Esto permite describir Python `self.policy=input` cuando policy tiene un
descriptor de clase sin inventar una transferencia directa al campo. El caso
Order de python-patterns necesita exactamente esa distinción. Tampoco demuestra
pureza ni ausencia de mutaciones ocultas por llamadas o aliases.

## Operación pública y consultas Strategy

`strategy.supplied_policy` expone unit, configure, supplied y policy. Correlaciona
campo, método configurador y parámetro de ese mismo método. Exige una escritura
FINAL_BINDING_INPUT al campo o una entrada CONSTRUCTOR_FIELD_INPUT soportada
(incluye parámetros-propiedad TypeScript e inicializadores explícitos C++).
Es reutilizable para consultas de políticas, callbacks o dependencias; por sí
sola no exige una llamada ni prueba intención Strategy.

Los joins comienzan en FINAL_BINDING_INPUT/CONSTRUCTOR_FIELD_INPUT y luego
correlacionan owner y campo. Enumerar campos, métodos y parámetros antes de
comprobar las escrituras produjo una combinación intermedia que agotó 100.000
estados en Commons IO. El presupuesto se conserva; se evita esa combinación
por el orden de los hechos, sin cambiar los bindings aceptados.

La variante por objeto exige además una llamada sobre ese mismo campo desde
otro método y un slot perteneciente al contrato nominal del campo, mediante
DECLARED_TARGET o TARGET. Un despacho con varios MAY_TARGET conserva su slot
declarado; no se exige elegir una implementación runtime única. Se conserva
el requisito actual de dos subtipos observados y su limitación para extensiones
externas. La variante callable exige CALLEE_VALUE del mismo campo desde otro
método. No se exige un nombre de clase, método, directorio, retorno ni cantidad de
argumentos particular. La política puede ejecutarse dentro de una rama o bucle:
la restricción lineal se aplica a su configuración, no a todo el consumidor.

Los cinco FP de intención C++ registrados en IR 1.38 pueden seguir cumpliendo
estas relaciones. No se añaden exclusiones por categorías ni una promesa de
exactitud de intención. La siguiente evidencia necesaria sería el papel del
algoritmo en el cliente; incluso entonces pueden existir usos con varios patrones.

## Validación

Antes/después sobre las mismas fuentes: objetos en Python/TS/Java/C#/C++ y
callables en Python/JS/TS/Go, con renombrado, escrituras anteriores/posteriores,
rebindings, returns, campos incorrectos, llamadas fuera del contrato y cuerpos
no lineales. El pase de bindings tiene casos en las ocho gramáticas, incluyendo
destinos locales, campos static y casos sin hechos. Se preservan el descriptor
Order, los Commands/Decorators/Bridge/Interpreter ambiguos documentados y los
positivos Strategy existentes. Se revisó cada cambio del corpus abierto y de
los alcances reales, con tiempos de consultas y verificación del wheel.

La matriz controlada de 113 fuentes pasa de 45 TP/22 TN/46 FP/0 FN a
45 TP/68 TN/0 FP/0 FN. No estima precisión global: los cinco FP de intención
C++ de 1.38 permanecen. Las pérdidas por configuración no lineal o slots
sobrecargados sin resolver se registran como límites de cobertura, sin contarlas
como TN demostrados.

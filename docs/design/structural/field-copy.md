# Prototype por asignaciones posteriores a la construcción

**Estado: implementado en IR 1.26.0**, variante `prototype#field-copy`, para
Python, JavaScript, TypeScript, Java y C#. La
[guía operativa](../../structural-ir.md) incluye una query ejecutable.

El caso real de Requests crea PreparedRequest vacío, copia campos de self y
devuelve la instancia nueva. Una query que solo inspecciona argumentos del
constructor no puede reconocerlo. La identidad de la asignación local debe
conservarse aunque haya escrituras a miembros de ese objeto.

La extensión del análisis de retornos permite escrituras simples a miembros
de bindings locales sin confundirlas con reasignaciones del binding. Además
retiene el último write explícito de cada campo de una asignación nueva que
llega a un retorno. Los estados se separan por identidad de asignación y campo;
se conservan en estados separados por rama y no salen de ramas terminadas por
return. El join no debe mezclar el objeto devuelto en una rama con campos
escritos únicamente en otra. Hay un límite de 256 estados y 100.000 unidades
de trabajo, además de profundidad 32; excederlo emite estado unsupported, sin
evidencia parcial de retornos o campos para ese callable. Los métodos que no
escriben miembros mantienen el dominio de locales con joins para evitar el
costo de enumerar ramas cuando no se necesita esta correlación.

Relaciones públicas: `RETURN_FIELD_STATE` une el retorno con un estado de campo;
`FIELD_STATE_ORIGIN` identifica la asignación nueva y `FIELD_STATE_WRITE` su
última escritura explícita. El nodo intermedio conserva correlación entre
retorno, objeto y escritura. No se cruzan evidencias de objetos distintos ni de
ramas que ya terminaron. Una sobrescritura posterior reemplaza la anterior.

La primera variante de Prototype exige retorno de una asignación del
mismo tipo y copia de al menos un campo de la instancia origen al campo homónimo
de la nueva instancia. No se prueba copia completa/profunda ni igualdad runtime.
Las asignaciones que escapen como argumentos o receptores de llamadas se
excluyen conservadoramente de la evidencia de campos, junto con otros usos
opacos (contenedores, publicación en campos, expresiones no modeladas). Los
aliases locales propagan esa exclusión, incluso si el uso es anterior a la copia
o inalcanzable. El origen del retorno
puede seguir siendo conocido. No se modelan setters, reflexión ni heap general.

Los tests cubren aliases, reasignación del objeto, sobrescritura de campos, copias en
ramas que no alcanzan el retorno, constantes, otro tipo, campos de otro objeto,
escape a helpers, ternarios en valores de campos y varias formas de lenguaje.
Los ternarios se admiten sólo dentro del RHS de una escritura de campo
soportada: su valor permanece opaco, sin convertirlo en un origen preciso.

`RETURN_FIELD_STATE` tiene modalidad `must` si esa tupla de retorno, asignación,
campo y escritura aparece en todos los estados modelados que alcanzan el retorno.
Si aparece sólo en algunos, es `may` y se consulta con `--evidence-mode possible`.
No se prueba factibilidad de condiciones ni correlación entre tests repetidos.
Dos ramas que escriben el mismo campo con operaciones distintas generan testigos
alternativos; no se fusionan para fabricar una escritura única.

La corrección incluye dos problemas de identidad del frontend: una anotación
Python sin valor no inicializa un atributo de clase, y una declaración local con
el nombre de un campo no debe resolverse a ese campo. Las asignaciones de clase
con valor y el spelling explícito `ClassVar[...]` conservan su clasificación
estática. No hay resolución general de aliases de typing ni de bloques léxicos.

Quedan pendientes copias de valores de campo a través de temporales, setters y
descriptors, copias completas/profundas, constructores de copia de otros lenguajes,
retornos implícitos y protocolos externos. La variante `explicit-copy` anterior
conserva sus límites de flujo de argumentos; esta extensión no la convierte en
un análisis preciso de todos los caminos.

# Métodos C++ y contratos virtuales

Estado: contrato implementado en IR 1.37.0; validación detallada en la
[auditoría](../../structural-validation/multilanguage/cpp-method-contracts.md).

Un método declarado sin cuerpo es una entidad consultable, aunque no tenga flujo
de ejecución. `virtual Product *make() = 0;` debe exponer nombre, owner, parámetros,
tipo de retorno escrito y carácter virtual/puro. Se debe distinguir de un campo
`Product *(*callback)()`. Cada sobrecarga conserva identidad propia por ubicación;
una declaración múltiple conserva cada método. No se inventa un cuerpo ni CFG.

El mismo contrato se aplica a definiciones inline. Los metadatos separan cuerpo
disponible, modificador virtual escrito, override/final y cualificadores cv/ref.
Los parámetros conservan nombres cuando existen, defaults y tipos abstractos con
punteros/referencias. Un parámetro anónimo sigue siendo un parámetro; no debe
convertir el nombre del tipo en una variable declarada.

Incorporar esos slots obliga a corregir OVERRIDES en C++: un nombre coincidente
no basta. El enlace necesita una cadena nominal resuelta, un slot virtual y una
firma compatible de parámetros y cualificadores del receptor. La virtualidad
se hereda aunque la implementación no repita `virtual` ni `override`. Los métodos
estáticos y constructores no participan. Nombres de parámetros y defaults no
forman parte de esa comparación. Se conserva la cualificación del objeto apuntado;
la cualificación de nivel superior de un parámetro por valor no distingue firmas.

La comparación es conservadora: tipos primitivos modelados y nominales locales
resueltos, punteros/referencias y arrays de parámetros con ajuste a puntero.
Tipos no resueltos, sustitución de templates, punteros a función y casos complejos
de declaradores tienen un estado explícito de firma no disponible. No se adivinan
aliases ni nombres externos. La firma no selecciona overloads de llamadas.

`METHOD_SIGNATURE_STATUS` declara supported/unsupported por callable con
`analysis=cpp-virtual-signatures/1` y reason. `VIRTUAL_METHOD` enlaza el slot
virtual soportado con su clase; OVERRIDES conserva
`basis=cpp-resolved-virtual-signature`. Los cuerpos que no repiten virtual pueden
heredar esa propiedad mediante una firma compatible. Destructores y miembros
de clases template conservan entidades pero quedan fuera de esta comparación.
`declaration_only` significa que no existe cuerpo escrito, también para métodos
defaulted/deleted; no es una clasificación completa de definiciones según C++.

TYPE_HEAD/TYPE_HEAD_STATUS se aplican también a parámetros C++: conservan un head
nominal simple tras quitar cualificadores y a lo sumo una indirección. Se mantiene
el tipo escrito completo en native_type/TYPE_REF. Un puntero doble, un array o un
nombre cualificado no se resuelven como receptor escalar por eliminar símbolos.
Ese head sintáctico no sustituye la resolución de nombres ni parámetros template.

OVERRIDES describe correspondencia estructural bajo las reglas soportadas,
no certifica que el programa C++ sea válido: las restricciones de retorno
covariante, accesibilidad, noexcept, final y deleted necesitan validación adicional.
No se fusionan todavía declaraciones con definiciones fuera de la clase ni se
expanden macros. Las listas de inicializadores quedaron fuera de IR 1.37;
IR 1.38 incorpora un [modelo acotado](cpp-constructor-initializers.md).

La evaluación debe incluir firmas virtuales puras y no puras, implementaciones
inline, cadenas de herencia, sobrecargas con tipos y cv/ref distintos, métodos
estáticos/no virtuales que ocultan nombres, defaults, parámetros anónimos,
callback fields y declaraciones múltiples. Los tests de patrones deben ejercitar
Adapter, Factory Method, Abstract Factory, Interpreter, Template Method y Visitor
por nombre con mutaciones negativas, más regresiones de los otros lenguajes.
El corpus abierto se compara archivo por archivo y cada coincidencia
nueva o perdida se revisa; un nombre de carpeta no prueba intención.

Referencias del contrato: [funciones virtuales](https://eel.is/c++draft/class.virtual)
y [declaradores de función](https://eel.is/c++draft/dcl.fct) en el borrador de C++.

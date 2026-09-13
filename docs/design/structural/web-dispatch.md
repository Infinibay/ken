# Despacho heredado y adaptación de handlers

Extensión implementada IR 1.23.0, motivada por Flask: registro en un método base,
selección por miembros de un contexto y ejecución del resultado de un adaptador.

`EFFECTIVE_METHOD` relaciona una clase con sus métodos visibles en una cadena
de herencia simple resuelta. Los overrides sustituyen la definición base. No se
resuelven MRO múltiple, mixins dinámicos ni bases desconocidas por nombre global.
`INSTANCE_SLOT` relaciona accesos self/this al mismo slot nominal heredado en
Python/JS/TS. Representa una ubicación relativa a una instancia del tipo, no la
identidad de todos los objetos de esa clase. Campos estáticos, privados léxicos y
descriptores/métodos homónimos no se unen a un slot público ancestral.

`ACCESS_INPUT` relaciona un acceso a miembro con el parámetro del que parte,
conservando los pasos de acceso y las asignaciones locales en la evidencia. Se
siguen aliases únicamente mediante una escritura simple anterior en una
secuencia contenedora. No se cruzan campos de heap, llamadas arbitrarias,
destructuring, reasignaciones ni escrituras implícitas de bucles. Es procedencia
sintáctica, no prueba de que un getter preserve valores ni de estabilidad entre
lecturas o frente a concurrencia.

La query de despacho conserva correlación entre tabla registrada y tabla
consultada. El adaptador debe resolverse a un callable con evidencia de retorno
del parámetro recibido o de una llamada que recibe ese parámetro, mediante
`RETURN_ORIGIN` del análisis de retornos. Es evidencia de una ruta posible;
no certifica todas las ramas ni la semántica de la llamada adaptadora. No se infiere
identidad incondicional del adaptador. Su resultado debe invocarse en el método
de despacho. Los nombres del framework no forman parte de la firma.

Los tests cubren registro heredado, override de métodos, tablas homónimas no
relacionadas, múltiples bases, miembros privados, claves derivadas y aliases
sobrescritos, adaptadores que descartan la entrada y resultados no invocados,
en varios lenguajes. Flask se analiza como fuente, sin ejecutarlo.

La investigación también corrigió pérdida de información en argumentos Python:
el campo `value` de un subscript designa su contenedor, no el argumento completo.
Solo los wrappers de argumento se desenvuelven de esa forma. C++/C#/Rust tienen
proyecciones explícitas para su gramática de índice único; las formas multi-índice
siguen preservadas como sintaxis, sin fingir un solo índice.

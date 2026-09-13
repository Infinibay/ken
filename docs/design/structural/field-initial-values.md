# Valores iniciales de campos

Estado: implementado y verificado en IR 1.45.0. Diseño previo al código;
ver [auditoría](../../structural-validation/multilanguage/field-initial-values.md).

Los dos FN Java documentados en IR 1.44 requieren distinguir inicialización
implícita de ausencia de información, sin fabricar operaciones ASSIGNMENT.

FIELD_DECLARATION conecta un slot con su nodo declarador real, incluyendo
native_type y la modalidad explicit/implicit/absent. El estado supported/unsupported
del declarador y FIELD_INITIAL_STATUS son independientes de esa modalidad.
type_parameters conserva los nombres genéricos de los ámbitos envolventes para
evitar confundirlos con clases nominales; no resuelve sus constraints. Sólo se admiten
declaradores directos del cuerpo de una clase, no locales, referencias al campo,
propiedades, eventos o asignaciones dentro de métodos/bloques estáticos.
FIELD_INITIAL_STATUS y FIELD_INITIAL_VALUE describen el valor al completar ese
declarador. No prueban el estado después de inicializadores posteriores, ejecución
de constructores, setters o reentrancia. Declaraciones repetidas del mismo slot
son unsupported, sin elegir arbitrariamente una ocurrencia.

Un inicializador explícito reutiliza su operando fuente; una declaración sin
inicializador se interpreta por lenguaje. Java: referencias/arrays null, boolean
false, char U+0000 y números cero. C#: palabras clave primitivas, referencias
string/object/dynamic y arrays; tipos nominales sólo si el enlace demuestra una
clase/interface de referencia, no por su nombre. Nullable de primitivos admite
null; genéricos/value types no resueltos quedan unknown. Java no confunde
primitivos con sus wrappers; dimensiones escritas junto al nombre son arrays.

JS nativo sin inicializador usa UNDEFINED, nunca NULL. TS sin inicializador
queda unsupported sin una política de emisión conocida (useDefineForClassFields).
Campos declare/abstract TS
son declaraciones sin inicialización runtime. Una anotación Python aislada no
asigna el atributo. Python y JS/TS con inicializador conservan el valor explícito.
No se inventan defaults para C++, Rust, Go o locales.

Los valores primitivos implícitos son entidades VALUE sintéticas con tipo,
valor literal y basis=language-field-default; no tendrán operación de asignación.
NULL/UNDEFINED son extremos distintos. La vista de consulta debe conservar esta
separación. Errores de parsing impiden publicar un inicializador conocido.

singleton.lazy_instance usa FIELD_INITIAL_VALUE NULL con status supported en
vez de exigir una asignación explícita. Se conservan sus restricciones de flujo.
Así se recupera Java/C# sin atribuir null a campos JS/TS ni a anotaciones Python.
No se inferirá null para un campo con inicializador explícito distinto.

Validación: matriz de defaults en varios lenguajes y tipos, declaraciones múltiples,
dimensiones Java por declarador, null explícito, overrides, locales, métodos,
campos TS borrados, errores, roundtrip, consultas y Singleton positivos/negativos.
Revisar los FN externos y cualquier match nuevo de corpus/producción.

Referencias: [defaults C#](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/builtin-types/default-values),
[emisión de campos TS](https://www.typescriptlang.org/tsconfig/useDefineForClassFields.html),
[defaults Java](https://docs.oracle.com/javase/specs/jls/se17/html/jls-4.html#jls-4.12.5).

La verificación pasa 5.709 tests y mypy en 103 archivos. La matriz recupera
14 FN y elimina dos coincidencias sobre declaraciones duplicadas. Cinco fuentes
externas originales recuperan su match; la presencia por directorio sube a 74/281,
sin pérdidas. El mapa de tipos declarados se mantiene separado de TYPE inferido
por escrituras posteriores para decidir defaults C#.

# Acceso a constructores y Singleton eager restringido

Estado: implementado y verificado en IR 1.43.0. El diseño precedió al código;
ver [auditoría](../../structural-validation/multilanguage/restricted-eager-singleton.md).

IR 1.42 conserva correctamente valores bajo aserciones TS, pero expone un falso
positivo de intención: Notification de RxJS comparte COMPLETE y permite crear
otras notificaciones. No debe deshacerse la normalización de valores.

## Separar evidencia reutilizable y patrón

`singleton.shared_instance` conserva su contrato y roles. La variante canónica
`singleton#eager-shared` añade dos requisitos: un inventario soportado de
constructores explícitos de instancia, todos privados, y un único sitio de
creación resuelto a esa clase en el grafo analizado. Es una firma
de construcción restringida en Java, C# y TypeScript, no unicidad runtime.
JavaScript sin restricción de constructor sigue disponible por la operación
amplia, pero no por esta variante. No se cambia lazy-guarded: su garantía sigue
siendo otra firma estructural, y necesita una revisión independiente.

## Contratos genéricos del IR

Los callables miembros de Java/C#/TS exponen `visibility`, `visibility_basis`
y `visibility_status`. Se leen tokens nativos de modificadores, sin buscar
palabras en comentarios, anotaciones, cadenas o parámetros-propiedad. Los
constructores explícitos sin modificador tienen acceso package en Java, private
en C# y public en TS. Un constructor estático C# no crea instancias.

`CONSTRUCTOR_INVENTORY` conecta una clase con estado supported/unsupported;
contiene counts de declaraciones explícitas de instancia, privadas y otras.
No se creará una entidad ficticia para un constructor implícito: explicit=0
no satisface la firma. Se enumeran firmas de sobrecargas TS, no sólo la última
entrada por nombre. Clases C# partial o con constructor primario, records y clases
con errores de parsing tienen inventario unsupported. El inventario no prueba
que un programa compile ni analiza generadores de código o reflexión.

`RESOLVED_ALLOCATION_COUNT` contiene la cantidad de sitios CALL distintos con
ALLOCATES_TYPE hacia la clase en el grafo analizado, no instancias creadas durante
la ejecución. Incluye otros métodos, clases anidadas y archivos enlazados. Su
basis indicará explicit-resolved-sites: constructores invocados mediante aliases,
reflection, serialización, clonación y fuentes fuera del grafo no se cuentan.
No se publicará la cifra como cierre global de ALLOCATES_TYPE. La consulta exige
count=1 y la operación compartida ya vincula ese sitio con el inicializador.

No se infiere sincronización ni inmutabilidad del almacenamiento. Un único sitio
puede ejecutarse más de una vez por loader o evaluación del sitio de definición.
La restricción private TS pertenece al chequeo de tipos, no a una barrera runtime.

## Validación y evidencia

Matrices en Java/C#/TS: renombrado, comentarios, anotaciones, sobrecargas privadas,
constructor público/protected/default/ausente, constructor estático separado,
constructor primario/partial, múltiples inicializadores, factory y reset con otra
creación. La operación amplia debe conservar sus resultados. Pruebas genéricas
de visibilidad e inventarios, parsing con errores, roundtrip, consultas nombradas
y presupuestos. Verificar RxJS y conservar los tres ejemplos Java previamente
revisados; repetir corpus y escaneos comparables con hashes de fuentes iguales.

## Referencias de lenguaje

- [Java: constructores y acceso](https://docs.oracle.com/javase/specs/jls/se17/html/jls-8.html#jls-8.8): un constructor explícito sin modificador tiene acceso package.
- [C#: constructores](https://learn.microsoft.com/en-gb/dotnet/csharp/programming-guide/classes-and-structs/constructors): distinguir constructores de instancia, estáticos y primarios.
- [TypeScript: clases](https://www.typescriptlang.org/docs/handbook/2/classes.html): private/protected se comprueban estáticamente y no garantizan restricciones runtime.

Se verificaron 5.340 tests, 102 archivos con mypy y el wheel fuera del checkout.
La matriz de 42 fuentes corrige 27 FP; 15 TP se conservan y la operación amplia
retiene sus 42 matches. RxJS pierde sólo el FP canónico; el corpus conserva
73 presencias en 281 ejemplos. El alcance lazy sigue pendiente de otra revisión.

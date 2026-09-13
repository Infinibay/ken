# Ken: diseño del IR y de la búsqueda estructural

**Estado: propuesta de diseño, 12 de septiembre de 2026.**
La implementación disponible y sus límites están descritos en la [guía operativa](../../structural-queries.md). Estos documentos
especifican el producto que queremos construir. No son una lista de capacidades
ya disponibles. El código experimental de `src/ken/structural` es un prototipo:
puede informar el diseño, pero no determina sus contratos.

Actualización de implementación: la [referencia IR](../../structural-ir.md)
incluye tipos parametrizados, operadores, CFG de statements, joins de retornos en
ramas, operaciones públicas de patrones, copias de colecciones, slots heredados,
accesos derivados de parámetros, procedencia de elementos iterados y descarte
de resultados de llamadas, estados de campos del objeto devuelto, bindings por
ocurrencia de argumento, transferencias directas de campos, productos internos de
builders, enlaces nominales de anotaciones genéricas Rust, predicados simples
inventarios de asignaciones por callable con conteos explícitos y raíces de
jerarquías nominales declaradas. C# conserva static/const de sus campos; C++ conecta declaradores con sus slots
y conserva indirecciones y cualificadores. Los [métodos C++](cpp-method-contracts.md)
incluyen prototipos y enlaces de override por firma virtual soportada, con estados
explícitos para firmas que aún no se resuelven. Los [inicializadores de constructor](cpp-constructor-initializers.md)
conservan argumentos y transferencias directas soportadas; Command reutiliza la
operación pública retained_dispatch para reconocer invocación por contrato nominal.
Las [entradas de bindings](strategy-binding-inputs.md) distinguen última escritura
fuente y retención de miembros; Strategy compone supplied_policy con un slot de contrato.
Sus límites y ejemplos ejecutables se
mantienen allí; los capítulos de diseño no sustituyen esa matriz de disponibilidad.

Las incorporaciones posteriores incluyen [valores de clase y factories de subclases](class-expression-factories.md),
[acceso a constructores](restricted-eager-singleton.md), [flujo lazy y nulidad](lazy-null-flow.md)
y [valores iniciales de campos](field-initial-values.md). La última distingue
modo de inicialización, estado del análisis y valor de declaración: no describe
el heap final ni acredita unicidad o seguridad de threads. El catálogo actual
tiene 23 conceptos GoF, 44 variantes ejecutables, 33 variantes de diseño, diez
reglas modernas/web y quince operaciones públicas; la [cobertura](../../gof-coverage.md)
explica qué demuestra cada conteo.

El objetivo es buscar relaciones en código sin ejecutarlo: una consulta puntual,
un patrón de diseño, una práctica del equipo y un posible defecto usan exactamente
el mismo motor. Una regla es una consulta guardada con metadatos opcionales.
`gof`, `correctness`, `architecture` y `concurrency` son colecciones o etiquetas;
no son clases especiales de búsqueda.

## Recorrido de lectura

Empezar por [del algoritmo en palabras al IR](algorithms-to-ir.md): Builder,
Memento, Observer y Cache-Aside derivan el vocabulario necesario del comportamiento.
Continuar con la [revisión de los 23 GoF](gof-algorithm-contracts.md), que aplica
el mismo ejercicio a todos y distingue los contratos que aún faltan en el motor.
El [núcleo de instrucciones](instruction-ir.md) organiza valores, memoria,
regiones y efectos; su exportación inicial es una base de migración, no el reemplazo
completo de los análisis ni del lenguaje de consultas actual.

1. [IR: identidad, operaciones, tipos, flujos y evidencia](ir.md).
2. [KenQL: lenguaje de búsqueda y semántica](query-language.md).
3. [Composición de consultas nombradas](composition.md): roles públicos, dependencias y reutilización.
4. [Catálogo declarativo](catalog-format.md): un TOML por patrón, varias variantes y DB derivada.
5. [Análisis de los 23 patrones GoF](gof.md): roles, consultas, alternativas,
   ambigüedades y matriz de ejemplos en ocho lenguajes.
6. [Casos completos y reglas adicionales](use-cases.md): construcción, generadores,
   bugs, concurrencia, APIs públicas y directorios.
7. [Implementación, rendimiento y plan de validación](validation.md).
8. [Revisión del IR contra errores reales](ir-review-2026-09-13.md): prioridades,
   reproducción de asignaciones sin versión y separación entre gaps del IR y queries.
9. [Operaciones públicas de patrones](pattern-operations.md): iterate_over, map,
   filter y bloques de uso con bindings correlacionados.
10. [Copias de colecciones](collection-snapshots.md): alias restringidos y
    notificación Observer sobre snapshots.
11. [Despacho web](web-dispatch.md): tabla heredada, clave derivada y adaptación
    del handler con evidencia de retorno.
12. [Unit of Work](unit-of-work.md): cambios diferidos por clave y operaciones
    de persistencia correlacionadas, con límites transaccionales explícitos.
13. [Acciones Command](patterns/command.md#discriminación-de-acciones-y-consultas):
    descarte de resultados y objetos retenidos, implementados en IR 1.25.0.
14. [Copia de campos posterior a la construcción](field-copy.md): variante de
    Prototype implementada en IR 1.26.0, con estados correlacionados por rama.
15. [Valores retornados en KenQL](returned-values.md): proyección de orígenes
    precisos a RETURNS_VALUE en IR 1.27.0 y fallback sintáctico explícito.
16. [Memento con getters y contratos](memento-accessors.md): variante implementada
    en cinco lenguajes en IR 1.28.0; Builder conserva una ambigüedad pendiente.
17. [State y transiciones mediante el contexto](state-context-transitions.md):
    variante con bindings de setter, parámetros-propiedad TypeScript y slots nominales.
18. [Bindings de llamadas y transferencias de campos](call-bindings.md): identidades
    por ocurrencia, constructores, defaults, estados y límites de los nuevos hechos.

19. [Command en colas y procesamiento de lotes](queued-command.md): operación pública
    drain, vaciado de colecciones y variante Command con contrato o caller observado.

20. [Builder con producto almacenado](stored-product-builder.md): configuración de
    miembros, inicializadores Rust y uso público de copias derivadas.

21. [Entradas de configuración de Builder](builder-input-writes.md): última
    escritura, campos directos, sentencias Go y declaradores C++.

22. [Read-Through Cache](read-through-cache.md): predicados simples, inventarios
    de escrituras y caminos de hit/retorno y miss/carga/escritura/retorno.

23. [Cache-Aside y orden de escrituras](cache-aside-flow.md): conteos por callable,
    rebindings, caminos de miss y orígenes posibles del retorno.

24. [Bridge refinado](patterns/bridge.md#delegación-en-la-abstracción-refinada-implementada-en-ir-1350):
    campos locales/heredados, raíces nominales y separación de familias.

25. [Declaradores de campos C++](cpp-field-declarators.md): slots, tipos cualificados,
    punteros/referencias, callbacks opacos e inicializadores por declarador.

26. [Métodos C++ y contratos virtuales](cpp-method-contracts.md): prototipos,
    cualificadores, identidad de parámetros y enlaces de override por firma.

27. [Inicializadores de constructor y Command retenido](cpp-constructor-initializers.md):
    argumentos fuente, retención final y operación pública de despacho por contrato.

28. [Entradas de bindings y políticas Strategy](strategy-binding-inputs.md): última
    escritura, descriptores, slots declarados y composición de consultas.

29. [Dependencias funcionales y paréntesis del callee](callable-dependency-injection.md):
    factories, conversores, callbacks y distinción de casts.

30. [Singleton eager](eager-singleton.md): almacenamiento compartido, campos
    privados y llamadas estáticas.

31. [Expresiones de clase y factories de subclases](class-expression-factories.md):
    ámbitos internos, bases léxicas y aserciones TypeScript.

32. [Acceso a construcción y Singleton eager restringido](restricted-eager-singleton.md).

33. [Inicialización lazy y polaridad de nulidad](lazy-null-flow.md).

34. [Valores iniciales y defaults de campos](field-initial-values.md).

35. [Terminación normal de regiones y Retry por fallthrough](normal-completion.md).

Los capítulos de diseño incluyen **sintaxis propuesta** que el parser aún no
acepta. Para consultas ejecutables usar las guías operativas de
[KenQL](../../structural-queries.md) e [IR](../../structural-ir.md); las notas de
implementación indican qué partes del diseño ya están disponibles.
Los ejemplos de lenguajes fuente son propios y se
identifican como completos o como fragmentos. Un fragmento no representa una prueba
compilada ni un resultado confirmado del analizador.

## Decisiones principales

| Decisión | Razón | Consecuencia |
|---|---|---|
| Un grafo de propiedades tipado, con operaciones y regiones de control | Declaraciones solas no explican uso, estado ni orden | Separar síntaxis preservada, resolución y análisis de flujo |
| Identidades por declaración y ámbito | Un nombre igual no demuestra identidad | Importaciones y referencias ambiguas conservan alternativas |
| Tipos, lugares de almacenamiento y valores son entidades distintas | Una variable puede contener valores diferentes a lo largo del programa | Builder inmutable y mutable requieren variantes diferentes |
| Evidencia y alcance de completitud explícitos | La ausencia de una arista puede ser falta de información | Negación y cuentas exactas pueden producir `unknown` |
| Una sola representación de consulta | Evitar capacidades exclusivas del catálogo | Los 23 patrones se expresan con primitivas públicas |
| Preservar diferencias entre lenguajes | Go no necesita una jerarquía de clases; una closure puede ser Strategy | Adaptadores por lenguaje y variantes por mecanismo |
| Resultados explicables | El usuario necesita revisar por qué apareció una coincidencia | Bindings, localizaciones, derivaciones y contraejemplos posibles |
| Caché configurable de 500 MB por defecto | Reusar parseo y análisis sin crecimiento ilimitado | Límite de disco separado de RAM y presupuestos de consulta |
| Backend intercambiable detrás de contratos | Elegir Rust por mediciones, no por suposición | Corpus semántico compartido entre implementaciones |

## Qué significa detectar un patrón

Ken puede establecer que existen hechos compatibles con una estructura y un uso.
No puede observar directamente la intención del autor. State y Strategy pueden
compartir todo el grafo disponible. Eso debe producir dos interpretaciones con
explicaciones, no una decisión arbitraria que excluye una de ellas.

Distinguimos tres afirmaciones:

- **Forma:** hay un objeto con un campo y un método que delega en él.
- **Comportamiento observado estáticamente:** el método delega usando el mismo
  receptor que recibió y almacenó el constructor.
- **Interpretación:** ese objeto podría desempeñar el rol de Strategy, State,
  Adapter, Proxy u otro, según relaciones adicionales e intención.

Cada variante del catálogo declara cuál de esas afirmaciones respalda. La severidad
es metadato editorial; no aumenta la certeza de los hechos.

## Lo que la revisión ya cambia respecto del prototipo

El primer catálogo contiene firmas demasiado débiles para presentarlas como
identificación general de los 23 patrones. Ejemplos concretos:

- Dos setters que devuelven `self` también aparecen en entidades de dominio.
  Builder necesita relación con un producto o una construcción por etapas.
- Observer requiere evidencia de suscripción y difusión del evento, además de un
  bucle con llamadas.
- Command necesita encapsulación e invocación diferida; un delegado sin argumentos
  no basta, y un Command sí puede recibir argumentos.
- Factory Method clásico requiere un punto de extensión en la creación. Una
  función constructora libre merece otra variante/etiqueta, no una equivalencia.
- `SUBTYPE_OF` no debe absorber indiscriminadamente herencia, implementación de un
  trait, compatibilidad estructural y embedding.
- `unknown` del analizador no es el tipo `unknown` de TypeScript.
- `*` en caminos no puede significar silenciosamente «entre 1 y 16 saltos».
- Un conjunto global de capabilities no prueba ausencia en un método concreto.

Estas brechas son motivos para revisar el diseño antes de ampliar el código. Los
tests del prototipo prueban sus firmas actuales; no prueban todas las variantes
idiomáticas ni la precisión del catálogo propuesto.

## Límites deliberados

La primera versión no pretende demostrar seguridad de memoria, ausencia global de
carreras, terminación, equivalencia de programas ni efectos arbitrarios de macros,
metaprogramación o reflexión. Puede encontrar candidatos útiles y señalar qué
información faltaría para decidir. El soporte por lenguaje se publica por capacidad,
no como una casilla genérica de «soportado».

No habrá ejecución de scripts del repositorio para resolver consultas. Los modelos
de APIs son datos declarativos versionados y validados. Repositorios incompletos,
código con errores y dependencias ausentes deben seguir siendo analizables con
cobertura explícita.

## Mantener el diseño y la referencia sincronizados

Al cambiar el motor, actualizar primero el contrato del capítulo correspondiente:
identidad de los nodos, extremos y atributos de cada relación, lenguajes admitidos,
estados de incertidumbre y casos que quedan fuera. Después de implementar y
validar, trasladar el comportamiento disponible a las guías operativas de IR y
KenQL. Una propuesta sólo pasa a disponible con evidencia ejecutable; conservar
las auditorías anteriores como resultados de su versión, sin actualizar sus
conteos retroactivamente.

Los bloques `kenql` de ambas guías se ejecutan desde
`tests/structural/test_documented_ir_queries.py` y
`tests/structural/test_documented_kenql_queries.py`. Este último carga también
la biblioteca TOML publicada en la guía y prueba controles que eliminan la
evidencia necesaria. Al agregar ejemplos, aportar fuentes testigo y controles
apropiados; parsear una query por sí solo no prueba que encuentre lo descrito.
Los ejemplos aún propuestos deben permanecer identificados en los capítulos de
diseño, fuera de los bloques ejecutables de las guías operativas.

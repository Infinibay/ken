# Bridge refinado y raíces nominales — IR 1.35.0

## Resultado

Se incorpora `bridge#refined-composition` al TOML existente. La consulta canónica
une esa variante con runtime-composition y conserva su rol unit. El catálogo tiene
**23 conceptos GoF, 42 variantes ejecutables, 33 variantes de diseño y nueve reglas
modernas/web**. No equivale a cobertura completa de cada concepto o lenguaje.

La variante conecta una abstracción derivada, otra clase de la misma familia, un
método que reemplaza un slot de la base, un campo de instancia usado como receptor,
su contrato y dos implementaciones nominales. El campo puede estar en la derivada
o ser un slot heredado resuelto. Las raíces explícitas de ambos contratos deben
ser distintas. Ver [diseño y límites](../../design/structural/patterns/bridge.md).

El IR agrega NOMINAL_ROOT/NOMINAL_ROOT_STATUS sobre bases explícitas resueltas,
con raíz única y hasta 32 tipos por camino. Diamantes con raíz compartida se
resuelven con memoización; bases desconocidas, ciclos y raíces múltiples conservan
unsupported. No se inventan bases Object/object implícitas ni compatibilidad
estructural. Los campos C# leen static/const desde field_declaration; readonly,
comentarios, atributos e inicializadores no se confunden con esos modificadores.
La versión 1.35 invalida grafos anteriores en caché.

## Comparación controlada

Las mismas 66 fuentes —once casos, campos locales en Python/TypeScript/Java/C#
y heredados en Python/TypeScript— se analizaron con el wheel 1.34 y el motor 1.35.
Cada par conserva hash, etiqueta y completitud.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.34.0 | 0 | 42 | 0 | 24 |
| IR 1.35.0 | 24 | 42 | 0 | 0 |

[Datos anteriores](refined-bridge-before.json), [datos actuales](refined-bridge-after.json).
Los positivos cubren forma básica, renombrado, forma de declaración de campo y
tercera implementación. Los negativos cubren ausencia de override o base, una
sola implementación, contrato ajeno, campo sin uso, receptor ajeno y una sola familia.
Son fixtures de análisis estático; no se ejecutan ni se compilan los programas.
Esta matriz no estima precisión o recall global.

Se agregan **139 tests**: 84 de Bridge, 24 de modificadores C#, 30 de raíces nominales
y un ejemplo ejecutable de la guía. Además de la matriz, Bridge comprueba campos
estáticos, herencia desconocida, correspondencia de la consulta canónica con la
variante, ausencia de un segundo subtipo de abstracción y topología de decorador.
Los tests del IR comprueban declaraciones múltiples, locales de métodos estáticos,
serialización, cadenas, ciclos, diamantes, profundidad y errores de parsing.

## Revisión externa de los nueve matches nuevos

La [comparación completa del corpus](ir135-corpus-regression.json) conserva commits,
fuentes y consultas. Pasa de **59 a 61 ejemplos con presencia esperada, entre 281**.
Son 736 archivos únicos, 745 apariciones por caso y 6.463 consultas completas.
Sólo cambia Bridge: nueve clases añadidas, ninguna eliminada. Los otros detectores
conservan todos sus matches.

| Caso | Clases nuevas | Evaluación de intención |
|---|---|---|
| iluwatar, bridge | Hammer, Sword | **2 TP revisados.** Ambas implementan Weapon y delegan wield/swing/unwield en el campo Enchantment. FlyingEnchantment y SoulEatingEnchantment aportan la segunda familia. |
| across-languages, notification_system TypeScript | InfoNotification, WarningNotification, UrgentNotification | **3 TP revisados.** Reemplazan Notification.send y delegan en el campo sender heredado; MessageSender tiene Email/Sms/Push como implementaciones. |
| across-languages, llm_providers TypeScript | OpenAIClient, AnthropicClient, GeminiClient, OllamaClient | **4 FP de intención en esta revisión.** generate consulta getBaseURL/getModel para logging y construye una respuesta simulada. Dos familias nominales y una consulta al campo de configuración no demuestran delegación de un algoritmo de implementación. |

No se cuentan los cuatro clientes como cobertura Bridge recuperada ni como TP.
La firma describe correctamente ciertas relaciones, pero sigue siendo demasiado
amplia para decidir esa intención. No se agregaron filtros por nombres de APIs,
clases o directorios para ocultar esos candidatos. **5 TP y 4 FP** describen sólo
los nueve resultados nuevos revisados; no la precisión total del catálogo.

Los [testigos con roles y líneas](refined-bridge-witnesses.json) conservan los tres
scopes, commits y hashes. Se muestra un testigo por clase/operación/campo, separando
las permutaciones de peer/first/second: 144 bindings de clientes se reducen a cuatro
operaciones para revisión, 36 de notificaciones a tres y 12 de armas a seis.
La extracción detallada usa max_matches=1000; las búsquedas canónicas del corpus
mantienen sus presupuestos anteriores y completan. Esa expansión de testigos no
se interpreta como más clases ni como evidencia independiente adicional.

Lombok no se ejecuta ni expande. Los campos final de Sword/Hammer aportan tipo y
uso en código fuente; la consulta no afirma observar el constructor generado.

## Controles externos descartados y casos pendientes

La primera variante experimental también señalaba HeroFactoryImpl en el ejemplo
Prototype y tres Middleware en el ejemplo Decorator. HeroFactoryImpl tiene un solo
subtipo de HeroFactory observado; no cumple la firma final de dos variantes de
abstracción. Middleware hereda RequestHandler, que es también el contrato del campo
handler: las raíces comunes impiden presentarlo como dos familias independientes.
Estas exclusiones se probaron también con fuentes propias en cuatro lenguajes.

Siguen abiertos:

- Los cuatro clientes/configuración anteriores. Falta distinguir consulta de datos
  de delegación de comportamiento sin depender de nombres ni excluir retornos útiles.
- Bridge Python de notification_system: abc.ABC queda sin resolver en el corpus,
  por lo que no se presume una raíz exacta ni un slot heredado a través de ese límite.
- Bridge C++: el tipo del declarador puntero implementor no llega al slot usado
  como receptor. La corrección de static C# no resuelve esa separación de identidades.
- Bridge Go con embedding y contratos estructurales, y Rust genérico: requieren
  variantes propias; no se fuerza su representación como herencia nominal.
- Una sola abstracción refinada, raíces de marcador comunes o bases externas pueden
  ser Bridge válido y quedar fuera de esta firma conservadora. La variante
  runtime-composition anterior sigue disponible con sus límites anteriores.

## Regresión de proyectos reales

[Requests](ir135-requests.json), 19 archivos; [Flask](ir135-flask.json), 24;
[RxJS](ir135-rxjs.json), 123; [Commons IO](ir135-commons-io.json), 277;
[log](ir135-rust-log.json), nueve; e [iluwatar caching](ir135-iluwatar-caching.json),
14, conservan sus matches y roles y completan sus búsquedas. Se contrastaron las
mismas fuentes y commits contra IR 1.34. Los alcances y colecciones son los que
figuran en cada reporte: no se afirma escanear todo cada repositorio.

Commons IO conserva sus tres Bridge previos. La consulta nueva inicialmente agotaba
max_states al combinar peer antes de filtrar la delegación y las raíces. Colocar
ese join al final evita esa multiplicación. La versión final completa la consulta
canónica con unas 4.200 expansiones de estado, sin ampliar el presupuesto.

## Comprobaciones finales y rendimiento

La suite final pasa **3.973 tests en 160,07 s**; mypy pasa en **99 archivos**.
El wheel offline contiene los módulos y TOML verificados byte por byte contra
el manifiesto. Fuera del checkout se comprobaron IR 1.35, las nueve reglas modernas
y ocho positivos/negativos Bridge en cuatro lenguajes. La guía operativa tiene
20 tests y la consulta nueva forma parte de esa suite.

Sobre los mismos archivos externos, con una consulta de warmup y 30 muestras sobre
índice/registro precalculados:

| Consulta Bridge | Mediana IR 1.34 | Mediana IR 1.35 | p95 IR 1.35 | Matches 1.35 |
|---|---:|---:|---:|---:|
| iluwatar bridge, Java | 0,041 ms | 0,359 ms | 0,429 ms | 2 |
| notification_system, TypeScript | 0,053 ms | 0,493 ms | 0,565 ms | 3 |

La versión anterior no encontraba ninguno de esos Bridge; no se presenta la
mayor comprobación como una mejora de velocidad. Se midió la construcción de la
vista aparte, con diez muestras. No se incluyen CLI, parseo/enlace ni caché
persistente. Son observaciones de estos ejemplos en el host, no una proyección
de rendimiento a repositorios grandes. [Datos de rendimiento](refined-bridge-performance.json)
y [registro de comprobaciones](ir135-checks.json).

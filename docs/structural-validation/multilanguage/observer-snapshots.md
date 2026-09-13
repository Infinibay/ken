# Observer sobre copias de colecciones — IR 1.22.0

Se corrigió TS-01: la nueva variante declarativa `observer#snapshot-registry`
relaciona alta de listeners, copia del registro y llamadas sobre sus elementos.
También admite alta desde un callback que un método pasa explícitamente a una
llamada. El cambio está en el TOML de Observer; no hay un detector Python especial
para RxJS. El IR aporta modelos de copia y procedencia reutilizables en consultas.

## Evidencia externa revisada

Se escanearon 123 archivos TypeScript de RxJS en el commit
`54796b38a57e6309f9861e174737479bb3f63f61`, excluyendo specs y testing, sin
ejecutar ni importar el proyecto. El [reporte completo](observer-snapshots-rxjs.json)
incluye hashes de fuente y motor, alcance, presupuestos y resultados. Observer
pasa de cero a tres clases. Se revisaron los nueve testigos de una consulta con
roles ampliados, conservados en [este reporte](observer-snapshot-witnesses.json).

| Clase | Alta | Copia → llamada de notificación | Evaluación |
|---|---|---|---|
| Subject | `subject.ts:33`, callback pasado a super | 42→43, 52→55, 63→66 | TP revisado |
| AsyncSubject | `async-subject.ts:42`, método privado | 60→63, 75→79 y 81 | TP revisado |
| PerSubscriptionSubjectBase | `per-subscription-subject-base.ts:105`, método protegido | 120→122, 138→141, 156→159 | TP revisado |

En cada caso el mismo campo recibe al suscriptor y suministra la copia consumida.
Vaciar el registro después de copiarlo no elimina los elementos de la copia.
Los tres matches corresponden a implementaciones de Observer en estas fuentes;
las nueve llamadas son evidencia de esos tres matches, no nueve patrones.
No se infiere precisión global a partir de esta muestra ni se da por probado
el comportamiento completo de las APIs Observable, cancelación o reentrancia.

## Regresiones y rendimiento

95 tests nuevos de código fuente en Python, JavaScript y TypeScript cubren copias
directas, aliases, aliases encadenados, limpieza del origen, callbacks de alta y
elementos invocables. Los negativos incluyen otra colección, mapper de Array.from,
builtins reemplazados, alias posterior/condicional/sobrescrito, escape a una llamada,
mutación directa o por otro alias, escritura indexada, exec/eval, shadowing del
elemento, reutilización de un alias como binding de otro bucle y callbacks sin uso.
Son pruebas de parsing/IR/query; no ejecutan ni compilan las fuentes de fixtures.

La suite completa pasa 2.082 tests. La [regresión del corpus GoF](ir122-corpus-regression.json)
mantiene las mismas 53 presencias esperadas en 281 ejemplos, los mismos matches y
ninguna consulta incompleta. Los tres TP de RxJS pertenecen a una evaluación
separada; no se suman al numerador 53 del corpus didáctico.

En una ejecución del alcance completo de RxJS, construir el grafo tomó 1.248,34 ms.
La consulta Observer tomó 0,784 ms, 434 estados y 203 filas examinadas, completa.
Son mediciones individuales: construcción y búsqueda se informan por separado;
no son percentiles ni una medición de RSS o caché. La suite completa tomó 44,07 s.

## Límites restantes

Los modelos suponen builtins estándar. Se rechaza shadowing detectado en el archivo,
pero monkey-patching externo no está resuelto. Solo se siguen escrituras locales
simples con orden léxico suficiente; las exclusiones de escape/mutación son
conservadoras y pueden omitir usos válidos. La resolución general de bloques,
el heap, reemplazos temporales del registro, reasignación del parámetro de alta y
la ejecución del callback requieren análisis adicional. La presencia de un call
en un bucle no certifica alcanzabilidad. Las otras variantes de Observer conservan
sus propias limitaciones; este cambio no valida automáticamente sus resultados.

Contrato y ejemplos: [copias de colecciones](../../design/structural/collection-snapshots.md)
y [guía IR](../../structural-ir.md).

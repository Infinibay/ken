# Disponibilidad contextual y recomendaciones

Propuesta de disponibilidad general, todavía no un builtin completo de KQL.
La integración de Ken ofrece ahora `ken_related(..., relation="available",
from_path=...)`: expresiones de acceso explícitas para callables Python y sus
obligaciones pendientes. No implementa todavía la relación general de tipos,
fases e inicialización descrita aquí. Ver [inspección](../code-inspection.md).

## Caso de uso

Capturar una clase, módulo, función u objeto que satisface un patrón Factory;
comprobar que produce un tipo compatible; comprobar que se puede usar desde el
ámbito/punto donde aparece una construcción manual o un Builder; emitir una
recomendación con ambas ubicaciones y su evidencia.

No basta buscar la palabra Factory, ni saber que existe una clase en algún archivo.
La existencia es una consulta sobre patrones; la disponibilidad es una relación
del modelo del programa; recomendar un reemplazo añade obligaciones de equivalencia.

## Relaciones necesarias

| Concepto | Entradas/salidas conceptuales |
|---|---|
| Coincidencia de patrón | Patrón/modelo y roles; produce entidad, producto y evidencia correlacionados |
| Compatibilidad | Tipo requerido, tipo producido, conversión permitida y contexto |
| Visibilidad | Declaración, scope de uso, imports/exports, access control |
| Resolución | Nombre/expresión en el punto de uso y posibles destinos |
| Disponibilidad por fase | Entidad, punto, configuración de build/runtime, fase y modalidad |
| Recomendación | Código actual, alternativa concreta, obligaciones acreditadas y pendientes |

La API de composición debe reutilizar `matches`/predicados nombrados y exports de
roles. Evitar convertir `Class.of(pattern.ofType(...))` en un nombre de tipo mágico:
primero capturar las entidades que cumplen el patrón y luego relacionarlas por
identidad/tipos. Sirve igual para módulos, funciones y objetos.

## Fases y conocimiento

La fase depende del constructo y configuración, no sólo del lenguaje. C puede
necesitar preprocesado/enlace; Java tiene carga e inicialización; Python/JavaScript
pueden importar o definir dentro de una rama. Estar declarado o ser lexicalmente
visible no prueba que la inicialización haya sucedido ni que una llamada tenga éxito.

Separar must/may y conocimiento desconocido. Ausencia acreditada sólo dentro de
un universo cerrado. Un import condicional no hace disponible la fábrica en todas
las rutas; un modelo sin información de carga no prueba su ausencia.

Una condición de query sobre disponibilidad debe preservar unknown: el else no
se activa porque el análisis no pudo probar la rama positiva. Esta regla coincide
con `when` del lenguaje. El motor podrá resolver anticipadamente condiciones por
lenguaje/path, pero las de disponibilidad pueden requerir CFG, orden de eventos,
aliases, configuración y contexto interprocedural.

## Dependencias, optimización y pruebas futuras

* Predicados positivos pueden compartir resultados; ciclos con negación requieren
  estratificación. Una regla de recomendación no puede justificarse circularmente
  por su propia recomendación.
* La caché incluye patrón/modelo transitivo, punto/scope, configuración y universo
  de resolución. Agregar un import, símbolo o archivo puede cambiar el resultado.
* Prefiltrar por producto/familia/scope antes de evaluar cada Factory/Builder del
  repositorio. Reutilizar coincidencias y evidencia del mismo snapshot.
* Pruebas: módulos exportados/no exportados, shadowing, símbolos privados,
  imports condicionales, definición posterior al uso, cargas desconocidas,
  build flags, productos incompatibles y disponibilidad sólo en una rama.
* Una recomendación informativa puede reportar evidencia parcial. Un autofix
  necesita además preservar efectos, identidad, errores y orden relevante.

Incorporar después de P11/E11/E12/S13. Sigue pendiente decidir firmas concretas,
perfiles por frontend y sintaxis final; estos nombres conceptuales no son APIs.

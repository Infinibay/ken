# Los 23 patrones GoF: representación y portabilidad

Estado: análisis de diseño. Volver al [índice](README.md).

La [revisión algorítmica de los 23](gof-algorithm-contracts.md) añade el ejercicio
«palabras → identidades/invariantes → instrucciones», con variantes, ruido permitido,
contraejemplos y gaps. Es una especificación de contratos; no convierte automáticamente
las firmas actuales en pruebas del comportamiento completo.

El catálogo original reúne 23 patrones; aquí se propone su representación estática,
con ejemplos propios y sin reproducir el texto del libro. [Página del editor](https://www.informit.com/store/design-patterns-elements-of-reusable-object-oriented-software-9780201633610).

## Cómo leer este catálogo

Cada sección contiene roles, restricciones del grafo, variantes y contraejemplos.
Las expresiones de «grafo» son **planes relacionales**, no consultas ejecutables.
Sus verbos descriptivos se deben expandir a operaciones, tipos, accesos, llamadas y
flujos del [IR](ir.md); no son predicados secretos de detección.

Las ocho filas de cada tabla son **fragmentos de diseño**, con tipos, constructores,
campos y contexto omitidos. Ilustran el mecanismo relevante, no programas autónomos
ni fixtures ya compiladas. Las filas funcionales o basadas en composición se marcan
como variantes cuando no cumplen la definición clásica basada en herencia. La
siguiente fase debe convertir cada fila en un fixture completo con positivos,
negativos y hechos esperados; todavía no se ha demostrado que Ken las reconozca.

P = Python; JS = JavaScript; TS = TypeScript; J = Java; CS = C#; CPP = C++; G = Go;
R = Rust. Nombres como `build` o `visit` ayudan a leer, pero no deben decidir una
coincidencia salvo que formen parte de un protocolo de lenguaje resuelto.


## Archivos por patrón

1. [Abstract Factory](patterns/abstract-factory.md) — [variantes declarativas](catalog/abstract-factory.toml).
2. [Builder](patterns/builder.md) — [variantes declarativas](catalog/builder.toml).
3. [Factory Method](patterns/factory-method.md) — [variantes declarativas](catalog/factory-method.toml).
4. [Prototype](patterns/prototype.md) — [variantes declarativas](catalog/prototype.toml).
5. [Singleton](patterns/singleton.md) — [variantes declarativas](catalog/singleton.toml).
6. [Adapter](patterns/adapter.md) — [variantes declarativas](catalog/adapter.toml).
7. [Bridge](patterns/bridge.md) — [variantes declarativas](catalog/bridge.toml).
8. [Composite](patterns/composite.md) — [variantes declarativas](catalog/composite.toml).
9. [Decorator](patterns/decorator.md) — [variantes declarativas](catalog/decorator.toml).
10. [Facade](patterns/facade.md) — [variantes declarativas](catalog/facade.toml).
11. [Flyweight](patterns/flyweight.md) — [variantes declarativas](catalog/flyweight.toml).
12. [Proxy](patterns/proxy.md) — [variantes declarativas](catalog/proxy.toml).
13. [Chain of Responsibility](patterns/chain-of-responsibility.md) — [variantes declarativas](catalog/chain-of-responsibility.toml).
14. [Command](patterns/command.md) — [variantes declarativas](catalog/command.toml).
15. [Interpreter](patterns/interpreter.md) — [variantes declarativas](catalog/interpreter.toml).
16. [Iterator](patterns/iterator.md) — [variantes declarativas](catalog/iterator.toml).
17. [Mediator](patterns/mediator.md) — [variantes declarativas](catalog/mediator.toml).
18. [Memento](patterns/memento.md) — [variantes declarativas](catalog/memento.toml).
19. [Observer](patterns/observer.md) — [variantes declarativas](catalog/observer.toml).
20. [State](patterns/state.md) — [variantes declarativas](catalog/state.toml).
21. [Strategy](patterns/strategy.md) — [variantes declarativas](catalog/strategy.toml).
22. [Template Method](patterns/template-method.md) — [variantes declarativas](catalog/template-method.toml).
23. [Visitor](patterns/visitor.md) — [variantes declarativas](catalog/visitor.toml).

## Matriz de capacidades que decide si funcionaría

| Familia de variantes | Capacidades necesarias | Sin ellas |
|---|---|---|
| Abstract Factory / Factory Method nominales | Resolución de contratos, override y tipos de retorno | Candidato de construcción, sin familia probada |
| Builder mutable | Identidad de receptor, escrituras y flujo al producto | Fluent API, sin construcción probada |
| Builder inmutable / typestate | Flujo entre versiones, generics y sustitución | No afirmar ausencia de Builder |
| Prototype / Memento | Copia, lectura/escritura y flujo por campos | Snapshot/copy-like parcial |
| Singleton / Flyweight | Storage compartido, guards, claves y modelos de API | Cache-like, sin unicidad ni sharing probado |
| Adapter / Bridge / Decorator / Proxy | Contratos y delegación correlacionada | Wrapper candidato con roles ambiguos |
| Composite / Interpreter | Recursión, colecciones o sum types, uso de resultados | Recorrido recursivo sin interpretación de intención |
| Command / Strategy / Observer | Valores callable, capturas, almacenamiento e invocación | No depender solo de clases |
| State | Def-use del slot que gobierna dispatch y transiciones | Intercambiabilidad sin State confirmado |
| Iterator | Protocolos por lenguaje, yield/resume/fin | Sintaxis de generación sin corrección de recorrido |
| Mediator / Facade | Call graph entre participantes, imports/exports y frontera | Coordinación candidata |
| Template Method | Slots reemplazables y orden del algoritmo | Delegación sin esqueleto extensible |
| Visitor | Self-flow, tipos de elementos y despacho de operaciones | Callback que recibe self |

**Conclusión de diseño:** el IR de declaraciones y triples del prototipo no basta
para estas variantes. Hace falta modelar closures, contratos estructurales,
operaciones por sitio, flujos correlacionados y cobertura local. Es viable formular
las firmas sobre ese IR ampliado; la viabilidad de reconocerlas con precisión y
costo útil aún requiere el corpus y las mediciones de [validación](validation.md).

## Discriminación: qué no debería hacer el catálogo

No elegir una sola etiqueta porque fue la primera regla en hacer match. No exigir
que todos los lenguajes copien ejemplos Java. No interpretar que `Clone` garantiza
copia profunda o `Singleton` sincronización. No confundir presencia de un patrón con
calidad del diseño. No subir un score por nombres como Factory salvo que el usuario
pida expresamente una búsqueda textual/heurística y el resultado lo declare.

Cada variante debe contener: roles emitidos, hechos obligatorios, evidencia opcional,
capabilities, afirmación exacta, falsos positivos conocidos, fixtures positivas,
negativas y de análisis incompleto. Las firmas más débiles pueden conservarse para
exploración bajo una etiqueta `shape`, con explicación visible.

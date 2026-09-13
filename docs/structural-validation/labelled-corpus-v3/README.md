# Reescaneo del corpus con IR 1.8.0

Fecha: 2026-09-12. Mismos 281 ejemplos y mismos hashes de las 736 fuentes seleccionadas que en v2. Los matches del patrón etiquetado pasan de **38 a 44**, sin pérdida de ninguno de los 38 anteriores. Todas las consultas completaron su enumeración dentro del presupuesto; no hubo excepciones. Persisten cinco ejemplos con diagnósticos de parsing.

Los 237 ejemplos sin match esperado no constituyen por sí solos falsos negativos confirmados. Tampoco 44/281 es precisión: es presencia de la etiqueta esperada en una muestra seleccionada. PHP y Swift permanecen inventariados, sin frontend estructural.

| Corpus | Casos | Antes | Ahora |
|---|---:|---:|---:|
| across-languages | 69 | 17 | 19 |
| cpp-patterns | 24 | 0 | 1 |
| go-patterns | 2 | 0 | 1 |
| guru-rust | 31 | 1 | 1 |
| java-patterns | 23 | 1 | 1 |
| pandovski | 110 | 14 | 15 |
| php-patterns | 0 | 0 | 0 |
| python-patterns | 22 | 5 | 6 |
| swift-patterns | 0 | 0 | 0 |

## Ganancias revisadas

| Corpus | Ejemplo | Cambio relevante |
|---|---|---|
| across-languages | [behavioral/iterator/data_stream_processor/typescript/](https://github.com/Eng-Elias/design-patterns-across-languages/tree/efd075de92e42099e8ae24fc274dc0e7b86ba2f9/behavioral/iterator/data_stream_processor/typescript/) | Avance position++ (Iterator TypeScript) o registro de claves e invocación en goroutine (Observer Go). |
| across-languages | [behavioral/observer/event_monitoring/go/](https://github.com/Eng-Elias/design-patterns-across-languages/tree/efd075de92e42099e8ae24fc274dc0e7b86ba2f9/behavioral/observer/event_monitoring/go/) | Avance position++ (Iterator TypeScript) o registro de claves e invocación en goroutine (Observer Go). |
| cpp-patterns | [iterator/Iterator.cpp](https://github.com/JakubVojvoda/design-patterns-cpp/tree/4fae40666a970dc4c7901df54964d6ebcd80ba5c/iterator/Iterator.cpp) | ConcreteIterator usa next/isDone/currentItem y campos declarados después de los métodos. |
| go-patterns | [behavioral/observer/main.go](https://github.com/tmrts/go-patterns/tree/f978e420361704bd7531e2b57905a308a3a012c8/behavioral/observer/main.go) | eventNotifier registra observadores como claves de un mapa. |
| pandovski | [Behavioral/Iterator/java/](https://github.com/ZoranPandovski/design-patterns/tree/db0dcf0ceade1a84fc5466fc625a50cc1dd066fe/Behavioral/Iterator/java/) | ListOfDoubleIterator avanza index++ dentro del argumento a getElement. |
| python-patterns | [patterns/behavioral/strategy.py](https://github.com/faif/python-patterns/tree/47f7390d01f5d69a15fba915fb50e257b13d7864/patterns/behavioral/strategy.py) | Order almacena e invoca la función de descuentos; descriptor runtime todavía no resuelto. |

La revisión de Observer Go confirma el patrón; no demuestra seguridad de concurrencia: su Notify lanza goroutines y eso requiere análisis separado. El Iterator TypeScript satisface la variante pareada aunque su metadata anterior sólo mencionaba Java. El matcher no restringe automáticamente idiomas por esa metadata.

## Candidatos adicionales y problemas

| ID | Caso | Revisión | Próxima acción |
|---|---|---|---|
| V3-01 | C++ Memento: Originator aparece como Builder | Falso positivo de intención revisado: setState modifica estado y createMemento toma un snapshot; no hay protocolo de construcción de un producto. Se parece al problema JAVA-01 del lector de bloques. | Reducir ambos casos y revisar el contrato de Builder, sin filtros por nombres. |
| V3-02 | C++ Builder: Director aparece como Strategy | Composición polimórfica compatible con la firma de Strategy, pero su papel principal es coordinar pasos del builder. No se declara falso positivo definitivo por coexistencia posible. | Conservar roles ampliados y separar firma de delegación de interpretación de algoritmo. |
| V3-03 | C++ Chain of Responsibility: Handler aparece como Strategy | El campo successor es una cadena, no una selección independiente de algoritmo. La firma nominal acepta inyección y dos subtipos. Probable sobreclasificación. | Comparar reenvío condicionado al mismo contrato con inyección de estrategia externa; documentar casos ambiguos. |
| V3-04 | Python Abstract Factory: PetShop aparece como Strategy | El callable inyectado es una clase constructora de animales. Es una política de creación; la intención Strategy es ambigua y Abstract Factory sigue sin detectarse. | Resolver valores callable que son tipos y distinguir familias de productos, sin descartar automáticamente patrones coexistentes. |

Estos cuatro matches nuevos están registrados con sus roles en [comparison.json](comparison.json). Los reportes por repositorio y [manifest.json](manifest.json) fijan motor, fuentes, presupuestos y commits. El reescaneo sólo ejecutó el analizador, no los programas descargados.

## Prioridades derivadas

1. Endurecer la interpretación de Builder frente a snapshots y sucesores: más matches no deben presentarse como mejora automática.
2. Resolver colaboraciones Java entre archivos y completar Builder de producto almacenado en Rust/C++; siguen dominando las omisiones.
3. Ampliar modelos de middleware HTTP con identidad de import y registro, además del wrapper funcional ya implementado.
4. Mantener diferencias entre candidato estructural, intención revisada y ausencia por capacidad faltante en resultados y documentación.

Reproducción: `.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/ken-corpus-replay`. La comparación verificó igualdad de cada ruta y SHA-256 entre v2 y v3 antes de contar ganancias o pérdidas.

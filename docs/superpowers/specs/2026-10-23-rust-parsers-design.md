# M3b: gramáticas y parsers nativos

Se continúa la migración aprobada, en ejecución nativa y sin pausas de aprobación.
M3a quedó aceptado en2e52412e. Este bloque migra los19frontends de
`src/ken/parsers`, sus44extensiones y las20gramáticas necesarias (TS/TSX
son gramáticas distintas). El modelo común y las escrituras incrementales
siguen siendo los siguientes bloques de M3; no se atribuyen a estos extractores.

## Conceptos y uso

`GrammarCatalog` selecciona y conserva una gramática nativa verificada.
`SyntaxTree` posee el árbol y el préstamo de su biblioteca; ningún nodo puede
sobrevivir a esa propiedad. `ParserRegistry` selecciona un frontend por lenguaje
/extensión. Cada frontend transforma sintaxis en `ParsedFile`, con símbolos,
imports, docstring y scopes. Helpers de comentarios/firmas son reglas comunes;
las decisiones específicas siguen en su lenguaje.

```rust
let parsers = ParserRegistry::new(GrammarCatalog::prepared(grammar_manifest)?);
let language = parsers.detect(Path::new("api.h"), Some(source))?;
let parsed = parsers.parse(language, source, "api.h")?;
```

No se invoca Python, Git, un compilador ni un descargador desde estas operaciones.
Preparar recursos de prueba/paquete es una operación distinta, anterior al consumo.
No se instala ni reemplaza todavía el comando `ken`.

## Gramáticas y recursos

El binding Python0.25.2 incluye el motor C0.25.10, revisión
`da6fe9beb4f7f67beb75914ca8e0d48ae48d6406`. Rust usa tree-sitter0.25.10:
los42fuentes C/headers del motor original coinciden byte por byte con ese crate.
El número0.25.2 del binding no identifica la versión del motor C. Los seis paquetes
con gramáticas directas conservan versiones: Python0.25.0, Rust0.24.2,
JavaScript0.25.0, TypeScript/TSX0.23.2, Go0.25.0, Java0.23.5. Se usan sus crates
oficiales nativos, comprobando sus `parser.c` contra los sdists autenticados por
`uv.lock`. Los sdists Python/Java/Rust/TS no son por sí solos una fuente compilable
completa: faltan scanner o headers en algunos. No se cargan los `.abi3.so`, cuyos
símbolos públicos son bindings Python.

Bash,C,C++,C#,CSS,Dart,GraphQL,HTML,Kotlin,PHP,PowerShell,Ruby y SQL usan las
bibliotecas C independientes de language-pack1.8.1, iguales a las originales.
El catálogo upstream fijado es33602ce7d17edd24cc00a1a9fe7129a61138f8ef.
Se autentica el bundle completo antes de extraer sólo esos13recursos y licencias:
macOSarm64 SHA9337a5141d800a08ec2995a5a6f87bacd623517fe6d2f192b85a69c41faf25d7;
Linuxaarch64 SHA1b5d762750597fe9d5587a5c225f5a85feef9e839842816d25d085dc2662f0c1.
El manifest preparado identifica formato, plataforma, revisión y SHA/size de cada
biblioteca. Las revisiones y licencias de las13gramáticas viajan con el paquete.
No se cambia ni borra la caché global existente.

Carga diferida por lenguaje: un recurso opcional ausente/corrupto falla al usar
ese lenguaje e identifica cuál; no inutiliza los otros18. El manifest no admite
rutas absolutas, escapes `..`, identidades duplicadas ni plataformas incorrectas.
Un recurso distinto nunca se interpreta como la gramática solicitada. Los módulos
permanecen vivos mientras existan árboles/nodos; el API público no entrega un
`tree_sitter::Tree/Language` que permita escapar a esa vida útil. Instanciar un
parser independiente por operación evita estado mutable compartido entre clientes.
M8 integrará la ubicación instalada de los recursos; ahora el catálogo recibe
explícitamente su manifest preparado y permite usar las gramáticas estáticas sin
los recursos opcionales disponibles.

## Compatibilidad de extracción

Se conserva todo `ParsedFile` de los originales: orden/multiplicidad, kinds,
nombres/qualnames, rangos1-based inclusivos, imports con línea, docstring,
scopes con símbolo, firma, documentación, owner, statements, inicio de
implementación y annotations. No se corrigen peculiaridades históricas para
hacer más elegante el port. Los símbolos compartidos que el enriquecimiento
modifica deben dar el mismo valor final en la lista y el scope correspondiente.

Python conserva los dos recorridos (outline y scopes lexicales), interpretación
de literales/docstrings, decoradores, clases anidadas y sus imports. JS/TS conserva
funciones, métodos, arrows, asignaciones y scopes adicionales del enriquecimiento.
Los demás frontends conservan sus elecciones concretas de nodos y comentarios.
El enriquecimiento común mantiene prioridades por span, atributos Rust intercalados,
inner docs y comentarios trailing. Textos se decodifican UTF-8 con sustitución como
el original; byte offsets y líneas provienen de tree-sitter, no de índices Unicode.

Detección:44extensiones, suffix lowercase; `.h` usa evidencia estructural C++
cuando hay bytes y conserva C sin ellos; palabras C++ en comentarios/literales no
cambian el lenguaje. Sólo el hint literal terminado en `.tsx` selecciona TSX,
como el original. Extensiones desconocidas devuelven ausencia, no un parser por
defecto. Errores sintácticos se analizan con recuperación original; no se convierten
en excepción simplemente por `has_error`.

## Prueba y aceptación

El oráculo se importa únicamente de la copia congelada, verificando todos los
owners `src/ken/parsers/*.py` contra M0 y versiones de paquetes. Se captura el
resultado dataclass completo de llamadas reales de la suite original de parsers,
sin modificar las entradas ni usar resultados Rust. Se deduplican entradas exactas
conservando inventario/cantidad de llamadas, tests descubiertos y XML original.
Un corpus complementario declarado cubre19lenguajes/20gramáticas, fuentes vacías,
Unicode/bytes inválidos, sintaxis rota, decoradores, scopes y ambigüedad.h.
Se capturan también formas sintácticas para comprobar gramáticas, no sólo símbolos.

Cada frontend tiene su ciclo RED→GREEN con esos resultados independientes.
Se comparan todos los campos y el orden: nada de ordenar o quitar documentación
para ocultar diferencias. Las pruebas de corrupción/pérdida, lifetime, aislamiento
por lenguaje y llamadas concurrentes ejercitan los consumidores reales.

MacOSarm64/Linuxaarch64 ejecutan la matriz completa de este bloque y el probe
nativo fuera del checkout, con PATH sin Python y auditoría de linkage/exec/conexión.
Los recursos se preparan una vez por identidad y se reutilizan. Se conservan
fuentes/binarios/recursos/entradas/salidas/hashes y la procedencia de dependencias.
Se reutilizan las matrices M0–M2 y M3a contra sus snapshots; no se repiten modelos
ni toda la suite Python para un cambio de parser. Los originales1066siguen intactos.
Un único review final revisa el plan entero; sus Important/Critical se reparan en
un pase con pruebas. Los temporales propios se limpian tras archivar el ledger.

Referencias primarias: [tree-sitter0.25.10](https://docs.rs/tree-sitter/0.25.10/tree_sitter/),
[coordenadas y nodos](https://tree-sitter.github.io/tree-sitter/using-parsers/2-basic-parsing.html),
[catálogo1.8.1 fijado](https://github.com/xberg-io/tree-sitter-language-pack/blob/33602ce7d17edd24cc00a1a9fe7129a61138f8ef/sources/language_definitions.json).

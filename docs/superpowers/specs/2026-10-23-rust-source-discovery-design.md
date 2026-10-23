# M3a: descubrimiento de fuentes en Rust

La migración continúa con la autorización vigente: ejecución nativa, originales
conservados, sin confirmaciones entre etapas y sin repetir evidencia sin cambios.
Esta especificación desarrolla la parte de exclusiones y recorrido de M3 de
[la especificación general](2026-10-18-rust-migration-design.md). M3 seguirá abierto
hasta completar parsers, modelo común, resolución e indexación incremental.

## Problema y conceptos

Un indexador necesita las mismas identidades relativas y las mismas exclusiones
que el original, sin recorrer cachés enormes ni salir del proyecto. El propietario
original es `src/ken/gitignore_filter.py`; `_paths.py` define el confinamiento.

`SourceFilter` decide si una identidad relativa queda excluida. Compone tres
responsabilidades explícitas: reglas incorporadas, `.kenignore` de raíz y reglas
Git por ancestro. Las dos primeras son barreras independientes; una negación Git
no puede levantarlas. Dentro de Git, la decisión aplicable más profunda prevalece.
Un matcher pertenece a un recorrido: las reglas no quedan obsoletas entre llamadas.

`ProjectSources` coordina un recorrido confinado. Reutiliza `ProjectPaths` de M1,
conserva identidades relativas, ordena cada directorio y usa una pila como el
original. Publica archivos y directorios; quien solicita archivos filtra el tipo.
No depende de modelos, almacenamiento, Git ejecutable ni intérprete Python.

Uso representativo:

```rust
let sources = ProjectSources::new(paths, context);
for item in sources.walk(Path::new("pkg/src"))? {
    let entry = item?;
    if !entry.is_dir { index_source(entry.path); }
}
```

## Contrato

- Conservar literalmente las 16 reglas de `ALWAYS_IGNORE` del original.
- `.kenignore` sólo se lee en raíz; cada `.gitignore` afecta a sus descendientes.
- Negaciones, patrones anclados, directorios, `**`, clases, espacios escapados y
  comentarios se comparan con `pathspec` del oráculo congelado antes de portar.
- Se incluyen archivos de reglas salvo que una regla los excluya; archivos ocultos
  no reciben una exclusión implícita. No se consultan exclusiones globales de Git.
- Un directorio excluido se poda antes de enumerarlo. El scope conserva reglas de
  todos sus ancestros y nunca visita hermanos. Un ancestro excluido no se reabre
  por una negación descendiente. Scope inexistente o archivo produce lista vacía,
  como el recorrido original; scope externo falla con `ProjectError`.
- Scope que apunta por symlink interno usa la identidad canónica original. En el
  recorrido completo se conserva el alias relativo del enlace interno.
- Conservar orden observado: entradas ordenadas por directorio; subdirectorios se
  recorren desde una pila LIFO. No prometer un orden global distinto.
- Leer reglas como UTF-8 con sustitución y separar líneas igual que Python.
  Las reglas ilegales deben tener resultado diferencial explícito; no omitirlas
  silenciosamente para hacer pasar la comparación.
- Corrección de integridad explícita: el original puede seguir enlaces externos o
  ciclos encontrados durante la enumeración. Rust informa error identificado y
  poda ese enlace. Un enlace interno acíclico sigue funcionando. Errores de acceso
  durante el recorrido se informan, sin convertirlos en ausencia probada.
- Comparar nombres Unicode y conservar rutas nativas. El transporte JSON de la
  prueba exige UTF-8 y falla explícitamente con nombres no representables.
- Ninguna escritura, borrado ni modificación de fuentes o reglas del proyecto.

## Implementación elegida

La revisión final demostró que `ignore0.4.33`/globset cambia llaves literales,
comodines Unicode y prioridades de directorios. Se sustituye por `SourcePatterns`,
una adaptación nativa del algoritmo pathspec1.1.1, con `regex1.13.1` ya fijado en
el workspace. Su archivo conserva atribución y licencia MPL2.0; composición y
recorrido siguen perteneciendo a Ken. Las clases sin cierre se descartan como
el original; rangos descendentes, escapes sin carácter y `!` sin patrón fallan.
No se invoca Python ni Git para decidir reglas.

Los directorios pendientes se revalidan al abrirse. La enumeración usa un
descriptor de raíz y `openat` sin seguir enlaces en cada componente canónico;
`fdopendir/readdir` enumera el descriptor mantenido, cerrando la ventana entre
comprobación y apertura. La identidad lógica del alias no se sustituye por un
nombre de descriptor. Scope inexistente bajo un archivo se reconoce antes de
consultar reglas de directorios imposibles.

## Aceptación

Fixtures reales y captura independiente del original acreditan reglas compuestas,
orden, scopes, Unicode, archivos especiales y enlaces internos. Casos de enlaces
externos/ciclos y errores de acceso acreditan por separado la corrección declarada.
Se ejecutan pruebas Rust, diferencial por proceso nativo fuera del checkout con
PATH sin Python, formato y clippy, en macOS arm64 y Linux aarch64. Los manifiestos
de evidencia guardan fuentes, binario, casos, salidas y hashes originales.
La aceptación de M2 se conserva contra una copia exacta de sus fuentes; no se
repite inferencia neural para cambios de recorrido. Los originales siguen intactos.

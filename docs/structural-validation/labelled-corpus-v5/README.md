# Precisión de Builder: configuración y constructores

2026-09-12. La consulta mutable exige que un paso no constructor reciba el valor
almacenado en un campo usado para construir el producto. No basta que ese paso
modifique estado interno o tenga un parámetro que ignore.

El [reescaneo de ReversedLinesFileReader](rollover-builder-after.json) no produce
Builder y termina dentro del presupuesto. Corrige JAVA-01 del informe inicial;
no corrige su clasificación Prototype ni demuestra ausencia de otros falsos positivos.

También se corrigió la clasificación de constructores C++ inline: no son pasos
de configuración separados. El IR 1.11.1 invalida las caches anteriores.

Se agregaron 21 regresiones: positivos y negativos de configuración en Python,
JavaScript, TypeScript, Java y C#, más el constructor C++ que antes bastaba para
clasificar un objeto con método de copia como Builder. Inputs transformados y
presets sin parámetros necesitan variantes adicionales; la variante director
sigue disponible para construcción coordinada.

El reescaneo de los mismos 281 ejemplos conserva **52 etiquetas esperadas**,
sin ganancias ni pérdidas frente a v4. Todas las consultas completaron su
enumeración. No es una cifra de precisión. Los JSON y manifest fijan las fuentes
y el estado del analizador usado durante el escaneo.

El falso positivo de Memento/Originator continúa abierto: setter + snapshot y
configuración + producto pueden compartir la estructura observable. No se agregó
un filtro por nombres ni una exclusión automática entre patrones coexistentes.

## Validación posterior: Prototype Rust

IR 1.12.0 incorpora la variante `prototype#derived-clone`. El
[reescaneo del ejemplo oficial](rust-prototype-after.json) detecta Circle en
RefactoringGuru/design-patterns-rust, con 14 estados y enumeración completa.
Es evidencia sintáctica de derive Clone y llamada sobre el mismo tipo; no se
expanden macros, no se resuelven custom derives importados y no se prueba copia
profunda. El total 52/281 anterior sigue siendo la línea base previa a esta variante;
no se recalculó todo el corpus después de agregarla.

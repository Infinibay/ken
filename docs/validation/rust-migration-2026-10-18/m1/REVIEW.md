# Revisión independiente M0/M1

Reviewer: `gpt-6-astra`, contexto fresco, sólo lectura, sin subdelegación.
Rango: `96a9d2d5ed5b7a6dc51b13c8e97e290cae7c9908..bce986844bb62b540d0d2ca31ccdc393b2fb0e6b`.
Método: Superpowers executing-plans/requesting-code-review. Una revisión del
conjunto y una pasada de correcciones TDD del autor, sin segunda revisión.

## Resultado del reviewer

Sin Critical. Un Important reproducido: el resolver sólo retenía enlaces activos
y expandía repetidamente destinos compartidos ya terminados. Con `l0 -> .` y
`lN -> l(N-1)/l(N-1)` hasta 20, pathlib resolvió en aproximadamente 0,2 ms y el
binario release revisado superó cinco segundos. Efecto: una ruta válida podía
bloquear `status` y consumir recursos de forma exponencial.

Fortalezas observadas: responsabilidades claras, transacción readonly única para
contadores/paths y cobertura WAL, transporte health con proxy/redirect desactivados
y deadline global, validación concreta de paths antes de normalizar, comparación
estricta de tipos/orden y controles negativos. El reviewer verificó sin deriva los
manifiestos original y congelado, los archivos revisados y la identidad del
binario correspondiente al recibo macOS.

Veredicto del reviewer: **With fixes**. La matriz Linux/macOS completa y comparable
seguía pendiente; no se atribuye al reviewer una ejecución completa adicional de
las suites o benchmarks.

## Correcciones de la única pasada

1. Reutilizar destinos terminados dentro de cada resolución y conservar el estado
   activo para detectar ciclos. Regresión de proceso real con 25 enlaces y deadline
   de dos segundos: se observó FAIL por timeout y después PASS. Permanecen los
   tests de destinos inexistentes, enlaces interiores, `..`, escapes y ciclos.
2. Hallazgo adicional del autor durante el triage: un archivo indexado reemplazado
   por un enlace cíclico producía Python exit 0/stale=1 y Rust exit 1. Se centralizó
   la semántica de existencia de pathlib, conservando errores de permisos/otros IO.
   Tres regresiones RED→GREEN cubren enlace indexado cíclico, path NUL no codificable
   y marcador cíclico con descubrimiento del ancestro. `libc=0.2.191`, ya transitiva,
   pasa a dependencia Unix directa; `FilesystemLoop` todavía es nightly-only.

Las 28 pruebas de integración Rust y clippy pasaron tras las correcciones. Se
añadieron cuatro casos públicos, conservando los 58 anteriores: 62 en total.
Los recibos anteriores identifican las fuentes anteriores; el cierre requiere
nuevos recibos de las fuentes corregidas y la suite Python completa.

## Minor diferidos

- `crates/ken-core/tests/status.rs:131` del rango revisado: el test de concurrencia
  repite el mismo inventario observable; alternar inventarios y añadir un control
  no transaccional reforzaría su capacidad de detectar regresiones.
- `IMPLEMENTATION.md:63,84` del rango revisado: la lista histórica de decisiones
  omite la nota que reemplazó la solución anchored por el resolver propio. Su
  marcador no tenía la sintaxis esperada por la extracción; la guía sí explica
  el reemplazo. La corrección histórica se deja diferida como indicó el proceso.

## Aspectos que el reviewer dejó fuera de su juicio

- M2–M8: siguen pendientes; la instrucción del usuario exige continuarlos después
  de cerrar esta entrega, sin atribuir sus capacidades a `status`.
- Windows: no se infiere certificación; la aceptación aprobada exige Linux/macOS.
- Cambios Python previos y tests/docs ajenos: se conservan como entrada del oráculo,
  fuera de los commits de migración.
- CI remota y aceptación final Linux/matriz: no estaban acreditadas en la evidencia
  disponible; no se ejecutó CI remota y la comprobación Linux local es obligatoria.
- Reejecución independiente de todas las suites/benchmarks: el reviewer inspeccionó
  recibos, identidades y tests relevantes y ejecutó el repro del resolver. Las
  ejecuciones completas del autor siguen siendo la evidencia de esas suites.
- Verificación semántica manual de cada entrada CLI/MCP: se revisó captura y
  cobertura del inventario; no se certifica como migrado cada comando histórico.

Las decisiones, sus riesgos y los dos Minor diferidos quedan también en el ledger.

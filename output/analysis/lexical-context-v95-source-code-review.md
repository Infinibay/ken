# Revisión del slice fuente léxico95

**APTO de código para preparar el catálogo sólo de fuente, con las correcciones actuales.** No es aprobación de artefactos reales, proyección/evidencia, PRE-FIT o API. Helper `cbac763ea551be45d2a4b8cf463cb7e56ce1416ac76cd40e88e03a92294cb034`; productor prospectivo `eff1b6a2bdbb0894cbec36ce27e129b432f8bfadac9d4691e123e60a20fefeea`. Falta ligar el freeze95 real a esos bytes antes de ejecutarlo. No ejecuté el productor ni creé marcadores.

Los tres contraejemplos detectados quedaron cerrados:

- C válido producía una excepción porque el frontend estructural no soporta `c`. Ahora devuelve `structural_grammar_unavailable`, sin autorizar contexto ni ampliar core.
- `const one=()=>1, unrelated=eraseAll()` incluía el segundo initializer porque una sola raíz callable no hacía exclusivo al carrier. Ahora exige un único declarator con value callable directo; ambas formas, en una y varias líneas, se rechazan.
- Los bindings legacy de destructuring admitían defaults y claves computadas como supuesto contexto de una función: `const {value=eraseAll()}=()=>1`, `const {[eraseAll()]:value}=()=>1` y la variante array. Ahora el name del declarator debe ser identifier y los assignments un target estático; los tres se rechazan. Los computed/call-receiver assignments tampoco autorizan contexto.

Verifiqué22tests del slice y25probes adicionales en Python/JS/TS/Rust/Go/Java/C++/C. En29contextos aceptados, cada texto y parte coincide byte a byte con su fuente, CRLF/UTF8 se preservan y los Passages permanecen intactos. Las entidades/ordinales de hijos no se reasignan al padre. Los scopes conservan fronteras y parent indexes; helpers muertos, redefiniciones por rama, clases locales y closures anónimas siguen siendo sólo fuente léxica, sin afirmar ejecución, target o retorno resuelto. El [detalle de probes](lexical-context-v95-review-probes.json) conserva los resultados.

El productor revisado prepara exclusivamente fuente16/6314archivos y espera50967owners originales. Usa índices RO y hashes66c, bytes físicos, generación ligada al hash del índice, inventarios por archivo y hashes de catálogos. Los casos sin pasajes/parser y las ambigüedades quedan explícitos. No abre requests/candidatos/features/referencias/scores ni carga encoder/modelo; no tiene branch de ajuste o evaluación.

Límites que deben conservarse: C no tiene contexto estructural; no se excluye del inventario. Export functions y assignments con semicolon pueden quedar rechazados conservadoramente por la guarda de línea parcial. El token de generación viene del caller. La validación del helper es de partición/extent canónicos, no una attestation de todos los campos/chunks ni del origen del índice; el productor y la auditoría real deben seguir ligando la procedencia fuente7. Ninguna de esas limitaciones da autoridad para rellenar huecos o atribuir ejecución.

Falta congelar95 con estos hashes y auditar los catálogos ALL16 reales antes de cualquier fase de consultas/proyección/target/fit. El protocolo mantiene fuente/identidades/regiones originales, perfiles anteriores, referencias, ALL400 y aceptación estricta; una futura política de evidencia necesita versión explícita y presupuestos finales, incluyendo procedencia. No hay resultado de calidad o recurso emitido por esta revisión.

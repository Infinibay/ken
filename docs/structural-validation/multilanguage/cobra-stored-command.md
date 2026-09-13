# Cobra: Command mediante closures almacenadas

La variante `command#stored-closure` detecta cuatro closures RunE de los comandos
de completado en Cobra, en `completions.go:831,867,895,917`. Cada una captura `out`
y `noDesc` de su fábrica, se asigna al campo RunE y se invoca desde `execute`
(`command.go:1015`). Los ocho [testigos](cobra-stored-command-witnesses.json)
son combinaciones closure/captura, no ocho comandos distintos.

La revisión confirma acciones de generación de completado Bash, Zsh, Fish y
PowerShell con configuración retenida. El [escaneo](cobra-stored-command.json)
fija commit, hashes y presupuestos; las 23 consultas completaron en 19 archivos,
sin diagnósticos de parsing. Se usaron los mismos archivos que en la auditoría
Composite anterior. No se ejecutó código del repositorio externo.

Correcciones necesarias:

1. Conservar los inicializadores nombrados de un literal struct Go como
   ocurrencias, con valor y campo resuelto; una clave de mapa no es un campo.
2. Resolver tipos nominales entre archivos del mismo directorio y paquete Go.
3. Conservar capturas de bindings explícitos de funciones exteriores. La primera
   prueba confundió `fmt` con una variable capturada, porque una referencia previa
   había creado un storage sin declaración. Ahora ese caso se excluye y tiene test.

Los 24 tests propios cubren Python, JavaScript, TypeScript, C# y Go, negativos por
falta de captura o llamada, campo diferente, mapa frente a struct, otros paquetes
y directorios, tipos ambiguos y referencias a paquetes.

Límites: se vinculan campos de un tipo, sin análisis sensible a cada instancia ni
prueba de orden temporal. Captured Strategy y Command pueden compartir esta forma;
la intención requiere revisión. La variante `command-object` conserva su testigo
incorrecto de búsqueda de plantilla, descrito en [la auditoría anterior](cobra-composite.md).
La consulta pública ahora conserva ambas pruebas al deduplicar por tipo. La
[verificación de evidencias](cobra-alternative-proofs.json), sobre los mismos
19 archivos y hashes, devuelve una coincidencia Command con dependencias
`command#command-object` y `command#stored-closure` visibles en su evidencia.
Completó con 1.279 estados, 535 filas examinadas y 2,413 ms de consulta. Es una
medición individual que excluye construir el grafo. Esta mejora hace auditable
el testigo incorrecto; no corrige todavía la variante `command-object`.

La [regresión compacta](stored-command-corpus-regression.json) conserva manifest,
hashes y diferencias respecto a v9: mismos 281 ejemplos, mismas 53 presencias,
ninguna combinación de roles cambiada y ninguna consulta incompleta. Los archivos
brutos del runner quedaron en `/tmp/ken-corpus-v10-final`; el resumen persistido no
depende de que ese directorio temporal se conserve.

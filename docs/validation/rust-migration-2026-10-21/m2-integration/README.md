# Integración nativa M2

Este paquete conserva las nuevas llamadas públicas de ModelFactory y los gates
finales de Rust/Python/almacenamiento. Corresponde al plan 2026-10-21; la regresión
final se ejecutó el 2026-10-23. La revisión independiente del plan se registra como
un cierre separado antes de avanzar a M3.

Se ejecutaron24 perfiles en macOS y9 en Linux, con los tipos/dispositivos fijados.
Cada encoder usó un lote original representativo y cada juez conservó la llamada
vacía y el primer score satisfactorio. Vectores/scores y preparación real coinciden
exactamente con el adaptador directo acreditado. No se atribuyen estas muestras
al corpus neuronal completo anterior ni se reetiquetan sus hosts/hashes.

También hay llamadas reales de tabla NPZ, Potion, contexto, reranker y traducción;
NPZ/Potion incluyen 8consultas concurrentes. FastEmbed descargó los 91 MB públicos
registrados con Rust en cada plataforma y luego los reutilizó offline. Linux
conserva execve/execveat/connect reales; las fases offline no conectan. Las fuentes
prestadas y todos los originales permanecen intactos.

Pasaron 313 tests Rust en macOS y 303 en Linux, incluyendo todos los casos descubiertos;
los subprocesos de pruebas se contabilizan dentro de su caso padre. Formato y
Clippy con warnings denegados pasaron. La recuperación de almacenamiento ejercitó
los cinco historiales originales mediante el driver actual, en copias aisladas.

La suite Python completa inicial dio 15991pasados/10xfail en macOS y15990 pasados/
10xfail/1fallo en Linux. El fallo nuevo era una ruta de preparación específica de
macOS en el test del probe. Se corrigió usando CARGO_TARGET_DIR y se verificó en
ambos sistemas. Los únicos otros cambios durante esas suites fueron las herramientas de validación
y sus tests para interpretar subprocesos Rust y comprobar el comando de auditoría. Se conservan los
XML/logs iniciales, las fuentes exactas previas, los 7 tests específicos ejecutados
y el XML combinado derivado mecánicamente:15994 pasados/10xfail por plataforma.
Ningún fallo original se eliminó ni se sustituyó un caso ajeno a esas reparaciones.

INDEX.json vincula fuentes productivas, tooling actual, hosts y tres manifiestos
anteriores fijos. FILES.json autentica cada archivo de este paquete. El replay
reinterpreta los outputs y los historiales; un flag passed no sustituye datos.
Las pruebas de corrupción usan además capturas nativas reales y rechazan perfiles,
roles, versiones, módulos, valores, conexiones y subprocesos alterados.

La dependencia Python pertenece exclusivamente al oráculo y al replay de pruebas;
el ejecutable de producto observado es Rust. La aplicación completa aún requiere
M3–M8 y el comando original ken sigue conservado.

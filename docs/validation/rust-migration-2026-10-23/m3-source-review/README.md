# M3a: cierre de revisión y reparación

La única [revisión final](REVIEW.md) detectó seis defectos Important en el matcher,
scopes y confinamiento del iterador. Todos se repararon en un pase TDD;
[las decisiones](RULINGS.md) conservan el razonamiento, la corrección de la
interpretación errónea de rangos y la licencia de la adaptación. No hay menores
nuevos ni hallazgos diferidos de este bloque.

Cada plataforma nativa (macOS arm64/Linux aarch64) pasó34pruebas Rust del núcleo,
24pruebas Python de herramientas, formato y clippy. Los casos se autentican contra
la lista descubierta, evitando contar dos veces el subproceso de permisos.
El listado Python se reutiliza de la captura anterior sin cambios de tests; el
XML y las ejecuciones son actuales. Las pruebas de permisos usan un usuario real
sin privilegios, también bajo el controlador Docker root.

El diferencial actual cubre702decisiones originales (270previas+432nuevas) y
134recorridos por plataforma (51previos+83nuevos), con entradas exactas, orden,
tipos y scopes. Ambas capturas originales nuevas coinciden. Cuatro formas
ilegales producen errores y tres formas de clase sin cierre son no-ops, como el
original. La sustitución de un directorio pendiente por un enlace externo tiene
una regresión determinista a través de la API pública.

Los procesos nativos se copian fuera del checkout, usan PATH vacío y auditoría de
carga. Linux añade el registro real de execve/execveat/connect. Las capturas crudas
se conservan comprimidas en dos archivos para evitar cientos de archivos de
trabajo adicionales. `VERIFY.py` extrae sólo en un temporal propio, autentica
cada captura y compara el snapshot preciso de fuentes. Para el cierre actual:

```sh
PYTHONPATH=. .venv/bin/python docs/validation/rust-migration-2026-10-23/m3-source-review/VERIFY.py --current
```

El entorno de validación es la `.venv` preparada existente, con NumPy por los
helpers compartidos de evidencia; el replay no ejecuta inferencia. El binario
Rust de fuentes no carga Python, NumPy ni modelos.

`--current` comprueba además las fuentes del checkout. Para auditar este recibo
histórico después de migrar otros componentes, omitir ese argumento. Los
originales1066siguen intactos y los recibos previos quedan ligados a sus propias
fuentes; sus resultados neurales no se ejecutaron de nuevo.

M3a queda aceptado con esta reparación. Parsers, modelo común y escritura de
índices siguen perteneciendo al resto de M3. Este recibo no acepta M3 ni toda la
migración. No se instala/reemplaza el comando original ni se promueven escritores
Rust sobre datos de producción.

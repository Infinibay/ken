# Archivos de modelos verificados en Rust (T2)

`ModelFileSource` conserva ubicaciones absolutas explícitas sin cargar pesos.
`ModelAssets::verify_files` copia sus archivos declarados a un directorio propio,
verifica tamaño y SHA-256 sobre el mismo descriptor regular abierto y entrega
`VerifiedModelFiles`. El directorio y sus subdirectorios son0700; los datos
finales son0444. Las copias son archivos nuevos, independientes de las fuentes,
y su propietario los elimina al liberarse. No se exponen rutas privadas al
llamador público. La API anterior de snapshots en memoria permanece.

La comprobación de regularidad/tamaño y la copia con hash viven en
`verified_file`: se conservan O_NONBLOCK/O_NOCTTY, el control del inode abierto,
el límite tamaño+1, el rechazo de dispositivos/FIFO y la aceptación de symlinks
HF cuyo destino abierto es regular. La copia usa64KiB y reintenta Interrupted,
como el antiguo read_to_end. Los errores no publican un propietario verificado.

`verify_onnx_dependencies(nombre, archivos)` permite verificar la clausura sin
filtrar rutas ni acoplar el propietario genérico al formato ONNX. El lector
Read+Seek salta payloads y comparte el decodificador de varints con el lector
anterior. Recorre los carriers de TensorProto en grafos, atributos, funciones,
sparse tensors y entrenamiento. Limita profundidad64, campos1.000.000 y strings
de metadatos externos4096bytes; rechaza escapes, archivos no declarados, claves
ambiguas/basepath y rangos negativos/desbordados/fuera de archivo. La regla de
nombres relativos tiene una sola definición en ModelAssets.

Los ensayos de `measurement/` usan un ejecutable Rust que depende directamente
de ken-models, con versiones de dependencias fijadas al Cargo.lock principal.
Copian, auditan y liberan los30conjuntos reales (18.953.017.670bytes sumando las
configuraciones compartidas repetidas), incluido el archivo externo Jina de
2.291.339.168bytes. El límite de aceptación de128MiB se comprueba sobre el pico
RSS getrusage del hijo; no es un límite del kernel. Los hashes de todas las
fuentes se comprueban antes/después. Una declaración con SHA erróneo en
`tokenizer_config.json` provoca un fallo después de copiar los pesos grandes:
el staging queda vacío y las fuentes permanecen intactas. Las pruebas con
Write sobre un destino real ejercitan además truncado a mitad de copia y error
de escritura, con limpieza antes de devolver error.

Esto verifica propiedad de archivos y dependencias, sin ejecutar la red del
encoder FastEmbed. La inferencia y la aceptación conjunta de34controles siguen
en las tareas posteriores. El corpus original T1 se conserva en el directorio
hermano `m2-fastembed`, con inventario independiente.

El máximo RSS observado fue6.438.912bytes (~6,14MiB). Los recibos son
de macOS arm64; la aceptación acumulada exige todavía Linux y la inferencia
completa en T7. No se declara M2 terminado ni mejora de velocidad.

Verificación final macOS:194ejecuciones Rust,0fallos/ignorados, incluidos los
ejemplos y la comparación byte a byte del head ONNX anterior; fmt y Clippy de
todo el workspace pasan. Los1.066originales mantienen sus hashes. Las primeras
pruebas detectaron permisos0755 y propagación de Interrupted; ambos fallos
tienen pruebas RED→GREEN conservadas en execution/.

Los logs se conservan íntegros como gzip, con hash/tamaño del log original y
del transporte. Esto preserva también los saltos finales emitidos por Cargo.

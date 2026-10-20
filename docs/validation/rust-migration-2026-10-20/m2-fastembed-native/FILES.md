# FastEmbed T6: procesos nativos y fuentes independientes

Este corte acredita los30modelos/300casos en macOS arm64 y Linux aarch64 contra sus respectivos originales, con inputs exactos y1e-6absoluto+1e-6relativo en vectores F32 finitos. Son15660filas por plataforma,60casos vacíos y8fallos originales FP16 alemanes conservados como errores reales, sin resultados fabricados ni estado listo.

Cada modelo usa un proceso Rust nuevo, con binario/core/catálogo copiados fuera del checkout y PATH de sentinelas. Linux registra exactamente un exec por rol. Cargo-tree y dependencias enlazadas se auditan sin Python. El productor incluye39fuentes/Cargo/registro de runtime compilados, incluido el propio probe; hashes de binario/core/catálogo se verifican antes y después. Las solicitudes contienen sólo operación, ID, lado y textos.

Las cinco familias de propiedad prueban un hash corrupto en la última configuración después de copiar pesos, limpieza del staging fallido, reparación real, archivos privados0700/0444 regulares con nlink1/inodos distintos/SHA exactos, retirada externa de las fuentes COPIADAS y resultados idénticos, y limpieza al salir. Las fuentes canónicas permanecen intactas. El proceso no tiene flags de fallo ni preparación de fuentes.

Los registros guardan stdout/stderr completos en gzip autenticado y limitado a16MiB; no se recortan mensajes ni se duplican vectores en los resúmenes. Los picos retienen el HWM bruto y su envolvente observada (Linux informa aproximaciones que pueden disminuir). El tiempo de proceso cubre Popen a wait e incluye esperas del controlador; las llamadas registran su tiempo de operación y las pruebas de propiedad separan prepare de embed. No se afirma aceleración ni ejecución numérica GPU.

El anexo native-case-alias conserva dos procesos léxicos E5 (nombre canónico y mayúsculas) con sólo cuatro configuraciones y sin pesos: query/passage coinciden con el original y no cargan runtime ni sesión.

Las pruebas focalizadas, de protocolo y de procesos se conservan en execution. El inventario FILES.json acredita todos los bytes publicados y las versiones originales de los logs. Esta prueba es histórica y verificable;T7 aún debe componer los34controles/33huellas completos en ambas plataformas. FastEmbed_accepted=false y M2_accepted=false se conservan hasta esa aceptación.

# M2: tabla estática NPZ nativa

Deriva del contrato de [migración completa](2026-10-18-rust-migration-design.md)
y del inventario de [runtimes M2](2026-10-18-rust-model-runtime-design.md).
El usuario pidió continuar hasta terminar, con ejecución nativa y originales
intactos. Este corte implementa la tabla ya existente, sin cambiar el producto.

## Uso y responsabilidades

```rust
let encoder = StaticTableEncoder::from_npz(&artifact_bytes)?;
let query = encoder.embed_query("¿Dónde se guarda la configuración?")?;
let passages = encoder.embed_passages(&["save_config", ""])?;
```

`StaticTableEncoder` convierte textos en vectores usando una tabla autocontenida.
El lector NPZ valida y convierte matrices; el encoder conserva la política del
tokenizer serializado y posee tablas/metadata. Un probe coordina archivos y JSON
para comparación. Ninguno llama Python ni abre datos del proyecto. La resolución
de `KEN_STATIC_HEAD`/cache/bundle pertenece a la futura fábrica de modelos.

## Contrato numérico y de formato

- Artefacto real: `src/ken/embedder/data/ken__static-qwen3-r512-v2.npz`,
  23135664 bytes, SHA256 `e6ab79ad2462d447d367ac4c9735e1062cb752ba6ed50901773ec2bd427a1ff0`.
- NPZ ZIP almacenado/comprimido, NPY little/big endian y orden C/Fortran.
  Arrays requeridos: `lut`, `A`, `B`, `tokenizer`, `meta`; `A_scale` si A es int8.
  LUT int32/int64; A int8 o F16/F32/F64; B y escala F16/F32/F64 convertidos a F32.
  Otras conversiones permisivas de NumPy quedan pendientes, sin atribuirlas al perfil.
- LUT unidimensional, índices válidos en A (negativos desde el final como NumPy).
  A/B bidimensionales, rango y dimensión positivos, formas compatibles; escala
  por fila. Tokenizer/meta son bytes uint8 UTF8 y meta objeto JSON.
  Datos corruptos/no finitos/objetos pickle no se ejecutan ni producen éxito.
- `encode_batch(..., add_special_tokens=False)` conserva padding/truncation
  serializados, UNK y tokens añadidos. No aplica límite512, prefijo ni regla UNK
  de Model2Vec. `token_count` usa encode individual con la misma política.
- Gather LUT→A, suma F32 por texto, proyección F32 con B y norma L2 F32 acotada
  por `1e-12`. Int8 se desquantiza a F32 con escala de cada fila al cargar.
  Vacíos producen ceros si el tokenizer no añade padding. Queries/passages
  comparten tabla; batch vacío devuelve[]; resultados son copias independientes.
- Paridad: IDs/count exactos, dimensión1024 real; ceros exactos, finitos y
  `atol=2e-6`, `rtol=1e-5`, coseno>=0.999999 fijados antes de implementar.
  No aumentar tolerancias para ocultar algoritmos incorrectos.

## Evidencia y aceptación

Fijar primero casos y salidas del Python congelado: español/Unicode, código,
vacío, UNK, mezcla de vacíos, repeticiones largas y variación de lote. Fixtures
pequeños cubren dtype, endian, Fortran, política serializada y errores.
Las salidas se capturan mediante un proceso que verifica el import congelado
y hashes antes/después. El Rust compilado se ejecuta fuera del checkout con PATH
restringido, auditoría de librerías y strace Linux con sólo el exec inicial.

Linux y macOS deben comparar los mismos casos, artefactos y fuentes. Ejecutar
workspace Rust/fmt/clippy y pruebas originales/tooling relevantes por tarea;
suite Python completa al cierre, sin fallos nuevos ni originales omitidos.
Conservar todos los recibos y muestras. Revisión fresca única al terminar este
plan. Aceptar sólo este perfil; M2 completo sigue pendiente hasta cubrir todos
los modelos y datos. No promover entrypoints ni borrar originales.

## Dependencias y alternativas

Se elige `npyz=0.9.1` con half para NPY, `zip=6.0.0` con deflate y sin features
por defecto para contenedor, y `ndarray=0.17.1` sin BLAS para proyección portable.
Las [fuentes oficiales de npyz](https://docs.rs/npyz/0.9.1/npyz/) documentan F16,
endianness y orden; la compilación real verifica compatibilidad con Rust1.95.
`ndarray-npy` no incluye F16 directamente; un parser NPY casero duplicaría formato.
No se carga NumPy ni se introduce dependencia dinámica en Python/BLAS del host.

# Recibo macOS arm64

Fuentes nativas en `6ef6aa08`. Los 16 gates locales pasaron; la aceptación
conjunta también requiere Linux y la revisión del conjunto. `M2_accepted=false`
permanece explícito porque los otros runtimes y los datos siguen pendientes.

Los logs y JUnit crudos, las salidas completas de ambos procesos y los inputs
de medición se conservan en `.ken/rust-migration/m2/validation/`. Sus hashes no
se alteraron. La suite Python emitió una advertencia de deprecación de hf_xet;
los dos errores históricos de mypy por transformers ausente están en summary.

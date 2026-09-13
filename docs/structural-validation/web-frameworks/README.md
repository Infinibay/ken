# Auditoría inicial de Flask y consultas modernas

**Actualización IR 1.23.0:** el falso negativo del despacho está corregido mediante
la variante declarativa `adapted`. Se revisó el registro, slot heredado, clave
derivada y ambas ramas del adaptador. [Resultado y límites](flask-adapted-dispatch.md).
Las mediciones y observaciones de este documento se conservan como historial.

Fecha: 2026-09-12. 24 archivos src/flask, 6051 entidades; sin diagnósticos de parsing. Commit: d73fa1cdcbd8b1465c151db8924ba58b1dd14e35. No se ejecutó Flask ni se instalaron sus dependencias.

## Problema de búsqueda corregido

Dispatch Table agotaba el presupuesto de 100000 estados antes de resolver el registro y la invocación indexados. Se reordenaron sus filtros manteniendo la misma conjunción lógica: los joins de relaciones se ejecutan antes de filtros de parámetros y desigualdades.

| Medida | Antes | Después |
|---|---:|---:|
| Estados | 100001 (cortado) | 255 |
| Filas examinadas | 69190 | 127 |
| Tiempo de consulta observado | 326.984 ms (incompleta) | 0.544 ms |
| Dispatch Table | 0, incompleto | 0, completo |

Los tiempos son una observación local, no un benchmark general. Se verificaron hashes de entrada idénticos. Una regresión con 150 métodos adicionales y seis parámetros cada uno exige completar bajo 2000 estados y conservar el match real.

## Relaciones que faltan para detectar el despacho Flask

1. **Registro e invocación heredados.** [Scaffold]( https://github.com/pallets/flask/blob/d73fa1cdcbd8b1465c151db8924ba58b1dd14e35/src/flask/sansio/scaffold.py#L108) declara view_functions; [App.add_url_rule](https://github.com/pallets/flask/blob/d73fa1cdcbd8b1465c151db8924ba58b1dd14e35/src/flask/sansio/app.py#L661) registra endpoint → view_func. La invocación está en Flask, una subclase. Hace falta preservar la identidad del campo heredado y los métodos efectivos, sin mezclar campos homónimos de instancias distintas.
2. **Clave derivada.** [dispatch_request](https://github.com/pallets/flask/blob/d73fa1cdcbd8b1465c151db8924ba58b1dd14e35/src/flask/app.py#L969) obtiene req desde ctx.request y rule desde req.url_rule; la clave usada es rule.endpoint. La query actual exige una clave que sea un parámetro directo. Hace falta flujo de accesos a miembros y aliases.
3. **Adaptación del handler.** La entrada se pasa por [ensure_sync](https://github.com/pallets/flask/blob/d73fa1cdcbd8b1465c151db8924ba58b1dd14e35/src/flask/app.py#L1068) y se invoca el callable resultante con kwargs. El método retorna el original o una adaptación async. No se debe modelar como identidad incondicional ni por el nombre ensure_sync.

Estos son límites del modelo, no motivos para eliminar las condiciones de correlación de la query. La ausencia inicial era indeterminada por presupuesto; tras la corrección queda un caso real de despacho que esta variante no cubre.

## Otros resultados

Dependency Injection devuelve cinco combinaciones de roles sobre tres clases: AppContext, BlueprintSetupState y DispatchingJinjaLoader. Son candidatos de inyección/uso; no se han certificado todas sus rutas runtime. Continuation Wrapper devuelve cero; eso no demuestra que Flask no tenga wrappers.

## Reproducción

`.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/flask --prefix src/flask/ --collection modern --output /tmp/flask-modern.json`

[Antes](flask-before.json) y [después](flask-after-query-order.json) conservan fuentes, commit, hashes del motor, presupuestos, matches y outcomes. La opción --collection puede repetirse para usar otras colecciones del registro público.

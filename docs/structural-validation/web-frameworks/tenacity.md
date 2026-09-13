# Tenacity: variante de retry aún no cubierta

Se descargó https://github.com/jd/tenacity y se analizaron estáticamente 12 archivos
de `tenacity/`. El [reporte](tenacity-retry.json) fija commit, hashes, presupuesto
y resultados. No hubo diagnósticos de parsing y la consulta terminó completa,
sin matches. Eso no indica ausencia del patrón.

La revisión de `Retrying.__call__`, `tenacity/__init__.py:547–560`, confirma un
retry real coordinado por estado: `iter(retry_state)` decide DoAttempt, DoSleep
o resultado final. El intento llama `fn(*args, **kwargs)` dentro del try, almacena
la excepción o el resultado y vuelve al bucle por fallthrough; sólo retorna cuando
la acción deja de pedir otro intento o una espera.

**Omisión confirmada.** La consulta original `resilience.exception-retry` exigía
un `continue` explícito en el handler y un retorno del intento en el try. Ninguna
de las dos formas está presente aquí. IR 1.46.0 añade fallthrough, pero mantiene
el requisito de retorno: el nuevo escaneo sigue dando cero matches. Ver la
[comparación](../multilanguage/instruction-core.md). Relajar la consulta a «hay try dentro de un
while» también aceptaría procesamiento por lotes o un servidor que atiende trabajos
diferentes, y no resolvería la correlación necesaria.

Para cubrir esta variante hay que vincular el resultado/estado del mismo intento
con la decisión de repetir, la espera y la terminación. Se necesita una variante
de consulta y evidencia de flujo entre métodos, además de negativos con tareas
distintas por iteración. El uso de Tenacity mediante decorators o un objeto de
política necesita resolución de API/imports y otra variante. No se ejecutó el
código externo ni se consideran estos ejemplos pruebas de comportamiento runtime.

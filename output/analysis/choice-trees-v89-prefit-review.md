# Revisión independiente 89: PRE-FIT APTO

El helper, controlador congelado y preparación real de los 16 folds son aptos para ejecutar exclusivamente el control 89 registrado. No encontré un bloqueo de matemática, fidelidad o aislamiento en esos artefactos. Observé cero heads y el gate cerrado al finalizar. No importé ni ejecuté LightGBM/optimización, entrené modelos, creé marcadores, modifiqué fuentes/referencias ni abrí la reserva.

Revalidé 6.314 archivos físicos, 64 artefactos fuente, 51 bindings del padre y todos los inputs. Las 167.360 filas de 251 features, las etiquetas originales y las 400 decisiones de entrenamiento son idénticas a 88b. Hay 358 grupos contribuyentes; 37 exactos y cinco sin positivo se omiten sólo del entrenamiento. Los 16 archivos de normalizadores y sus hashes de matriz/targets/starts son idénticos a 88b; aquí son diagnóstico: el Dataset futuro recibe las features **crudas**, no su normalización.

Para cada fold reconstruí las filas crudas, qids, targets y tamaños de grupo. Todas pertenecen a los otros 15 repositorios, antes de crear el Dataset o sus bins. Envenené las 25 consultas del repo retenido con NaN y etiquetas inválidas: los seis arrays preparados permanecieron iguales, en 96 comprobaciones de hash. Los scores entrenados de 69 se usan sólo en el replay del baseline; no participan en selección, normalización, features, targets ni gradiente. No se introducen negativos minados por modelos de otros folds.

La pérdida suma por consulta `logsumexp(scores) − target·scores`, con masa positiva uniforme. El helper devuelve exactamente `p−target` y la diagonal `p·(1−p)`. El cálculo independiente cubrió 200 casos y 1.323 coordenadas por diferencias finitas: error máximo de gradiente analítico 3,33e-16, de diferencias finitas 3,74e-10 y de diagonal por diferencias finitas 1,98e-11. Los 14 tests congelados pasan. Targets y starts se copian como arrays inmutables; offsets unsigned válidos funcionan, saturación y traslación por consulta son estables, y extremos finitos que desbordan la resta se rechazan.

El callback aplica el floor registrado de 1e-12 sólo a la diagonal. Se omiten los términos acoplados entre filas del Hessiano; este control es boosting con aproximación diagonal, sin garantía de Newton completo, convergencia de árboles, NDCG ni precisión estricta. El código primario instalado de LightGBM confirma que un objetivo callable recibe scores crudos y no aplica una transformación logística adicional.

Los 395 casos positivos actuales tienen un solo owner elegible. Por eso la aserción del controlador que compara labels binarios con targets probabilísticos es válida en estos datos. Un futuro grupo con varios positivos fallaría de forma cerrada: el helper admite esa fórmula, pero este controlador no tiene soporte general de múltiples positivos. No afecta este gate fijo ni permite cambiar etiquetas.

El fit futuro instancia cada fold desde cero, con 160 rounds, 15 hojas, mínimo 40 datos, lambda L2 2, learning rate 0,08 y seeds 42, CPU de un thread, determinismo y columnas forzadas. No hay validación retenida, checkpoint elegido, early stopping o variante secundaria. Se exige exportación numérica idéntica en todas las filas de entrenamiento y retenidas, y replay de las 400 consultas con evidencia 3 y scorer original. El gate posterior sigue siendo cinco aciertos adicionales frente a 286/298; no hay aceptación de API, default o reserva en este informe.

La cronología declarada es precisa: el texto de 89 se escribió en la misma invocación que devolvió por primera vez la calidad de 88b. No certifico una preregistración anterior a conocer cualquier resultado de 88b ni una independencia histórica mayor que la registrada.

Bindings que root debe revalidar para su marcador:

```json
{
  "engine_receipt": "5ab6da502c32b858383bec48b06e37b571ef7a74d4e2ae405ffff9f1755273c2",
  "controller_sha256": "7b2ea86863afc3c6281be8bbb605b398b3d36571438f88911bb778504d744aa3",
  "pre_fit_registration_sha256": "851442265fee37e8b5dd2e31e0e1a7304a315a9aa7089fef9a02fdc3f73ff511"
}
```

Evidencia detallada: `choice-trees-v89-prefit-review.json` y `choice-trees-v89-helper-review.json`. El cierre posterior deberá revisar los 16 modelos/trazas reales, paridad de exportación, los 400 replays y scorer; la aptitud previa no los anticipa.

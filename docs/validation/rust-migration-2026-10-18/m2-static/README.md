# M2: primer encoder estático

Los 18 casos de `cases.json` se fijaron antes de implementar Rust. La captura
`potion-reference.json` ejecuta el encoder original desde la copia congelada y
verifica los cuatro artefactos públicos del registro. No contiene rutas privadas.
Cada caso empieza con un encoder nuevo; las llamadas dentro del caso conservan
el orden y la caché. Los lotes guardan vectores distintos más índices de fila:
se preserva cada salida, incluidas las 1024/1025 filas, sin repetir sus bytes.

Las tolerancias F16/F32 se fijaron antes del port y constan en ambos JSON.
Los tiempos del oráculo son observaciones de preparación e inferencia por caso,
no una comparación de rendimiento. Cero, tokens, dimensión y orden se comparan
exactamente. Este registro no acredita todavía inferencia nativa ni cierre M2.

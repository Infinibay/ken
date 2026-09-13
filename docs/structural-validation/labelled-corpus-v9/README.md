# Composite nominal: regresión sobre el corpus GoF

Con IR 1.16.0 se repitieron los 281 ejemplos aislados y las 23 consultas canónicas.
Los hashes de entrada coinciden con v8; siguen presentes las mismas 53 etiquetas.
También permanecen iguales todas las combinaciones de roles (`match-changes.json`
vacío). Todas las consultas completaron el presupuesto.

La nueva variante Composite se validó además sobre Cobra, que está fuera de este
corpus educativo: un tipo y tres recorridos recursivos revisados. Ese positivo no
se suma a 53/281. Los 22 tests propios cubren cinco lenguajes y negativos por otra
operación, receptor distinto, elemento de otro tipo e índice Go confundido con hijo.

Ver [Cobra](../multilanguage/cobra-composite.md), que también registra un testigo de
Command mal clasificado y todavía pendiente. Las etiquetas del corpus no miden
precisión global ni eliminan los fallos documentados anteriormente.

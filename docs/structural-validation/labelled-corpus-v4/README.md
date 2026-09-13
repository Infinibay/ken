# Enlace Java entre archivos: corpus v4

IR 1.9.0, 2026-09-12. Mismas fuentes y delimitaciones del corpus v3. Presencia de la etiqueta esperada: **44 → 52 de 281 ejemplos**, sin pérdidas. Los ocho nuevos matches corresponden a colaboraciones Java que antes no se enlazaban. Esto no mide precisión ni demuestra que todos sus roles sean correctos.

| Corpus | Antes | Ahora |
|---|---:|---:|
| across-languages | 19 | 19 |
| cpp-patterns | 1 | 1 |
| go-patterns | 1 | 1 |
| guru-rust | 1 | 1 |
| java-patterns | 1 | 7 |
| pandovski | 15 | 17 |
| php-patterns | 0 | 0 |
| python-patterns | 6 | 6 |
| swift-patterns | 0 | 0 |

## Nuevas coincidencias

La [comparación](comparison.json) enumera los ocho casos: Abstract Factory, Adapter, Decorator, Proxy, Strategy y Template Method de iluwatar; Factory Method y Proxy de Pandovski. Las consultas terminaron dentro del presupuesto. Los reportes por repositorio conservan todas las coincidencias, incluidas las ajenas a la etiqueta esperada; todavía requieren revisión de intención.

## Corrección de JAVA-03

El [probe de Commons IO](java-package-probe.json) confirma SUBTYPE_OF de AutoCloseInputStream a ProxyInputStream al analizar ambos archivos. El paquete se conserva en la entidad de módulo; el resolvedor usa esa identidad, imports explícitos o un nombre calificado. No busca arbitrariamente por basename global.

Diez regresiones cubren Template Method entre archivos, paquetes diferentes, import ausente/incorrecto/ambiguo, tipos duplicados y paquete por defecto. Wildcard imports, imports estáticos, tipos anidados importados, generic substitution, classpath/JDK externo, accesibilidad y módulos Java siguen sin resolverse completamente. En particular, un wildcard no se expande para adivinar un tipo ausente.

Los falsos positivos y ambigüedades registrados en v3 siguen pendientes. La mejora de resolución puede generar candidatos adicionales: no se publica una cifra de precisión global. El objetivo de ampliar patrones web y corregir las variantes restantes sigue abierto.

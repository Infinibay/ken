# vp-cs-065: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which HTML rendering class delegates blockquote children to block parsing and paragraph children to inline parsing, and emits task checkboxes as disabled inputs whose checked state follows the token?

Pieza elegida: `src/Parser.ts:_Parser`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-065.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-cs-065.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/Parser.ts:_Parser | False | 1 | 1 | 3.208602652615869 | 9.821847915649414 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/Renderer.ts:_Renderer | True | 3 | 2 | 0.7959464163556673 | 10.003368377685547 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| src/Lexer.ts:_Lexer | False | 2 | 3 | 0.20584103353726665 | 8.665119171142578 | 3 | 0.007936507936507936 | 0.007936507936507936 | 0.015873015873015872 | 3 |
| src/Tokenizer.ts:_Tokenizer | False | 5 | 5 | -2.8801399450697134 | 8.661141395568848 | 4 | 0.007692307692307693 | 0.0078125 | 0.015504807692307693 | 4 |
| src/Instance.ts:Marked | False | 4 | 4 | -1.6548383872824746 | 7.810609817504883 | 7 | 0.0078125 | 0.007462686567164179 | 0.01527518656716418 | 5 |
| src/Hooks.ts:_Hooks | False | 6 | 6 | -3.069107225583567 | 7.938743591308594 | 6 | 0.007575757575757576 | 0.007575757575757576 | 0.015151515151515152 | 6 |
| test/types/marked.ts:ExtendedRenderer | False | 7 | 8 | -4.5592230997985554 | 8.236533164978027 | 5 | 0.007352941176470588 | 0.007692307692307693 | 0.015045248868778281 | 7 |
| src/TextRenderer.ts:_TextRenderer | False | 8 | 7 | -4.314989349102046 | 7.121245384216309 | 8 | 0.007462686567164179 | 0.007352941176470588 | 0.014815627743634766 | 8 |

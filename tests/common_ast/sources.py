SOURCES={
 'python': 'def f(x: int):\n y=x+1\n if y>0:\n  y=y-1\n while y>0:\n  y=y-1\n return y\n',
 'javascript':'function f(x) { let y=x+1; if(y>0) {y=y-1;} while(y>0) {y=y-1;} return y; }',
 'typescript':'function f(x:number) { let y=x+1; if(y>0) {y=y-1;} while(y>0) {y=y-1;} return y; }',
 'java':'class A { int f(int x) { int y=x+1; if(y>0) {y=y-1;} while(y>0) {y=y-1;} return y; } }',
 'csharp':'class A { int f(int x) { int y=x+1; if(y>0) {y=y-1;} while(y>0) {y=y-1;} return y; } }',
 'cpp':'int f(int x) { int y=x+1; if(y>0) {y=y-1;} while(y>0) {y=y-1;} return y; }',
 'go':'package a\nfunc f(x int) int { y:=x+1; if y>0 {y=y-1}; for y>0 {y=y-1}; return y }',
 'rust':'fn f(x:i32)->i32 { let mut y=x+1; if y>0 {y=y-1;} while y>0 {y=y-1;} return y; }',
 'ruby':'def f(x)\n y=x+1\n if y>0\n  y=y-1\n end\n while y>0\n  y=y-1\n end\n return y\nend',
}
EXTENSIONS={'python':'py','javascript':'js','typescript':'ts','java':'java','csharp':'cs','cpp':'cpp','go':'go','rust':'rs','ruby':'rb'}

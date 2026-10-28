"""Additional original inputs for CPython parse-only and literal boundary semantics."""
FIXTURE_COMPAT='crates/ken-retrieval/tests/fixtures/python-witnesses-compat.json.gz'
def compatibility_cases():
    rows=[]
    keys=[('uppercase-u',"U'a'","'a'"),('uppercase-u-lowercase',"U'a'","u'a'"),('u-concat-first',"u'a' 'b'","u'ab'"),('u-concat-last',"'a' u'b'","'ab'"),('u-fstring',"u'a' f'{x}'","f'a{x}'"),('u-fstring-same',"u'a' f'{x}'",'u"a" f"{x}"'),('u-empty-fstring',"u'' f'{x}'","f'{x}'"),('u-after-fstring',"f'{x}' u'a'","f'{x}a'"),('fstring-debug-paren',"f'{(x)=}'","f'(x)={x!r}'"),('fstring-debug-space',"f'{ x = }'","f' x = {x!r}'"),('fstring-debug-format',"f'{x=:}'","f'x={x:}'"),('fstring-escaped-brace',"f'{{{x}}}'","f'{{{x}}}'"),('unknown-escape',"'\\z'",r"r'\z'"),('fstring-unknown-escape',"f'\\z{x}'",r"rf'\z{x}'"),('duplicate-keywords','f(x=1,x=2)','f(x=1,x=2)'),('lambda-kinds','lambda a,/,b=1,*args,c=2,**kw: a','lambda a,/,b=0x1,*args,c=0x2,**kw: a'),('lambda-empty','lambda:1','lambda:0x1')]
    for name,left,right in keys:
        source=f'def selected():\n    old = mapping.get({left}, None)\n    mapping[{right}] = new\n    log.append((mapping, {right}, old))\n'
        rows.append(dict(id='compat-'+name,files={'sample.py':source},manual=[dict(name='selected',start=1,end=4)]))
    for name,suffix in [('return-outside','return 1'),('break-outside','break'),('continue-outside','continue'),('nonlocal-outside','nonlocal missing'),('await-outside','await action()'),('yield-outside','yield value'),('duplicate-keywords','f(x=1,x=2)'),('duplicate-parameters','def other(x,x):\n    pass'),('future-type-default','def other[T=int]():\n    pass')]:
        rows.append(dict(id='compat-admission-'+name,files={'sample.py':'def selected():\n    action()\n'+suffix+'\n'},manual=[dict(name='selected',start=1,end=2)]))
    for name,source,start,end in [('decorated','@decorate()\ndef selected():\n    action()\n',2,3),('decorated-class','@decorate()\nclass selected:\n    action()\n',2,3),('decorator-only-call','@decorate()\ndef selected():\n    pass\n',2,3),('fstring-invalid-name','def selected():\n    action()\nvalue=f"\\N{NONEXISTENT NAME}{x}"\n',1,2),('string-invalid-name','def selected():\n    action()\nvalue="\\N{NONEXISTENT NAME}"\n',1,2)]:
        rows.append(dict(id='compat-'+name,files={'sample.py':source},manual=[dict(name='selected',start=start,end=end)]))
    return rows

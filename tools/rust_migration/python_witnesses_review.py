"""Separate original inputs for the six final-review findings and boundaries."""
FIXTURE_REVIEW='crates/ken-retrieval/tests/fixtures/python-witnesses-review.json.gz'
def review_cases():
    rows=[]
    keys=[('backslash',r"f'\{x}'",r"f'\{x}'"),('backslash-equivalent',r"f'\{x}'",r"f'\\{x}'"),('backslash-format',r"f'{x:\{w}}'",r"f'{x:\{w}}'"),('backslash-different',r"f'\{x}'","f'{x}'"),('empty-u-different',"u'' f'a'","f'a'"),('empty-u-equal',"u'' f'a'","u'a' f''"),('empty-u-boundary',"u'' f'{x}a'","f'{x}a'"),('empty-u-before',"u'' f'abc{x}'","u'abc' f'{x}'"),('empty-u-after',"f'{x}' u'' f'a'","f'{x}' u'a' f''"),('empty-u-through',"u'' f'' f'a'","u'a' f''"),('newline-empty',"f'{x:\n}'","f'{x:}'"),('newline-text',"f'{x:abc\n}'","f'{x:abc}'"),('newline-triple',"f'''{x:abc\n}'''","f'{x:abc}'"),('newline-nested',"f'{x:a\n{w}}'","f'{x:a{w}}'"),('newline-comment',"f'{x:a\n#hi\n}'","f'{x:a}'"),('newline-invalid',"f'{x:a\nb}'","f'{x:ab}'")]
    for name,left,right in keys:
        body=f'old = mapping.get({left}, None)\nmapping[{right}] = new\nlog.append((mapping, {right}, old))'
        source='def selected():\n'+''.join('    '+line+'\n'for line in body.split('\n'))
        rows.append(dict(id='review-'+name,files={'sample.py':source},manual=[dict(name='selected',start=1,end=len(source.splitlines()))]))
    for name,tail in [('decimal-limit','value = '+'1'*4301),('decimal-boundary','value = '+'1'*4300),('decimal-zeros','value = '+'0'*5000),('decimal-underscores','value = '+'1_'*4300+'1'),('hex-long','value = 0x'+'f'*5000),('parens-limit','value = '+'('*201+'1'+')'*201),('parens-boundary','value = '+'('*200+'1'+')'*200),('fparens-limit','value = f"{'+'('*200+'x'+')'*200+'}"'),('fparens-boundary','value = f"{'+'('*199+'x'+')'*199+'}"'),('format-limit',"value = f'{x:{y:{z:{w}}}}'"),('format-boundary',"value = f'{x:{y:{z}}}'"),('newline-admission',"value = f'{x:\n}'")]:
        rows.append(dict(id='review-'+name,files={'sample.py':'def selected():\n    action()\n'+tail+'\n'},manual=[dict(name='selected',start=1,end=2)]))
    for name,source,end in [('bom','\ufeffdef selected():\n    action()\n',2),('tabs-invalid','def selected():\n\tif True:\n    action()\n',3),('tabs-valid','def selected():\n\tif True:\n\t\taction()\n',3),('tab-space-valid','def selected():\n\tif True:\n\t action()\n',3),('spaces-tab-invalid','def selected():\n    if True:\n\taction()\n',3)]:
        rows.append(dict(id='review-'+name,files={'sample.py':source},manual=[dict(name='selected',start=1,end=end)]))
    return rows

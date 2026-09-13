"""Internally created products, member configuration and correlated finalization."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules

LANGUAGES=['python','javascript','typescript','java','csharp','rust']


def source(language,mutation='positive',nested=False,clone=False):
    access='part.value' if nested else 'value'
    if language=='python':
        product_init='self.part=Part()' if nested else 'self.value=0'
        text=f'''class Part:
 def __init__(self): self.value=0
class Product:
 def __init__(self): {product_init}
class Builder:
 def __init__(self, supplied):
  self.product=Product()
  self.other=Product()
 def configure(self, value: int):
  self.product.{access}=value
  return self
 def finish(self):
  return self.product
'''
        assignment=f'self.product.{access}=value'
        changes={
          'other-write':(assignment,assignment.replace('self.product','self.other')),
          'other-finish':('return self.product','return self.other'),
          'borrowed-product':('self.product=Product()','self.product=supplied'),
          'constant':(assignment,f'self.product.{access}=0'),
          'overwritten':(assignment,assignment+f'\n  self.product.{access}=0'),
          'rebound':(assignment,'value=0\n  '+assignment),
          'compound':(assignment,assignment.replace('=value','+=value')),
          'branch':(assignment,'if value:\n   '+assignment),
          'nonfluent':('  return self\n','  pass\n'),
          'dead-overwrite':('  return self\n','  return self\n  '+f'self.product.{access}=0\n'),
        }
    elif language=='rust':
        product_type="part:Part<'a>" if nested else "value:&'a str"
        product_init='part:Part{value:""}' if nested else 'value:""'
        result='self.product.clone()' if clone else 'self.product'
        receiver='&self' if clone else 'self'
        text=f'''#[derive(Clone)] struct Part<'a>{{value:&'a str}}
#[derive(Clone)] struct Product<'a>{{{product_type}}}
struct Builder<'a>{{product:Product<'a>,other:Product<'a>}}
impl<'a> Builder<'a>{{
 fn new(supplied:Product<'a>)->Builder<'a>{{Builder{{product:Product{{{product_init}}},other:Product{{{product_init}}}}}}}
 fn configure(&mut self,value:&'a str)->&mut Self{{self.product.{access}=value; self}}
 fn finish({receiver})->Product<'a>{{{result}}}
}}
'''
        assignment=f'self.product.{access}=value;'
        changes={
          'other-write':(assignment,assignment.replace('self.product','self.other')),
          'other-finish':(result+'}',result.replace('self.product','self.other')+'}'),
          'borrowed-product':('product:Product{'+product_init+'}', 'product:supplied'),
          'constant':(assignment,f'self.product.{access}="";'),
          'overwritten':(assignment,assignment+f'self.product.{access}="";'),
          'rebound':('value:&\'a str)->&mut Self{'+assignment,'mut value:&\'a str)->&mut Self{value="";'+assignment),
          'compound':(assignment,assignment.replace('=value','+=value')),
          'branch':(assignment,'if flag {'+assignment+'}'),
          'nonfluent':('->&mut Self{'+assignment+' self}','{'+assignment+'}'),
          'dead-overwrite':(assignment+' self}',assignment+'return self;'+f'self.product.{access}="";'+'}'),
        }
    else:
        js=language=='javascript';ts=language=='typescript';java=language=='java'
        if js or ts:
            part='class Part { '+('value:number;' if ts else '')+'constructor(){this.value=0;} }'
            field=('part:Part;' if nested else 'value:number;') if ts else ''
            init='this.part=new Part();' if nested else 'this.value=0;'
            product='class Product {'+field+'constructor(){'+init+'}}'
            ctor='constructor(supplied)' if js else 'constructor(supplied:Product)'
            fields='' if js else 'product:Product;other:Product;'
            configure='configure(value)' if js else 'configure(value:number)'
            finish='finish()'
        else:
            part='class Part {public int value;}'
            product='class Product {'+('public Part part=new Part();' if nested else 'public int value;')+'}'
            ctor='public Builder(Product supplied)';fields='Product product;Product other;'
            configure='public Builder configure(int value)';finish='public Product finish()'
        text=f'''{part}
{product}
class Builder {{{fields}
 {ctor} {{this.product=new Product();this.other=new Product();}}
 {configure} {{this.product.{access}=value;return this;}}
 {finish} {{return this.product;}}
}}
'''
        assignment=f'this.product.{access}=value;'
        changes={
          'other-write':(assignment,assignment.replace('this.product','this.other')),
          'other-finish':('return this.product','return this.other'),
          'borrowed-product':('this.product=new Product()','this.product=supplied'),
          'constant':(assignment,f'this.product.{access}=0;'),
          'overwritten':(assignment,assignment+f'this.product.{access}=0;'),
          'rebound':(assignment,'value=0;'+assignment),
          'compound':(assignment,assignment.replace('=value','+=value')),
          'branch':(assignment,'if(flag){'+assignment+'}'),
          'nonfluent':('return this;',''),
          'dead-overwrite':('return this;','return this;'+f'this.product.{access}=0;'),
        }
    if mutation in changes:
        old,new=changes[mutation];assert old in text,(language,mutation,old);text=text.replace(old,new)
        if mutation=='nonfluent' and language in {'java','csharp'}:text=text.replace('public Builder configure','public void configure')
    if mutation=='renamed':
        for a,b in [('Builder','Assembler'),('Product','Result'),('configure','apply'),('finish','release'),('product','pending'),('value','data')]:
            text=re.sub(r'\b'+a+r'\b',b,text)
    return text


def detect(text,language):
    graph=link_project([lower_source(text,language,'stored-example')]);assert not graph.diagnostics
    rules=builtin_rules();out=execute_rules(graph,[named_rule('builder#stored-product',rules)],registry=rules)
    assert out['complete'],out
    return graph,out


MUTATIONS=['positive','renamed','other-write','other-finish','borrowed-product','constant','overwritten','rebound','compound','branch','nonfluent','dead-overwrite']
@pytest.mark.parametrize('language,clone',[(lang,False) for lang in LANGUAGES]+[('rust',True)])
@pytest.mark.parametrize('nested',[False,True])
@pytest.mark.parametrize('mutation',MUTATIONS)
def test_stored_product_configuration_and_finalization(language,clone,nested,mutation):
    _,out=detect(source(language,mutation,nested,clone),language)
    assert bool(out['matches'])==(mutation in {'positive','renamed','nonfluent','dead-overwrite'}),out


@pytest.mark.parametrize('modification',['no-derive','explicit-clone','other-clone'])
def test_clone_finish_requires_the_same_derived_copy_usage(modification):
    text=source('rust',clone=True)
    if modification=='no-derive':text=text.replace('#[derive(Clone)] struct Product','struct Product')
    elif modification=='explicit-clone':text+="impl<'a> Product<'a>{fn clone(&self)->Product<'a>{Product{value:\"\"}}}"
    else:text=text.replace('self.product.clone()','self.other.clone()')
    _,out=detect(text,'rust');assert not out['matches']

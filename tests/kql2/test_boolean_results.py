import pytest
from ken.kql2.boolean_results import BooleanResults
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import FactIndex


def accreditation(source,language):
 ir=link_project([lower_source(source,language,'sample')])
 helper=BooleanResults(FactIndex(ir))
 return ir,helper,{e.name:helper.is_boolean(e.id) for e in ir.entities.values() if e.kind=='CALL'}

@pytest.mark.parametrize('result,expected',[
 ('bool',True),('int',False),('(bool,error)',False),('interface{}',False),('*bool',False),
])
def test_go_callback_result_uses_function_type_ast(result,expected):
 _,_,calls=accreditation('package p;func each(cb func(int) '+result+'){cb(1)}','go')
 assert calls['cb'] is expected

@pytest.mark.parametrize('result,expected',[
 ('boolean',True),('Boolean',False),('boolean|undefined',False),('Promise<boolean>',False),
 ('any',False),('unknown',False),('number',False),
])
def test_typescript_callback_result_is_primitive_boolean(result,expected):
 _,_,calls=accreditation('function each(cb:(x:number)=>'+result+'){cb(1)}','typescript')
 assert calls['cb'] is expected

@pytest.mark.parametrize('source,language',[
 ('package p;func each(cb func(int) bool,other func(int) bool){cb=other;cb(1)}','go'),
 ('function each(cb:(x:number)=>boolean,other:(x:number)=>boolean){cb=other;cb(1)}','typescript'),
 ('package p;type bool int;func each(cb func(int) bool){cb(1)}','go'),
])
def test_rebound_callback_or_shadowed_primitive_is_not_accredited(source,language):
 _,_,calls=accreditation(source,language)
 assert not calls['cb']


def test_parenthesized_typescript_callback_type_is_transparent():
 _,_,calls=accreditation('function each(cb:((x:number)=>boolean)){cb(1)}','typescript')
 assert calls['cb']

@pytest.mark.parametrize('result,expected',[('boolean',True),('Boolean',False),('Object',False),('int',False)])
def test_resolved_java_return_type_excludes_boxed_boolean(result,expected):
 _,_,calls=accreditation('class A {'+result+' check(){return true;} void run(){check();}}','java')
 assert calls['check'] is expected

@pytest.mark.parametrize('prefix,result,expected',[('', 'boolean',True),('async ','Promise<boolean>',False),('','Boolean',False)])
def test_resolved_typescript_return_type(prefix,result,expected):
 _,_,calls=accreditation(prefix+'function check():'+result+'{return true;} function run(){check();}','typescript')
 assert calls['check'] is expected


def test_missing_and_ambiguous_targets_are_not_boolean_proofs():
 ir,helper,calls=accreditation('function run(){missing();}','typescript')
 assert calls['missing'] is False
 assert helper.is_boolean('unknown') is False


def test_call_operation_identity_and_memo_preserve_cancellation_checks():
 ir,helper,calls=accreditation('function check():boolean{return true;} function run(){check();}','typescript')
 call=next(e for e in ir.entities.values() if e.kind=='CALL')
 operation=next(f.object for f in ir.facts if f.relation=='SYNTAX_NODE' and f.subject==call.id)
 assert helper.is_boolean(operation) and helper.is_boolean(call.id)
 def cancelled():raise RuntimeError('cancelled')
 helper.check=cancelled
 with pytest.raises(RuntimeError,match='cancelled'):helper.is_boolean(call.id)


@pytest.mark.parametrize('language,source',[
 ('csharp','class A {bool check(){return true;} void run(){check();}}'),
 ('cpp','bool check(){return true;} void run(){check();}'),
 ('go','package p;func check() bool{return true};func run(){check()}'),
 ('rust','fn check()->bool{true} fn run(){check();}'),
 ('python','def check() -> bool:\n return True\ndef run():\n check()\n'),
])
def test_resolved_primitive_annotations_across_languages(language,source):
 _,_,calls=accreditation(source,language)
 assert calls['check']


@pytest.mark.parametrize('relation',['MAY_TARGET','TARGET','DECLARED_TARGET'])
def test_conflicting_target_evidence_cannot_be_ignored(relation):
 ir,_,_=accreditation('function check():boolean{return true;} function run(){check();}','typescript')
 call=next(e.id for e in ir.entities.values() if e.kind=='CALL')
 ir.add(call,relation,'unresolved-other')
 assert not BooleanResults(FactIndex(ir)).is_boolean(call)


def test_missing_callback_write_inventory_is_not_an_annotation_proof():
 ir,_,_=accreditation('function each(cb:(x:number)=>boolean){cb(1)}','typescript')
 call=next(e.id for e in ir.entities.values() if e.kind=='CALL')
 ir.facts=[f for f in ir.facts if f.relation!='STORAGE_WRITE_STATUS']
 assert not BooleanResults(FactIndex(ir)).is_boolean(call)


def test_untyped_javascript_truthiness_is_not_boolean_type():
 _,_,calls=accreditation('function each(cb){if(!cb(1)){return;}}','javascript')
 assert not calls['cb']

"""All 31 APIs through real approval plans; fixtures are synthetic only."""
import ast,copy,json,math,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument
from line_document import JwwDocument,Line,Text
from writer.preserved import _document_bytes
from safe_edit import write_plan,execute_plan,file_sha256
from edit_result import write_edit_plan,execute_plan_result,preview_plan_result,EditExecutionError
from _edit_result_core import NAMES,METHODS,capture,apply_method,Rejected,Failed

CASES={
 'delete_entity':([0],{},(0,0,1)), 'delete_entities':([0,4],{},(0,0,2)),
 'move_entity':([0],dict(delta=[2,3]),(0,1,0)), 'move_entities':([0,4],dict(delta=[2,3]),(0,2,0)),
 'transform_entities':([0],dict(translation=[2,3],rotation=.2,copy_entities=True),(1,0,0)),
 'copy_entities':([0],dict(delta=[2,3]),(1,0,0)),
 'align_two_points':([0],dict(source_points=[[0,0],[10,0]],target_points=[[2,3],[12,3]],distance_tolerance=0,angle_tolerance=0),(0,1,0)),
 'rotate_entities':([0],dict(angle=.2),(0,1,0)), 'reflect_entities':([0],{},(0,1,0)),
 'scale_entities':([0],dict(scale_x=2),(0,1,0)),
 'set_entity_attributes':([0],dict(color=4),(0,1,0)), 'set_text':([1],dict(content='CHANGED'),(0,1,0)),
 'recalculate_text_endpoint':([1],{},(0,0,0)), 'set_group_scale':([],dict(layer_group=1,scale=100),(0,0,0)),
 'add_line':([],dict(start=[1,2],end=[3,4]),(1,0,0)), 'add_text':([],dict(start=[1,2],content='NEW'),(1,0,0)),
 'add_circle':([],dict(center=[1,2],radius=3),(1,0,0)), 'add_point':([],dict(position=[1,2]),(1,0,0)),
 'add_solid':([],dict(points=[[0,0],[2,0],[2,2],[0,2]]),(1,0,0)), 'add_circle_solid':([],dict(center=[1,2],radius=3),(1,0,0)),
 'set_group_state':([],dict(layer_group=1,state=0),(0,0,0)), 'set_layer_state':([],dict(layer_group=1,layer=2,state=1),(0,0,0)),
 'set_layer_name':([],dict(layer_group=1,layer=2,name='TEST'),(0,0,0)), 'set_group_name':([],dict(layer_group=1,name='TEST'),(0,0,0)),
 'add_block_definition':([],dict(name='NEW',entities=[dict(op='add_line',kwargs=dict(start=[0,0],end=[2,0]))]),(0,0,0)),
 'add_arc':([],dict(center=[1,2],radius=3,start_angle=0,arc_angle=1),(1,0,0)),
 'set_dimension_text':([2],dict(content='12'),(0,1,0)), 'place_block':([],dict(def_number=0,position=[1,2]),(1,0,0)),
 'replace_entities_with_block':([0],dict(name='REPLACE'),(0,1,0)), 'set_block_layer_priority':([3],dict(enabled=True),(0,1,0)),
 'import_group':([],dict(source_group=1,target_group=2),(1,0,0)),
}

class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name)
        self.source=self.p/'input.jww';self.output=self.p/'output.jww';self.plan=self.p/'plan.json'
        d=JwwDocument();d.set_group_scale(0,50);d.set_group_scale(1,25)
        d.add_line((2,4),(6,4));d.add_text((1,8),content='KEEP')
        d.add_dimension(Line((0,10),(10,10)),Text((2,11),(5,11),'10'))
        definition=d.add_block_definition('EXISTING',[Line((0,0),(2,0))]);d.add_block(definition.number,(20,20))
        d.add_line((50,50),(60,50),layer_group=1);d.save(self.source)
        self.raw=self.source.read_bytes();self.doc=CadDocument.open(self.source)
        self.import_source=self.p/'import.jww';self.import_source.write_bytes(self.raw)
    def plan_for(self,actions,targets=()):return write_edit_plan(self.doc,list(targets),actions,self.output,self.plan)
    def run_plan(self,r,**kw):return execute_plan_result(self.plan,approved_sha256=r['plan']['sha256'],**kw)

class MethodTests(Base):pass
def method_test(name):
    def run(self):
        chosen,kw,expected=copy.deepcopy(CASES[name])
        if name=='import_group':kw['path']=str(self.import_source)
        if name=='set_block_layer_priority':kw['enabled']=not self.doc.get_block_layer_priority(3)
        action=dict(op=name,kwargs=kw)
        if chosen:action['indices']=chosen
        before=capture(self.doc);planned=self.plan_for([action],chosen)
        self.assertEqual(planned['status'],'planned',planned.get('rejections'))
        self.assertFalse(self.output.exists());self.assertEqual(capture(self.doc),before)
        done=self.run_plan(planned);self.assertIn(done['status'],('applied','unchanged'))
        self.assertEqual(tuple(done['counts'][k]for k in ('added','modified','deleted')),expected)
        self.assertEqual(done['phase'],'verified');self.assertTrue(done['validation']['all_fields_match'])
        self.assertEqual(self.source.read_bytes(),self.raw)
        record=self.output.with_suffix('.edit-result.json');self.assertEqual(json.loads(record.read_text(encoding='utf-8')),done)
        direct=CadDocument.open(self.source);direct_kw=copy.deepcopy(kw)
        if name=='add_block_definition':direct_kw['entities']=[Line((0,0),(2,0))]
        args=([chosen[0]]if name in ('delete_entity','move_entity','recalculate_text_endpoint','set_entity_attributes','set_text','set_dimension_text','set_block_layer_priority')else [chosen])if chosen else []
        METHODS[name](direct,*args,**direct_kw)
        self.assertEqual(self.output.read_bytes(),_document_bytes(direct))
        self.assertEqual(done['operations'][0]['operation'],name)
    return run
for _name in NAMES:setattr(MethodTests,'test_'+_name,method_test(_name))

class ContractTests(Base):
    def test_ast_coverage_exactly_31_and_legacy_paths_excluded(self):
        tree=ast.parse((R/'src/model/document.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='CadDocument')
        found={n.name for n in cls.body if isinstance(n,ast.FunctionDef)and not n.name.startswith('_')and any(isinstance(a,ast.Attribute)and a.attr=='_require_editable'for a in ast.walk(n))}
        self.assertEqual(found,set(NAMES));self.assertEqual(len(CASES),31)
        r=write_edit_plan(JwwDocument(),[],[],self.output,self.plan)
        self.assertEqual(r['status'],'rejected');self.assertEqual(r['rejections'][0]['code'],'PLAN_OPERATION_UNSUPPORTED')
    def test_noop_counts_and_resource_changes_not_root_changes(self):
        r=self.plan_for([dict(op='move_entities',indices=[0],kwargs=dict(delta=[0,0]))],[0])
        done=self.run_plan(r);self.assertEqual(done['status'],'unchanged');self.assertEqual(done['counts']['unchanged'],5)
    def test_group_warning_and_definition_resource_counts(self):
        r=self.plan_for([dict(op='set_group_scale',kwargs=dict(layer_group=1,scale=100)),dict(op='add_block_definition',kwargs=CASES['add_block_definition'][1])])
        d=self.run_plan(r);self.assertEqual(d['resource_counts'],dict(groups=1,layers=0,definitions=1))
        self.assertEqual(d['counts']['modified'],0);self.assertEqual(d['warning_count'],1)
    def test_aliases_survive_deletion_and_new_source_none_entities_do_not_collapse(self):
        actions=[dict(op='add_line',kwargs=dict(start=[0,0],end=[1,0]),**{'as':'new'}),dict(op='copy_entities',indices=['new'],kwargs=dict(delta=[2,0]),**{'as':'copy'}),dict(op='move_entities',indices=['new'],kwargs=dict(delta=[1,0])),dict(op='delete_entities',indices=[0]),dict(op='set_entity_attributes',indices=['new','copy'],kwargs=dict(color=4))]
        d=self.run_plan(self.plan_for(actions,[0]));self.assertEqual((d['counts']['added'],d['counts']['deleted'],d['counts']['modified']),(2,1,0))
        self.assertEqual(d['operation_totals']['modified'],3)
        out=CadDocument.open(self.output);self.assertTrue(all(e.attributes['pen_color']==4 for e in out.entities[-2:]))
    def test_replacement_multiple_roots_retains_first_lineage(self):
        r=self.plan_for([dict(op='replace_entities_with_block',indices=[0,4],kwargs=dict(name='MULTI'))],[0,4])
        d=self.run_plan(r);self.assertEqual((d['counts']['added'],d['counts']['modified'],d['counts']['deleted']),(0,1,1))
        self.assertEqual(d['resource_counts']['definitions'],1)
    def test_missing_approval_and_changed_input_or_plan_are_rejected(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0])
        d=execute_plan_result(self.plan,approved_sha256='');self.assertEqual(d['status'],'rejected');self.assertFalse(self.output.exists())
        self.plan.write_text(self.plan.read_text()+' ',encoding='utf-8');self.assertEqual(self.run_plan(r)['status'],'rejected')
    def test_legacy_execute_and_new_common_schema_do_not_mix(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0])
        with self.assertRaises(ValueError):execute_plan(self.plan,approved_sha256=r['plan']['sha256'])
        self.assertFalse(self.output.exists())
    def test_legacy_plans_still_have_common_result_option(self):
        r=write_plan(self.doc,[0],[dict(op='move_entities',indices=[0],kwargs=dict(delta=[1,0]))],self.output,self.plan)
        self.assertEqual(execute_plan_result(self.plan,approved_sha256=r['sha256'])['counts']['modified'],1)
    def test_unsupported_operation_and_unknown_schema_refused(self):
        r=self.plan_for([dict(op='__setattr__',kwargs={})]);self.assertEqual(r['rejections'][0]['code'],'PLAN_OPERATION_UNSUPPORTED')
        self.assertFalse(self.plan.exists())
    def test_known_refusal_and_mutated_caller_arguments_remain_atomic(self):
        original=_document_bytes(self.doc);indices=[0];delta=[1,2]
        def bad(cad,indices,delta,*,units='paper'):
            cad.add_line((0,0),(2,0));indices.clear();delta[0]=999;raise ValueError('known refusal')
        with patch.dict(METHODS,move_entities=bad):
            with self.assertRaises(Rejected)as ctx:apply_method(self.doc,'move_entities',indices,delta)
        self.assertEqual(indices,[0]);self.assertEqual(delta,[1,2]);self.assertEqual(_document_bytes(self.doc),original)
        self.assertEqual(ctx.exception.record['before_model_sha256'],ctx.exception.record['after_model_sha256'])
        self.assertEqual(ctx.exception.record['counts']['rejected'],1)
    def test_unexpected_failure_raises_result_and_does_not_commit(self):
        original=_document_bytes(self.doc)
        def bad(cad,indices,delta,*,units='paper'):cad.entities=();raise RuntimeError('injected bug')
        with patch.dict(METHODS,move_entities=bad):
            with self.assertRaises(Failed)as ctx:apply_method(self.doc,'move_entities',[0],[1,0])
        self.assertEqual(ctx.exception.record['status'],'failed');self.assertEqual(_document_bytes(self.doc),original)
    def test_partial_plan_rejection_discards_previous_memory_operations(self):
        r=self.plan_for([dict(op='move_entities',indices=[0],kwargs=dict(delta=[1,0])),dict(op='set_text',indices=[1],kwargs=dict(content='NEW'))],[0,1])
        def refuse(cad,index,content,*,recalculate_end=False):raise ValueError('refuse at execution')
        with patch.dict(METHODS,set_text=refuse):d=self.run_plan(r)
        self.assertEqual(d['status'],'rejected');self.assertEqual(d['counts']['modified'],0);self.assertTrue(d['prior_operations_discarded'])
        self.assertTrue(d['operations'][0]['discarded']);self.assertFalse(self.output.exists());self.assertEqual(self.source.read_bytes(),self.raw)
    def test_known_rejections_distinguish_additions_and_resources(self):
        for name,kw in (('add_line',dict(start=[0,0],end=[1,0],color=999)),('set_layer_name',dict(layer_group=99,layer=0,name='X'))):
            with self.assertRaises(Rejected)as ctx:apply_method(self.doc,name,**kw)
            r=ctx.exception.record;self.assertEqual(r['counts']['rejected'],0)
            self.assertEqual(r['rejected_addition_count'],1 if name=='add_line'else 0)
            if name=='set_layer_name':self.assertEqual(len(r['resource_rejections']),1)
    def test_summary_count_and_limits_do_not_change_counts_or_invent_cursor(self):
        r=self.plan_for([dict(op='move_entities',indices=[0,4],kwargs=dict(delta=[1,0]))],[0,4])
        for mode in ('count','summary'):
            p=preview_plan_result(self.plan,plan_sha256=r['plan']['sha256'],mode=mode)
            self.assertEqual(p['projected_counts']['modified'],2);self.assertEqual(p['changes'],[]);self.assertTrue(p['detail_page']['truncated'])
        p=preview_plan_result(self.plan,plan_sha256=r['plan']['sha256'],limit=1)
        self.assertEqual(p['detail_page']['returned'],1);self.assertFalse(p['detail_page']['continuation_supported']);self.assertNotIn('next_cursor',p['detail_page'])
    def test_save_failure_and_retained_unverified_file_raise(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0])
        def bad(cad,before,source_sha,output,**kw):cad.save(output);raise OSError('saved-output verification failure')
        with patch('safe_edit.save_checked',side_effect=bad):
            with self.assertRaises(EditExecutionError)as ctx:self.run_plan(r)
        d=ctx.exception.result;self.assertEqual(d['status'],'failed');self.assertEqual(d['phase'],'saved');self.assertTrue(d['files_created']);self.assertIsNone(d['counts']['modified'])
        self.assertFalse(d['validation']['all_fields_match']);self.assertEqual(self.source.read_bytes(),self.raw)
    def test_duplicate_common_record_stops_before_drawing_save(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0]);record=self.output.with_suffix('.edit-result.json');record.write_bytes(b'KEEP')
        d=self.run_plan(r);self.assertEqual(d['status'],'rejected');self.assertFalse(self.output.exists());self.assertEqual(record.read_bytes(),b'KEEP')
    def test_all_31_invalid_arguments_reject_without_mutation(self):
        original=_document_bytes(self.doc)
        for name in NAMES:
            chosen,kw,_=copy.deepcopy(CASES[name]);kw['unknown_argument']=True
            if name=='import_group':kw['path']=str(self.import_source)
            args=([chosen[0]]if name in ('delete_entity','move_entity','recalculate_text_endpoint','set_entity_attributes','set_text','set_dimension_text','set_block_layer_priority')else [chosen])if chosen else []
            with self.subTest(name=name):
                with self.assertRaises(Rejected):apply_method(self.doc,name,*args,**kw)
                self.assertEqual(_document_bytes(self.doc),original)
    def test_alignment_tolerance_failure_reports_rejected_existing_targets(self):
        with self.assertRaises(Rejected)as ctx:apply_method(self.doc,'align_two_points',[0],[[0,0],[10,0]],[[0,0],[11,0]],distance_tolerance=0,angle_tolerance=0)
        self.assertEqual(ctx.exception.record['counts']['rejected'],1);self.assertEqual(self.source.read_bytes(),self.raw)
    def test_copy_variants_count_refused_new_roots_separately(self):
        cases=[('transform_entities',dict(copy_entities=True)),('rotate_entities',dict(angle=.2,copy=True)),('scale_entities',dict(scale_x=2,copy=True)),('reflect_entities',dict(copy=True))]
        for name,kwargs in cases:
            with self.subTest(name=name):
                with self.assertRaises(Rejected)as ctx:apply_method(self.doc,name,[0],**dict(kwargs,unobserved_option=True))
                self.assertEqual(ctx.exception.record['counts']['rejected'],1);self.assertEqual(ctx.exception.record['rejected_addition_count'],1)
    def test_unexpected_population_is_failure_before_commit(self):
        original=_document_bytes(self.doc)
        def bad(cad,indices,delta,*,units='paper'):cad.add_line((0,0),(1,0));return None
        with patch.dict(METHODS,move_entities=bad):
            with self.assertRaises(Failed):apply_method(self.doc,'move_entities',[0],[1,0])
        self.assertEqual(_document_bytes(self.doc),original)
    def test_oversized_single_detail_is_explicitly_omitted(self):
        from _edit_result_core import result,present
        r=result('test','applied','memory');r['counts']['modified']=1;r['changes']=[dict(payload='X'*1048577)]
        p=present(r);self.assertEqual(p['counts']['modified'],1);self.assertEqual(p['changes'],[]);self.assertEqual(p['detail_page']['total'],1);self.assertTrue(p['detail_page']['truncated'])
    def test_result_record_write_failure_retains_verified_counts(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0]);original=Path.open
        def guarded(path,*args,**kwargs):
            if str(path).endswith('output.edit-result.json')and args and args[0]=='x':raise OSError('record write failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guarded):
            with self.assertRaises(EditExecutionError)as ctx:self.run_plan(r)
        d=ctx.exception.result;self.assertEqual(d['status'],'failed');self.assertEqual(d['phase'],'verified');self.assertEqual(d['counts']['modified'],1);self.assertTrue(d['validation']['all_fields_match']);self.assertFalse(d['record_written']);self.assertTrue(d['transaction_committed']);self.assertNotIn('discarded',d['operations'][0])
    def test_new_contract_cannot_be_relabelled_as_legacy_schema(self):
        r=self.plan_for([dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],[0])
        plan=json.loads(self.plan.read_text());plan['schema_version']=2
        for k in ('result_contract_version','selection','selection_sha256'):del plan[k]
        self.plan.write_text(json.dumps(plan),encoding='utf-8');d=execute_plan_result(self.plan,approved_sha256=file_sha256(self.plan))
        self.assertEqual(d['status'],'rejected');self.assertFalse(self.output.exists())
    def test_dependency_collision_with_common_report_is_refused(self):
        dependency=self.output.with_suffix('.edit-result.json');dependency.write_text('PRIVATE',encoding='utf-8')
        r=write_edit_plan(self.doc,[0],[dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],self.output,self.plan,dependencies=[dependency])
        self.assertEqual(r['status'],'rejected');self.assertIn('overlaps',r['error_summary']['message']);self.assertFalse(self.output.exists());self.assertFalse(self.plan.exists())
    def test_result_record_plan_collision_refused_before_publication(self):
        collision=self.output.with_suffix('.edit-result.json')
        r=write_edit_plan(self.doc,[0],[dict(op='move_entity',indices=[0],kwargs=dict(delta=[1,0]))],self.output,collision)
        self.assertEqual(r['status'],'rejected');self.assertFalse(collision.exists());self.assertFalse(self.output.exists())
    def test_existing_workflow_schema4_keeps_full_save_audit(self):
        from replacement_workflow import plan_building_replacement
        paths=[]
        for name in ('a','b'):
            d=CadDocument.open(R/'src/resources/empty_template.jww')
            for g in (1,2,3):d.set_group_scale(g,100)
            d.add_line((0,0),(10,1 if name=='b'else 0),layer_group=1);d.add_line((1,1),(2,2),layer_group=2)
            for p in ((0,0),(10,0)):d.add_point(p,layer_group=3,is_temporary=True)
            path=self.p/(name+'.jww');d.save(path);paths.append(path)
        r=plan_building_replacement(*paths,self.output,self.plan,work_dir=self.p,building_group=1,archive_group=4,source_reference_indices=[2,3],target_reference_indices=[2,3],distance_tolerance=0,angle_tolerance=0,settings_policy='destination')
        d=execute_plan_result(self.plan,approved_sha256=r['sha256']);self.assertEqual(d['phase'],'verified')
        legacy=json.loads(self.output.with_suffix('.changes.json').read_text());self.assertTrue(legacy['workflow_audit']['passed'])

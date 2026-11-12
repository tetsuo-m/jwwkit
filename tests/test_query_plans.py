"""Two-stage approvals using search conditions, synthetic source only."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from cad_model import CadDocument
from safe_edit import write_plan,verify_plan,execute_plan,file_sha256,_hash


class QueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.source=self.folder/'source.jww'
        self.plan=self.folder/'review.json';self.output=self.folder/'edited.jww'
        doc=CadDocument.open(ROOT/'src/resources/empty_template.jww')
        doc.add_line((0,0),(20,0));doc.add_text((0,0),content='AW-01');doc.add_line((0,0),(5,0),layer=1)
        doc.save(self.source);self.original=self.source.read_bytes()
        self.query={'all':[{'field':'entity_type','in':['LINE']},{'field':'layer','in':[0]}]}

    def make(self,**kw):
        actions=kw.pop('actions',[dict(op='move_entities',indices=[0],kwargs=dict(delta=[1,2],units='paper'))])
        return write_plan(CadDocument.open(self.source),kw.pop('indices',None),actions,self.output,self.plan,
                          selection=kw.pop('selection',self.query),**kw)

    def rewrite(self,plan):
        self.plan.write_text(json.dumps(plan,ensure_ascii=True),encoding='utf-8')
        return file_sha256(self.plan)

    def test_schema3_records_input_effective_bindings_targets_and_hash(self):
        receipt=self.make();plan=receipt['plan'];selection=plan['selection']
        self.assertEqual(plan['schema_version'],3);self.assertEqual(selection['input_query'],self.query)
        self.assertEqual(selection['scope'],'drawing');self.assertEqual([h['index'] for h in selection['hits']],[0])
        self.assertEqual(selection['targets_sha256'],plan['targets_sha256'])
        self.assertEqual(plan['selection_sha256'],_hash(selection))
        self.assertNotIn('elapsed_seconds',selection)
        self.assertFalse(self.output.exists());self.assertEqual(self.source.read_bytes(),self.original)
        cad,checked=verify_plan(self.plan,approved_sha256=receipt['sha256']);self.assertEqual(checked,plan)

    def test_execution_moves_only_frozen_targets_and_roundtrips(self):
        receipt=self.make();report=execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.assertEqual(report['modified_count'],1);self.assertEqual(report['added_count'],0)
        self.assertEqual(report['approved_plan_sha256'],receipt['sha256'])
        a,b=CadDocument.open(self.source),CadDocument.open(self.output)
        self.assertEqual(b.line_points(0),((1.,2.),(21.,2.)))
        self.assertEqual(a.entities[1:],b.entities[1:]);self.assertEqual(self.source.read_bytes(),self.original)

    def test_criteria_must_equal_explicit_indices_and_generator_is_not_lost(self):
        with self.assertRaisesRegex(ValueError,'do not equal'):self.make(indices=[2])
        self.assertFalse(self.plan.exists())
        receipt=self.make(indices=(i for i in [0]));self.assertEqual(len(receipt['plan']['targets']),1)

    def test_changed_criteria_cannot_pass_even_with_new_hash_and_stale_hits(self):
        receipt=self.make();plan=receipt['plan'];plan['selection']['input_query']={'field':'layer','in':[1]}
        plan['selection_sha256']=_hash(plan['selection'])
        with self.assertRaisesRegex(ValueError,'Search selection'):
            execute_plan(self.plan,approved_sha256=self.rewrite(plan))
        self.assertFalse(self.output.exists())

    def test_changed_rule_version_is_refused_before_output(self):
        receipt=self.make()
        from model.query_text import rules
        altered=dict(rules(),width_rule='different')
        with patch('model.query_text.rules',return_value=altered):
            with self.assertRaisesRegex(ValueError,'Search selection'):
                execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.assertFalse(self.output.exists())

    def test_no_automatic_reselection_after_each_edit(self):
        q={'field':'entity_type','in':['LINE']}
        receipt=self.make(selection=q,actions=[dict(op='delete_entities',indices=[0]),
            dict(op='move_entities',indices=[2],kwargs=dict(delta=[7,0],units='paper'))])
        report=execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.assertEqual(report['deleted_count'],1);self.assertEqual(report['modified_count'],1)
        self.assertEqual(CadDocument.open(self.output).line_points(1),((7.,0.),(12.,0.)))

    def test_regex_selection_can_be_verified_in_a_separate_process(self):
        import subprocess
        receipt=self.make(selection={'field':'text','match':'regex','value':'^AW-'},
            actions=[dict(op='set_text',indices=[1],kwargs=dict(content='AW-02'))])
        code='import sys;sys.path.insert(0,sys.argv[1]);from safe_edit import execute_plan;execute_plan(sys.argv[2],approved_sha256=sys.argv[3])'
        process=subprocess.run([sys.executable,'-c',code,str(ROOT/'src'),str(self.plan),receipt['sha256']],capture_output=True,text=True,timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(CadDocument.open(self.output).entities[1].geometry['content'],'AW-02')

    def test_regex_timeout_and_incomplete_selection_create_no_plan_or_output(self):
        with self.assertRaises(TimeoutError):self.make(selection={'field':'text','match':'regex','value':'AW-'},selection_limits={'regex_seconds':1e-12})
        self.assertFalse(self.plan.exists());self.assertFalse(self.output.exists())
        doc=CadDocument.open(self.source);doc.add_circle((0,0),3,flatness=.5)
        other=self.folder/'ellipse.jww';doc.save(other)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            write_plan(CadDocument.open(other),None,[],self.output,self.plan,selection={'field':'length','min':1,'units':'paper'})
        self.assertFalse(self.plan.exists());self.assertFalse(self.output.exists())

    def test_timeout_during_reverification_stops_before_edit(self):
        receipt=self.make()
        with patch('model.query.search',side_effect=TimeoutError('controlled search timeout')):
            with self.assertRaises(TimeoutError):execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.assertFalse(self.output.exists());self.assertEqual(self.source.read_bytes(),self.original)

    def test_changed_source_approved_file_and_selection_hash_stop(self):
        receipt=self.make();raw=self.plan.read_bytes()
        self.plan.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'plan file changed'):execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.plan.write_bytes(raw);self.source.write_bytes(self.original+b'x')
        with self.assertRaisesRegex(ValueError,'Source changed'):execute_plan(self.plan,approved_sha256=receipt['sha256'])
        self.source.write_bytes(self.original);plan=receipt['plan'];plan['selection_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'selection record changed'):
            execute_plan(self.plan,approved_sha256=self.rewrite(plan))
        self.assertFalse(self.output.exists())

    def test_definition_result_is_not_an_edit_selection(self):
        result=CadDocument.open(self.source).search_entities({'field':'entity_type','in':['LINE']},scope='definitions')
        with self.assertRaises(ValueError):self.make(selection=result)
        self.assertFalse(self.plan.exists())

    def test_schema2_and_schema1_remain_usable(self):
        receipt=write_plan(CadDocument.open(self.source),[0],[dict(op='move_entities',indices=[0],kwargs=dict(delta=[1,0]))],self.output,self.plan)
        self.assertEqual(receipt['plan']['schema_version'],2)
        verify_plan(self.plan,approved_sha256=receipt['sha256'])
        plan=receipt['plan'];plan['schema_version']=1
        del plan['resource_targets'];del plan['resource_targets_sha256']
        execute_plan(self.plan,approved_sha256=self.rewrite(plan))
        self.assertTrue(self.output.exists())


if __name__=='__main__':unittest.main()

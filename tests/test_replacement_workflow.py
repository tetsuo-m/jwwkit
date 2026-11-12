"""Synthetic drawings only; approvals below belong exclusively to these fixtures."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument
from line_document import Line
from safe_edit import execute_plan,verify_plan,file_sha256,_hash
from replacement_workflow import plan_building_replacement,replacement_reference_points

class ReplacementWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.config=self.folder/'jww_workflow.toml';self.source=self.folder/'source.jww';self.incoming=self.folder/'incoming.jww'
        for path in (self.source,self.incoming):
            d=CadDocument.open(R/'src/resources/empty_template.jww')
            for group in (1,2,3):d.set_group_scale(group,100)
            d.set_group_scale(8,50)
            d.add_line((0,0),(1000,100 if path==self.incoming else 0),layer_group=1,units='real')
            d.add_line((50,50),(60,60),layer_group=2,units='real')
            for p in ((0,0),(1000,0)):d.add_point(p,layer_group=3,layer=0,units='real',is_temporary=True)
            d.save(path)
        self.input_hashes={p:file_sha256(p)for p in (self.source,self.incoming)}
    def plan(self,stem='case',**kw):
        args=dict(work_dir=self.folder,building_group=1,settings_policy='destination',
          source_reference_indices=[r['index']for r in replacement_reference_points(self.incoming)],
          target_reference_indices=[r['index']for r in replacement_reference_points(self.source)],distance_tolerance=0,angle_tolerance=0)
        args.update(kw)
        return plan_building_replacement(self.source,self.incoming,self.folder/(stem+'.jww'),self.folder/(stem+'.plan.json'),**args)
    def approve_synthetic(self,r):return execute_plan(r['path'],approved_sha256=r['sha256'])
    def test_default_archive_explicit_argument_and_reload_audit(self):
        r=self.plan(archive_group=8);self.assertEqual(r['plan']['schema_version'],4)
        self.assertFalse((self.folder/'case.jww').exists());self.assertEqual(r['plan']['workflow']['context']['archive_group'],8)
        report=self.approve_synthetic(r);self.assertTrue(report['workflow_audit']['passed'])
        self.assertEqual(report['deleted_count'],0);self.assertEqual(report['added_count'],1)
        out=CadDocument.open(self.folder/'case.jww');self.assertEqual(out.get_group_scale(8),100)
        self.assertEqual(out.get_group_state(8)['raw_value'],0);self.assertEqual(len(out.find_entities(layer_group=8)),1)
        self.assertEqual({p:file_sha256(p)for p in self.input_hashes},self.input_hashes)
    def test_configured_archive_group_and_first_empty(self):
        self.config.write_text('schema_version=1\n[building_replacement]\narchive_group="first_empty"',encoding='utf-8')
        r=self.plan();self.assertEqual(r['plan']['workflow']['context']['archive_group'],4)
        self.assertEqual(r['plan']['workflow']['settings']['effective']['archive_group'],'first_empty')
        self.approve_synthetic(r);self.assertEqual(len(CadDocument.open(self.folder/'case.jww').find_entities(layer_group=4)),1)
    def test_argument_overrides_config_and_conflicting_chat_is_refused(self):
        self.config.write_text('schema_version=1\n[building_replacement]\narchive_group=4',encoding='utf-8')
        r=self.plan(archive_group=8);self.assertEqual(r['plan']['workflow']['context']['archive_group'],8)
        with self.assertRaises(ValueError):self.plan('conflict',archive_group=8,instruction_overrides={'building_replacement':{'archive_group':9}})
        with self.assertRaises(ValueError):self.plan('invalid',archive_group=8,instruction_overrides={'building_replacement':{'archive_group':8.0}})
    def test_missing_occupied_writing_and_reference_archive_are_rejected(self):
        with self.assertRaises(ValueError):self.plan()
        for g in (0,1,2,3):
            with self.subTest(g=g),self.assertRaises(ValueError):self.plan(str(g),archive_group=g)
        self.assertFalse((self.folder/'case.jww').exists())
    def test_quick_deletes_only_old_building_and_records_frozen_settings(self):
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8');r=self.plan()
        w=r['plan']['workflow'];self.assertEqual(w['review']['deleted_count'],1);self.assertEqual(w['review']['old_target_indices'],[0])
        before=CadDocument.open(self.source);protected=before.snapshot_group(2)
        report=self.approve_synthetic(r);self.assertEqual(report['deleted_count'],1);self.assertEqual(report['added_count'],1)
        after=CadDocument.open(self.folder/'case.jww');self.assertEqual(len(after.entities),len(before.entities))
        self.assertTrue(after.audit_group_unchanged(2,protected)['passed'])
        written=json.loads((self.folder/'case.changes.json').read_text(encoding='utf-8'))
        self.assertEqual(written['workflow']['settings'],w['settings']);self.assertEqual(written['workflow_sha256'],r['plan']['workflow_sha256'])
    def test_file_change_or_deletion_after_plan_does_not_change_execution(self):
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8');r=self.plan()
        self.config.write_text('this is now invalid TOML',encoding='utf-8')
        with patch('workflow_settings.load_workflow_settings',side_effect=AssertionError('No live config reads')):report=self.approve_synthetic(r)
        self.assertEqual(report['deleted_count'],1)
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8');r2=self.plan('second');self.config.unlink()
        self.assertEqual(self.approve_synthetic(r2)['deleted_count'],1)
    def test_file_created_after_absent_plan_does_not_change_archive(self):
        r=self.plan(archive_group=8);self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8')
        self.assertEqual(self.approve_synthetic(r)['deleted_count'],0)
    def test_first_empty_never_selects_new_group_when_source_changes(self):
        self.config.write_text('schema_version=1\n[building_replacement]\narchive_group="first_empty"',encoding='utf-8');r=self.plan()
        d=CadDocument.open(self.source);d.add_line((0,0),(1,0),layer_group=4)
        changed=self.folder/'changed.jww';d.save(changed);self.source.write_bytes(changed.read_bytes())
        with self.assertRaisesRegex(ValueError,'Source changed'):self.approve_synthetic(r)
        self.assertFalse((self.folder/'case.jww').exists());self.assertEqual(r['plan']['workflow']['context']['archive_group'],4)
    def test_old_and_incoming_change_or_wrong_approval_are_rejected(self):
        r=self.plan(archive_group=8)
        with self.assertRaises(ValueError):execute_plan(r['path'],approved_sha256='0'*64)
        self.incoming.write_bytes(self.incoming.read_bytes()+b'x')
        with self.assertRaises(ValueError):self.approve_synthetic(r)
    def test_action_review_and_effective_tampering_rejected_even_with_new_hash(self):
        r=self.plan(archive_group=8)
        for mode in ('actions','review','settings'):
            p=copy.deepcopy(r['plan'])
            if mode=='actions':p['actions'].insert(0,dict(op='delete_entities',indices=[0],kwargs={}))
            if mode=='review':p['workflow']['review']['deleted_count']=1
            if mode=='settings':p['workflow']['settings']['effective']['old_group_action']='delete'
            p['workflow_sha256']=_hash(p['workflow']);path=self.folder/(mode+'.json');path.write_text(json.dumps(p),encoding='utf-8')
            with self.assertRaises(ValueError):verify_plan(path,approved_sha256=file_sha256(path))
    def test_output_duplicate_and_config_collision_stop_before_editing(self):
        r=self.plan(archive_group=8);self.approve_synthetic(r)
        with self.assertRaises(FileExistsError):self.approve_synthetic(r)
        with self.assertRaises(ValueError):plan_building_replacement(self.source,self.incoming,self.config,self.folder/'bad.json',
          work_dir=self.folder,source_reference_indices=[2,3],target_reference_indices=[2,3],distance_tolerance=0,angle_tolerance=0,building_group=1,archive_group=8)
    def test_delete_argument_archive_contradiction_but_file_archive_is_explicitly_inactive(self):
        self.config.write_text('schema_version=1\n[building_replacement]\narchive_group=8',encoding='utf-8')
        r=self.plan(instruction_overrides={'profile':'quick'});self.assertIsNone(r['plan']['workflow']['context']['archive_group'])
        self.assertEqual(r['plan']['workflow']['settings']['inactive_settings'][0]['value'],8)
        with self.assertRaises(ValueError):self.plan('bad',archive_group=8,instruction_overrides={'profile':'quick'})
    def test_non_target_shared_definition_is_preserved(self):
        d=CadDocument.open(self.source);block=d.add_block_definition('SHARED',[Line((0,0),(1,0))]);d.place_block(block.number,(1,1),layer_group=2)
        p=self.folder/'with_block.jww';d.save(p);self.source=p
        before=CadDocument.open(p).snapshot_group(2)
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8');r=self.plan();self.approve_synthetic(r)
        self.assertTrue(CadDocument.open(self.folder/'case.jww').audit_group_unchanged(2,before)['passed'])
    def test_scale_tolerance_and_building_reference_scopes_are_not_relaxed(self):
        d=CadDocument.open(self.incoming);d.set_group_scale(1,50);p=self.folder/'scale.jww';d.save(p);self.incoming=p
        with self.assertRaises(ValueError):self.plan(archive_group=8)
        with self.assertRaises(ValueError):self.plan('reference',archive_group=8,building_group=3)
    def test_legacy_schema3_null_selection_is_still_rejected(self):
        from safe_edit import write_plan
        d=CadDocument.open(self.source);r=write_plan(d,[0],[dict(op='delete_entities',indices=[0],kwargs={})],self.folder/'legacy.jww',self.folder/'legacy.json')
        p=r['plan'];p.update(schema_version=3,selection=None,selection_sha256=None)
        path=self.folder/'bad_legacy.json';path.write_text(json.dumps(p),encoding='utf-8')
        with self.assertRaises(ValueError):verify_plan(path,approved_sha256=file_sha256(path))

    def test_full_no_empty_group_and_protection_candidate_evidence(self):
        from _replacement_contract import archive_candidates
        d=CadDocument.open(self.source);d.header=copy.deepcopy(d.header);d.header['layer_groups'][4]['protect']=1
        rows=archive_candidates(d,1)
        self.assertEqual(rows[0]['reason'],'writing');self.assertEqual(rows[4]['reason'],'protected')
        d=CadDocument.open(self.source)
        for g in range(4,16):d.add_line((0,0),(1,0),layer_group=g)
        p=self.folder/'full.jww';d.save(p);self.source=p
        self.config.write_text('schema_version=1\n[building_replacement]\narchive_group="first_empty"',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'No eligible'):self.plan()

    def test_building_writing_state_and_nonunit_alignment_are_refused(self):
        with self.assertRaisesRegex(ValueError,'Writing'):self.plan(archive_group=8,building_group=0)
        with self.assertRaises(ValueError):self.plan('coincident',archive_group=8,source_reference_indices=[2,2])
        with self.assertRaises(ValueError):self.plan('bad_tol',archive_group=8,distance_tolerance=None)

    def test_settings_changed_during_prepare_stops_before_plan_publication(self):
        import replacement_workflow as rw
        real=rw.prepare
        def change(*args,**kw):
            result=real(*args,**kw);self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8');return result
        with patch('replacement_workflow.prepare',side_effect=change):
            with self.assertRaisesRegex(ValueError,'changed during planning'):self.plan(archive_group=8)
        self.assertFalse((self.folder/'case.plan.json').exists())

    def test_post_save_failure_retains_output_but_never_reports_success(self):
        r=self.plan(archive_group=8)
        with patch('_replacement_contract.audit_result',side_effect=[dict(passed=True),ValueError('injected readback failure')]):
            with self.assertRaisesRegex(RuntimeError,'output retained'):self.approve_synthetic(r)
        self.assertTrue((self.folder/'case.jww').exists());self.assertFalse((self.folder/'case.changes.json').exists())
        self.assertEqual(file_sha256(self.source),self.input_hashes[self.source])

    def test_schema4_selection_proof_can_be_used_and_tampering_is_rejected(self):
        from safe_edit import write_plan
        r=self.plan(archive_group=8);q={'field':'layer_group','in':[1]}
        p=self.folder/'selected.json';out=self.folder/'selected.jww'
        receipt=write_plan(CadDocument.open(self.source),None,r['plan']['actions'],out,p,dependencies=[self.incoming],selection=q,workflow=r['plan']['workflow'])
        self.assertEqual(receipt['plan']['schema_version'],4);self.assertIsNotNone(receipt['plan']['selection'])
        self.assertTrue(self.approve_synthetic(receipt)['workflow_audit']['passed'])

    def test_open_and_legacy_plan_do_not_load_workflow_configuration(self):
        from safe_edit import write_plan
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8')
        with patch('workflow_settings.load_workflow_settings',side_effect=AssertionError('No implicit open/settings read')):
            d=CadDocument.open(self.source)
            receipt=write_plan(d,[0],[dict(op='delete_entities',indices=[0],kwargs={})],self.folder/'old.jww',self.folder/'old.json')
        self.assertEqual(receipt['plan']['schema_version'],2)

    def test_first_empty_counts_hidden_metadata_roots(self):
        from _replacement_contract import archive_candidates
        d=CadDocument.open(self.source);d._source_records=copy.deepcopy(d._source_records)
        d._source_records['entities'].append({'type':'TEXT','base':{'layer_group':4},'content':'Printer_PaperSize=9'})
        self.assertEqual(archive_candidates(d,1)[4]['reason'],'occupied')

    def test_delete_does_not_bypass_unsupported_target_blocks(self):
        d=CadDocument.open(self.source);b=d.add_block_definition('TARGET',[Line((0,0),(1,0))]);d.place_block(b.number,(0,0),layer_group=1)
        p=self.folder/'target_block.jww';d.save(p);self.source=p
        self.config.write_text('schema_version=1\nprofile="quick"',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'references'):self.plan()

    def test_fault_injected_import_omission_is_rejected_before_plan(self):
        import safe_edit
        real=safe_edit._apply_edit_actions
        def drop(cad,plan,**kw):
            result=real(cad,plan,**kw);cad.entities=tuple(e for e in cad.entities if e.source_index is not None);return result
        with patch('safe_edit._apply_edit_actions',side_effect=drop):
            with self.assertRaisesRegex(ValueError,'counts disagree'):self.plan(archive_group=8)
        self.assertFalse((self.folder/'case.plan.json').exists())

    def test_fault_injected_original_attribute_change_is_rejected_before_plan(self):
        import safe_edit
        real=safe_edit._apply_edit_actions
        def change(cad,plan,**kw):
            result=real(cad,plan,**kw);cad.entities[0].attributes['pen_color']=7;return result
        with patch('safe_edit._apply_edit_actions',side_effect=change):
            with self.assertRaisesRegex(ValueError,'original element changed'):self.plan(archive_group=8)
        self.assertFalse((self.folder/'case.plan.json').exists())

if __name__=='__main__':unittest.main()

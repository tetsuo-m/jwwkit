"""Explicit read-only policy; immutable snapshots and strict fields."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from workflow_settings import load_workflow_settings,resolve_workflow_settings,_verify_resolved,_assert_live_snapshot

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.path=self.folder/'jww_workflow.toml'
    def config(self,text):self.path.write_bytes(text.encode('utf-8'));return load_workflow_settings(self.folder)
    def test_absent_is_careful_without_creating_any_file(self):
        loaded=load_workflow_settings(self.folder);r=resolve_workflow_settings(loaded)
        self.assertFalse(loaded['present']);self.assertIsNone(loaded['raw_sha256']);self.assertFalse(self.path.exists())
        self.assertEqual(r['effective'],dict(old_group_action='archive',archive_group=None))
    def test_profiles_and_typed_archive_values(self):
        for value,expected in (('8',8),('0',0),('15',15),('"first_empty"','first_empty')):
            d=self.config('schema_version=1\n[building_replacement]\narchive_group='+value)
            self.assertEqual(resolve_workflow_settings(d)['effective']['archive_group'],expected)
        self.assertEqual(resolve_workflow_settings(self.config('schema_version=1\nprofile="quick"'))['effective']['old_group_action'],'delete')
    def test_raw_hash_preserves_comments_and_crlf(self):
        raw='# コメント\r\nschema_version=1\r\nprofile="careful"\r\n';d=self.config(raw)
        self.assertEqual(d['raw_utf8'],raw);self.assertEqual(d['raw_sha256'],hashlib.sha256(raw.encode('utf-8')).hexdigest())
    def test_no_parent_home_or_environment_lookup(self):
        self.config('schema_version=1\nprofile="quick"');child=self.folder/'child';child.mkdir()
        with patch.dict('os.environ',{'JWW_WORKFLOW_CONFIG':str(self.path)}):r=resolve_workflow_settings(load_workflow_settings(child))
        self.assertEqual(r['effective']['old_group_action'],'archive')
    def test_unknown_fields_versions_profiles_and_forbidden_fields(self):
        for text in ('schema_version=3','schema_version=true','schema_version=1.0','profile="quick"',
          'schema_version=1\nprofile="fast"','schema_version=1\nProfile="careful"',
          'schema_version=1\nunknown=1','schema_version=1\nauto_approve=true',
          'schema_version=1\n[open]\nnormalize=true','schema_version=1\n[safety]\noverwrite=true',
          'schema_version=1\n[building_replacement]\ntolerance=0'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.config(text)
    def test_invalid_action_archive_types_and_duplicate_keys(self):
        for value in ('true','-1','16','8.0','"8"','"first"','[8]','nan','1979-05-27'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.config('schema_version=1\n[building_replacement]\narchive_group='+value)
        for text in ('schema_version=1\nschema_version=1','schema_version=1\nprofile=true',
          'schema_version=1\n[building_replacement]\nold_group_action="remove"','schema_version=1\n[building_replacement]\nold_group_action=true'):
            with self.assertRaises(ValueError):self.config(text)
    def test_size_utf8_and_bom_fail_closed(self):
        prefix=b'schema_version=1\n#';self.path.write_bytes(prefix+b'x'*(65536-len(prefix)))
        self.assertTrue(load_workflow_settings(self.folder)['present'])
        for raw in (prefix+b'x'*(65537-len(prefix)),b'\xff',b'\xef\xbb\xbfschema_version=1'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):load_workflow_settings(self.folder)
    def test_unreadable_file_is_not_absent(self):
        self.config('schema_version=1')
        with patch.object(Path,'open',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):load_workflow_settings(self.folder)
    def test_directory_is_not_a_settings_file(self):
        self.path.mkdir()
        with self.assertRaises(ValueError):load_workflow_settings(self.folder)
    def test_symlink_or_reparse_is_refused(self):
        self.config('schema_version=1')
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'LINK'):load_workflow_settings(self.folder)
    def test_chat_profile_beats_file_item_and_chat_item_beats_profile(self):
        loaded=self.config('schema_version=1\nprofile="quick"\n[building_replacement]\nold_group_action="archive"')
        self.assertEqual(resolve_workflow_settings(loaded,instruction_overrides={'profile':'quick'})['effective']['old_group_action'],'delete')
        r=resolve_workflow_settings(loaded,instruction_overrides={'profile':'quick','building_replacement':{'old_group_action':'archive','archive_group':8}},instruction_evidence='今回は退避')
        self.assertEqual(r['effective']['old_group_action'],'archive');self.assertEqual(r['effective']['archive_group'],8)
        self.assertEqual(r['provenance']['old_group_action'],'instruction.building_replacement.old_group_action')
    def test_config_archive_inactive_for_delete_but_explicit_contradiction_refused(self):
        loaded=self.config('schema_version=1\n[building_replacement]\narchive_group="first_empty"')
        r=resolve_workflow_settings(loaded,instruction_overrides={'profile':'quick'})
        self.assertIsNone(r['effective']['archive_group']);self.assertEqual(r['inactive_settings'][0]['value'],'first_empty')
        with self.assertRaises(ValueError):resolve_workflow_settings(loaded,instruction_overrides={'profile':'quick','building_replacement':{'archive_group':8}})
    def test_invalid_file_not_hidden_by_valid_chat(self):
        with self.assertRaises(ValueError):self.config('schema_version=1\noverwrite=true')
        d=load_workflow_settings(self.folder)if not self.path.exists()else None
        self.assertIsNone(d)
    def test_snapshot_validation_does_not_read_live_file(self):
        r=resolve_workflow_settings(self.config('schema_version=1\nprofile="quick"'))
        self.path.unlink()
        with patch('workflow_settings.load_workflow_settings',side_effect=AssertionError('No live read')):self.assertEqual(_verify_resolved(r),r)
    def test_snapshot_tampering_and_unknown_instruction_are_refused(self):
        r=resolve_workflow_settings(self.config('schema_version=1'))
        for key,value in (('effective',{'old_group_action':'delete'}),('selected_profile','quick'),('extra',True)):
            bad=copy.deepcopy(r);bad[key]=value
            with self.assertRaises(ValueError):_verify_resolved(bad)
        with self.assertRaises(ValueError):resolve_workflow_settings(r['config_snapshot'],instruction_overrides={'auto_approve':True})
    def test_planning_detects_file_changes_deletion_or_appearance(self):
        absent=resolve_workflow_settings(load_workflow_settings(self.folder));self.config('schema_version=1')
        with self.assertRaises(ValueError):_assert_live_snapshot(absent)
        r=resolve_workflow_settings(load_workflow_settings(self.folder));self.path.write_text('schema_version=1\nprofile="quick"',encoding='utf-8')
        with self.assertRaises(ValueError):_assert_live_snapshot(r)
        self.path.unlink()
        with self.assertRaises(ValueError):_assert_live_snapshot(r)
    def test_two_work_folders_and_returned_values_are_independent(self):
        quick=resolve_workflow_settings(self.config('schema_version=1\nprofile="quick"'))
        other=self.folder/'other';other.mkdir();careful=resolve_workflow_settings(load_workflow_settings(other))
        self.assertNotEqual(quick['effective'],careful['effective']);quick['profile_catalog']['careful']['old_group_action']='delete'
        self.assertEqual(resolve_workflow_settings(load_workflow_settings(other))['effective']['old_group_action'],'archive')

if __name__=='__main__':unittest.main()


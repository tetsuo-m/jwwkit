"""Execute the integrated workflow guide with synthetic data, never GUI."""
from pathlib import Path
import json,re,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument

class ReadingEditingGuideTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  text=(R/'docs/reading_to_editing.md').read_text(encoding='utf-8')
  blocks=re.findall(r'```python\n(.*?)\n```',text,re.S);assert len(blocks)==1
  cls.ns={};exec(compile(blocks[0],'docs/reading_to_editing.md','exec'),cls.ns)
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
  self.source=self.folder/'input.jww';c=CadDocument.open(R/'src/resources/empty_template.jww')
  c.set_group_scale(0,50);c.set_group_scale(1,25)
  c.add_text((0,0),content='ＡＷ－01',units='real');c.add_text((200,0),content='aw ‐02',units='real')
  c.add_text((0,0),content='OTHER',layer_group=1,units='real');c.add_line((0,100),(100,100),units='real');c.save(self.source)
  self.original=self.source.read_bytes()
 def test_readonly_views_shape_nearest_and_equivalence_together(self):
  r=self.ns['inspect_local'](self.source,[0,0],group=0,tie_tolerance=0,detail_limit=1)
  self.assertEqual(r['text_match_count'],2);self.assertTrue(r['text_search_complete']);self.assertTrue(r['details']['truncated']);self.assertTrue(r['closest']['complete'])
  self.assertTrue(r['geometry']['evaluation_complete']);self.assertEqual(self.source.read_bytes(),self.original)
 def test_separate_query_plan_and_approved_common_result(self):
  output=self.folder/'out.jww';p=self.ns['prepare_change'](self.source,output,self.folder/'edit.json',group=0,delta_real_mm=[10,0])
  self.assertEqual(p['status'],'planned');self.assertEqual(p['projected_counts']['modified'],2);self.assertFalse(output.exists())
  value=json.loads(Path(p['plan']['path']).read_text(encoding='utf-8'));self.assertEqual(value['schema_version'],5);self.assertIsNotNone(value['selection'])
  r=self.ns['run_approved_change'](p['plan']['path'],p['plan']['sha256']);self.assertEqual(r['phase'],'verified');self.assertEqual(r['counts']['modified'],2)
  before=CadDocument.open(self.source);after=CadDocument.open(output)
  self.assertEqual([e.raw for e in before.entities[2:]],[e.raw for e in after.entities[2:]])
  self.assertEqual([e.geometry['content']for e in after.entities[:2]],['ＡＷ－01','aw ‐02']);self.assertEqual(self.source.read_bytes(),self.original)
 def test_empty_scope_refuses_without_plan_or_output(self):
  with self.assertRaisesRegex(ValueError,'対象0件'):self.ns['prepare_change'](self.source,self.folder/'out.jww',self.folder/'empty.json',group=1,delta_real_mm=[10,0])
  self.assertFalse((self.folder/'empty.json').exists());self.assertFalse((self.folder/'out.jww').exists())
 def test_source_change_after_plan_refuses_execution(self):
  p=self.ns['prepare_change'](self.source,self.folder/'out.jww',self.folder/'edit.json',group=0,delta_real_mm=[10,0]);self.source.write_bytes(self.original+b'x')
  r=self.ns['run_approved_change'](p['plan']['path'],p['plan']['sha256']);self.assertEqual(r['status'],'rejected');self.assertFalse((self.folder/'out.jww').exists())

if __name__=='__main__':unittest.main()

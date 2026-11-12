"""Extract and execute every Python block of the query usage guide."""
import copy,json,re,sys,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument
from safe_edit import execute_plan,file_sha256


class QueryGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.source=self.folder/'input.jww'
        cad=CadDocument.open(R/'src/resources/empty_template.jww');cad.set_group_scale(0,100)
        cad.add_line((0,0),(20,0),layer=3);cad.add_arc((0,0),10,0,2,layer=5)
        cad.add_text((0,0),content='AW-01');cad.save(self.source)
        blocks=re.findall(r'```python\n(.*?)\n```',(R/'docs/search_queries.md').read_text(encoding='utf-8'),re.S)
        self.assertEqual(len(blocks),1);self.ns={}
        for code in blocks:exec(compile(code,'docs/search_queries.md','exec'),self.ns)

    def test_inspection_example_does_not_change_source(self):
        before=self.source.read_bytes();result=self.ns['inspect_drawing'](self.source)
        self.assertEqual(result['long_shapes'],(0,1));self.assertEqual(result['aw_texts'],(2,))
        self.assertEqual(result['horizontal_lines'],(0,));self.assertEqual(result['marked_lines'],())
        self.assertEqual(self.source.read_bytes(),before)

    def test_plan_example_requires_external_sha_then_saved_all_fields_match(self):
        before=self.source.read_bytes();output=self.folder/'new.jww';plan=self.folder/'review.json'
        receipt=self.ns['plan_search_move'](self.source,output,plan)
        self.assertFalse(output.exists());self.assertEqual(receipt['plan']['schema_version'],3)
        self.assertEqual(receipt['plan']['selection']['input_query'],self.ns['LONG_SHAPES'])
        with self.assertRaises(TypeError):execute_plan(plan)
        report=execute_plan(plan,approved_sha256=receipt['sha256'])
        self.assertEqual(report['modified_count'],2);self.assertTrue(report['saved_all_fields_match'])
        self.assertEqual(self.source.read_bytes(),before)

    def test_zero_matches_stops_without_creating_plan(self):
        empty=self.folder/'empty.jww';CadDocument.open(R/'src/resources/empty_template.jww').save(empty)
        plan=self.folder/'review.json'
        with self.assertRaisesRegex(ValueError,'0件'):
            self.ns['plan_search_move'](empty,self.folder/'new.jww',plan)
        self.assertFalse(plan.exists())


if __name__=='__main__':unittest.main()

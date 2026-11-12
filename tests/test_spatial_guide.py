from pathlib import Path
import json,os,re,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument
class SpatialGuideTests(unittest.TestCase):
    def test_every_guide_example_runs_and_source_stays_unchanged(self):
        with tempfile.TemporaryDirectory()as tmp:
            folder=Path(tmp);source=folder/'input.jww'
            doc=CadDocument.open(R/'src/resources/empty_template.jww');doc.add_line((0,0),(10,20));doc.save(source)
            before=source.read_bytes();blocks=re.findall(r'```python\n(.*?)```',(R/'docs/spatial_search.md').read_text(encoding='utf-8'),re.S)
            self.assertEqual(len(blocks),1);old=Path.cwd()
            try:
                os.chdir(folder)
                for block in blocks:exec(compile(block,'docs/spatial_search.md','exec'),{})
            finally:os.chdir(old)
            value=json.loads((folder/'spatial_inspection.json').read_text(encoding='utf-8'))
            self.assertTrue(value['closest']['complete']);self.assertEqual(value['closest']['scope_count'],1)
            self.assertTrue(value['anchors']['details_omitted']);self.assertEqual(source.read_bytes(),before)

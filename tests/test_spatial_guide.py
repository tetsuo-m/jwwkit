from jwwkit import template_path, guide_paths
from pathlib import Path
import json,os,re,tempfile,unittest
from jwwkit.cad_model import CadDocument
class SpatialGuideTests(unittest.TestCase):
    def test_every_guide_example_runs_and_source_stays_unchanged(self):
        with tempfile.TemporaryDirectory()as tmp:
            folder=Path(tmp);source=folder/'input.jww'
            doc=CadDocument.open(template_path());doc.add_line((0,0),(10,20));doc.save(source)
            before=source.read_bytes();blocks=re.findall(r'```python\n(.*?)```',(guide_paths()['usage_guide'].with_name('spatial_search.md')).read_text(encoding='utf-8'),re.S)
            self.assertEqual(len(blocks),1);old=Path.cwd()
            try:
                os.chdir(folder)
                for block in blocks:exec(compile(block,'docs/spatial_search.md','exec'),{})
            finally:os.chdir(old)
            value=json.loads((folder/'spatial_inspection.json').read_text(encoding='utf-8'))
            self.assertTrue(value['closest']['complete']);self.assertEqual(value['closest']['scope_count'],1)
            self.assertTrue(value['anchors']['details_omitted']);self.assertEqual(source.read_bytes(),before)

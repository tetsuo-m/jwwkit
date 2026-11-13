from jwwkit import template_path, guide_paths
"""Run every U2 guide example against a synthetic local input."""
from pathlib import Path
import json,os,re,tempfile,unittest
from jwwkit.cad_model import CadDocument
class GeometryGuideTests(unittest.TestCase):
    def test_all_examples_execute_without_changing_source(self):
        with tempfile.TemporaryDirectory()as tmp:
            folder=Path(tmp);source=folder/'input.jww'
            doc=CadDocument.open(template_path());doc.add_line((0,0),(10,20));doc.save(source)
            before=source.read_bytes();blocks=re.findall(r'```python\n(.*?)```',(guide_paths()['usage_guide'].with_name('geometry_view.md')).read_text(encoding='utf-8'),re.S)
            self.assertEqual(len(blocks),1);old=Path.cwd()
            try:
                os.chdir(folder)
                for block in blocks:exec(compile(block,'docs/geometry_view.md','exec'),{})
            finally:os.chdir(old)
            result=json.loads((folder/'geometry.json').read_text(encoding='utf-8'))
            self.assertEqual(result['counts']['total'],1);self.assertEqual(result['first']['bbox']['status'],'exact')
            self.assertTrue(result['summary']['evaluation_complete']);self.assertEqual(source.read_bytes(),before)
